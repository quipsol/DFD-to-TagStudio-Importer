
from sys import exit as sys_exit
import os
from typing import List
from database import Database, PostData
from dotenv import load_dotenv
import asyncio
import aiohttp
from alive_progress import alive_bar
import time
from enum import Enum, auto
from pathlib import Path
import json

load_dotenv()
DPD_SQLITE_LOCATION = os.getenv('DFD_DATABASE_LOCATION') or ''
TS_SQLITE_LOCATION = os.getenv('TAG_STUDIO_DATABASE_LOCATION') or ''
IMPORT_IMPLICATIONS = (os.getenv('IMPORT_IMPLICATIONS') or 'False').lower() == 'true'
SLOW_MODE = (os.getenv('SLOW_MODE') or 'False').lower() == 'true'


ARTIST_COLOR = dict(zip(['namespace', 'slug'], (os.getenv('ARTIST_COLOR', '') or 'tagstudio-standard,red-orange').split(',')))
COPYRIGHT_COLOR = dict(zip(['namespace', 'slug'], (os.getenv('COPYRIGHT_COLOR', '') or 'tagstudio-standard,indigo').split(',')))
CHARACTER_COLOR = dict(zip(['namespace', 'slug'], (os.getenv('CHARACTER_COLOR', '') or 'tagstudio-standard,green').split(',')))
GENERAL_COLOR = dict(zip(['namespace', 'slug'], (os.getenv('GENERAL_COLOR', '') or 'tagstudio-standard,blue').split(',')))
META_COLOR = dict(zip(['namespace', 'slug'], (os.getenv('META_COLOR', '') or 'tagstudio-standard,yellow').split(',')))

if DPD_SQLITE_LOCATION is None or TS_SQLITE_LOCATION is None:
    print("Please set the neccessary values in your .env file:")
    if DPD_SQLITE_LOCATION is None:
        print("'DANBOORU_DOWNLOADER_SQLITE_LOCATION' needs to be set.")
    if TS_SQLITE_LOCATION is None:
        print("'TAG_STUDIO_SQLITE_LOCATION' needs to be set.")
    sys_exit(0)

TAG_BUFFER_FILENAME = 'temporary_tag_buffer.txt'
CONCURRENCY = 1 if SLOW_MODE else 3 # More than 3 increases chance of running into "too many requests" denial repeatedly


async def worker(session:aiohttp.ClientSession, database:Database,
                 idx: int, data: dict[str, str],
                 stop_event:asyncio.Event, semaphore:asyncio.Semaphore) -> tuple[int, int]:
        if stop_event.is_set():
            return (-1,0)
        async with semaphore:
            #print(f"Entered semaphore with worker {idx}")
            if stop_event.is_set():
                return (-1,0)
            try:
                tag_implications: list[dict[str, str]] =await get_implications_from_api(session, data)  
            except Exception as e:
                print(e)
                stop_event.set()
                raise
        implications_added:int = 0
        for tag_implication in tag_implications:
                if tag_implication.get('status') != 'active':
                    continue
                is_antecedent_name = True if tag_implication.get('antecedent_name') == data['tag'] else False
                other_id = database.get_tag_id(str(tag_implication.get('consequent_name') if is_antecedent_name else tag_implication.get('antecedent_name')))
                if other_id == -1:
                    continue
                # cannot access local variable 'implications_added' where it is not associated with a value
                if is_antecedent_name:
                    implications_added += database.add_parent_to_tag(int(data['tag_id']), other_id)
                else:
                    implications_added += database.add_parent_to_tag(other_id, int(data['tag_id']))
        return (idx, implications_added)

async def get_implications_from_api(session:aiohttp.ClientSession, data: dict[str, str]) -> list[dict]:
    async with session.get(f'https://danbooru.donmai.us/tag_implications.json?search[name_matches]={data['tag']}') as resp:
        resp.raise_for_status()
        return await resp.json() 

async def create_parents_from_implications(session:aiohttp.ClientSession, database: Database) -> tuple[int, int]:
    tags_checked = 0
    implications_added = 0
    file_path = Path(TAG_BUFFER_FILENAME)
    lines = file_path.read_text().splitlines()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    completed = set()
    stop_event = asyncio.Event()

    tasks = [
            asyncio.create_task(worker(session, database, i, json.loads(line), stop_event, semaphore))
            for i, line in enumerate(lines)
        ]
    try:
        # Ran into issue one time where alive_bar never moved. Unclear if alive bar issue
        # or the implication logic was at fault. Has never happened again since!?
        with alive_bar(len(tasks), title='Adding implications') as bar:
            for completed_task in asyncio.as_completed(tasks):
                result = await completed_task
                if result[0] == -1:
                    continue
                tags_checked += 1
                completed.add(result[0])
                implications_added += result[1]
                bar()
    except Exception as e:
        print(e)
        stop_event.set()
        print(
                "\nRate limit hit and/or burst pool exhausted. This is normal.\n"
                "Please restart in a few hours.\n"
                "If this issue persists, try running in slow mode by adding SLOW_MODE=True to your .env file."
            )
        for t in tasks:
            t.cancel()
    finally:
        database.commit()
        # Compute remaining lines in original order
        remaining = [
            line for i, line in enumerate(lines)
            if i not in completed
        ]
        print(f"Remaining tags: {len(remaining)}")
        file_path.write_text(
            "\n".join(remaining) + ("\n" if remaining else "")
        )
    return (tags_checked, implications_added)



