
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

class ImplicationsMode(Enum):
    NONE = auto()
    ALL  = auto()

load_dotenv()
DPD_SQLITE_LOCATION = os.getenv('DFD_DATABASE_LOCATION') or ''
TS_SQLITE_LOCATION = os.getenv('TAG_STUDIO_DATABASE_LOCATION') or ''

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


RATE_LIMIT_INTERVAL = 1.01
added_tags:list[tuple[int, str]] = []


async def get_implications(session:aiohttp.ClientSession, booru_tag_name:str) -> list[dict]:
    async with session.get(f'https://danbooru.donmai.us/tag_implications.json?search[name_matches]={booru_tag_name}') as resp:
        resp.raise_for_status()
        return await resp.json()

async def create_parents_from_implications(session:aiohttp.ClientSession, database: Database) -> tuple[int, int]:
    tags_checked = 0
    implications_added = 0
    skip_tags:list[int] = []
    with alive_bar(len(added_tags), title="Adding Implications between Tags") as bar:
        for tup in added_tags:
            start = time.time()
            tag_implications: list[dict[str, str]] = await get_implications(session, tup[1])
            # the x-rate-limit header does not exist anymore so we rudimentary throttle ourselves 
            if tags_checked > 500: # Make use of burst pool
                await asyncio.sleep(max(0, RATE_LIMIT_INTERVAL - (time.time() - start)))
            tags_checked += 1
            for tag_implication in tag_implications:
                if tag_implication.get('status') != 'active':
                    continue
                is_antecedent_name = True if tag_implication.get('antecedent_name') == tup[1] else False
                other_id = database.get_tag_id(str(tag_implication.get('consequent_name') if is_antecedent_name else tag_implication.get('antecedent_name')))
                if other_id == -1 or other_id in skip_tags:
                    continue
                implications_added += 1
                if is_antecedent_name:
                    database.add_parent_to_tag(tup[0], other_id)
                else:
                    database.add_parent_to_tag(other_id, tup[0])
            skip_tags.append(tup[0])
            bar()
    return (tags_checked, implications_added)


async def _add_tags_to_ts_file(session:aiohttp.ClientSession, database: Database, tags: List[str], entry_id:int, color:dict[str,str], category_id:int | None, mode:ImplicationsMode):
    if category_id is None:
        return
    for tag in tags:
        tag_id: int = database.get_tag_id(tag)
        if tag_id == -1:
            database.insert_new_tag(tag, color.get('namespace'), color.get('slug'))
            tag_id = database.get_tag_id(tag)
            added_tags.append((tag_id, tag))
            database.add_parent_to_tag(tag_id, category_id)
        database.add_tag_to_file(tag_id, entry_id)
    database.commit()



async def add_tags_to_ts_file(session:aiohttp.ClientSession, database: Database, file_info:PostData,  categories:dict[str, int], mode:ImplicationsMode) -> None:
    file_entry_id: int = database.get_file_id(file_info.file_name)
    if file_entry_id == -1:
        return
    check_tag_id = database.get_tag_id(file_info.tags_artist[0])
    if check_tag_id != -1:
        if database.does_file_have_tag(check_tag_id, file_entry_id):
            return # If file has the first tag, assume this file has been processed already
    await asyncio.gather(
    _add_tags_to_ts_file(session, database, file_info.tags_artist, file_entry_id, ARTIST_COLOR, categories.get('Artist'), mode),
    _add_tags_to_ts_file(session, database, file_info.tags_copyright, file_entry_id, COPYRIGHT_COLOR, categories.get('Copyright'), mode),
    _add_tags_to_ts_file(session, database, file_info.tags_character, file_entry_id, CHARACTER_COLOR, categories.get('Character'), mode),
    _add_tags_to_ts_file(session, database, file_info.tags_general, file_entry_id, GENERAL_COLOR, categories.get('General'), mode),
    _add_tags_to_ts_file(session, database, file_info.tags_meta, file_entry_id, META_COLOR, categories.get('Meta'), mode),
    _add_tags_to_ts_file(session, database, [f"rating:{file_info.rating}"], file_entry_id, META_COLOR, categories.get('Meta'), mode)
    )
  



async def a_main(mode:ImplicationsMode):
    print("Adding tags to files")

    start = time.time()
    tasks = []
    async with aiohttp.ClientSession() as session:
        
        with Database(DPD_SQLITE_LOCATION,TS_SQLITE_LOCATION) as database:
            categories = database.get_categories()
            last_id = 0
            chunk_size = 200
            post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)
            while post_datas is not None and len(post_datas) != 0:
                for post_data in post_datas:
                    task = asyncio.create_task(
                        add_tags_to_ts_file(session, database, post_data, categories, mode)
                    )
                    tasks.append(task)
                await asyncio.gather(*tasks)
                last_id = post_datas[len(post_datas)-1].post_id
                post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)
    
            if mode is ImplicationsMode.ALL:
                print("Finished adding tags to files. Now adding implications between tags.")
                print("This process will take some time. You can already use TagStudio to view your files, but please refrain from:")
                print(" - adding/removing tags on files")
                print(" - adding/removing tags in the TagStudio Library")
                print(" - Editing Tags")
                (tags_checked, implications_added) = await create_parents_from_implications(session, database)
                print("\r\n")
                print(f"{tags_checked} tags checked")
                print(f"{implications_added} implications added")
    print("Done")
    end = time.time()
    print(f"Runtime: {end - start} seconds")
    print(f"{int((end-start) // 60)} Minutes and {int((end-start) % 60)} Seconds")

    time.sleep(5)
        

def main(mode:ImplicationsMode):
    asyncio.run(a_main(mode))

if __name__ == "__main__":
    main(ImplicationsMode.ALL)