async def insert_tags_into_temporary_file(tags:list[tuple[int, str]]) -> None:
    with open(TAG_BUFFER_FILENAME, "a") as myfile:
        for tag in tags:
            myfile.write(f'{{"tag_id": "{tag[0]}", "tag": "{tag[1]}"}}\n')

async def _add_tags_to_ts_file(database: Database, tags: List[str], entry_id:int, color:dict[str,str], category_id:int | None):
    if category_id is None:
        return
    new_tags:list[tuple[int, str]] = []
    for tag in tags:
        tag_id: int = database.get_tag_id(tag)
        if tag_id == -1:
            database.insert_new_tag(tag, color.get('namespace'), color.get('slug'))
            tag_id = database.get_tag_id(tag)
            new_tags.append((tag_id, tag))
            database.add_parent_to_tag(tag_id, category_id)
        database.add_tag_to_file(tag_id, entry_id)
    await insert_tags_into_temporary_file(new_tags)

async def add_tags_to_ts_file(database: Database, file_info:PostData,  categories:dict[str, int]) -> None:
    file_entry_id: int = database.get_file_id(file_info.file_name)
    if file_entry_id == -1:
        return
    check_tag_id = database.get_tag_id(file_info.tags_artist[0])
    if check_tag_id != -1:
        if database.does_file_have_tag(check_tag_id, file_entry_id):
            return # If file has the first tag, assume this file has been processed already
    await asyncio.gather(
    _add_tags_to_ts_file(database, file_info.tags_artist, file_entry_id, ARTIST_COLOR, categories.get('Artist')),
    _add_tags_to_ts_file(database, file_info.tags_copyright, file_entry_id, COPYRIGHT_COLOR, categories.get('Copyright')),
    _add_tags_to_ts_file(database, file_info.tags_character, file_entry_id, CHARACTER_COLOR, categories.get('Character')),
    _add_tags_to_ts_file(database, file_info.tags_general, file_entry_id, GENERAL_COLOR, categories.get('General')),
    _add_tags_to_ts_file(database, file_info.tags_meta, file_entry_id, META_COLOR, categories.get('Meta')),
    _add_tags_to_ts_file(database, [f"rating:{file_info.rating}"], file_entry_id, META_COLOR, categories.get('Meta'))
    )
    database.commit()
  


async def a_main():
    print("Adding tags to files")

    start = time.time()
    tasks = []
    async with aiohttp.ClientSession() as session:
        
        with Database(DPD_SQLITE_LOCATION,TS_SQLITE_LOCATION) as database:
            categories = database.get_categories()
            last_id = 0
            chunk_size = 200
            post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)
            data_exists:bool = post_datas is not None
            while data_exists and len(post_datas) != 0:
                for post_data in post_datas:
                    task = asyncio.create_task(
                        add_tags_to_ts_file(database, post_data, categories)
                    )
                    tasks.append(task)
                await asyncio.gather(*tasks)
                last_id = post_datas[len(post_datas)-1].post_id
                post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)
    
            if IMPORT_IMPLICATIONS:
                print("Finished adding tags to files. Now adding implications between tags.")
                print("This process will take some time. You can already use TagStudio to view your files, but please refrain from:")
                print(" - adding/removing tags on files")
                print(" - adding/removing tags in the TagStudio Library")
                print(" - Editing Tags")
                print(" - Editing Files")
                (tags_checked, implications_added) = await create_parents_from_implications(session, database)
                database.commit()
                print(f"{tags_checked} tags checked")
                print(f"{implications_added} implications added")
    print("Done")
    end = time.time()
    print(f"Runtime: {end - start} seconds")
    print(f"{int((end-start) // 60)} Minutes and {int((end-start) % 60)} Seconds")
    time.sleep(3)
        

def main():
    if not os.path.exists(f'./{TAG_BUFFER_FILENAME}'):
        with open(TAG_BUFFER_FILENAME, 'x') as file:
            pass
    asyncio.run(a_main())

if __name__ == "__main__":
    main()