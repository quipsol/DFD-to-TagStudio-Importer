
from sys import exit as sys_exit
import os
from typing import List
from database import Database, PostData
from dotenv import load_dotenv
import asyncio
import aiohttp
from alive_progress import alive_bar
import time

RATE_LIMIT_INTERVAL = 1.0 # make sure to never hit poll limit
request_lock = asyncio.Lock()
load_dotenv()
DPD_SQLITE_LOCATION = os.getenv('DANBOORU_DOWNLOADER_SQLITE_LOCATION')
TS_SQLITE_LOCATION = os.getenv('TAG_STUDIO_SQLITE_LOCATION')

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

tags_checked = 0
implications_found = 0
implications_added = 0
global_start_time = time.time()
total_coroutines = 0

async def get_implications(session, booru_tag_name:str) -> str:
    async with request_lock:
        asyncio.sleep(RATE_LIMIT_INTERVAL)
        total_coroutines += 1
        async with session.get(f"https://danbooru.donmai.us/tag_implications.json?search[name_matches]={booru_tag_name}") as resp:
            resp.raise_for_status()
            return await resp.json()

async def create_parents_from_implications(session, database: Database, booru_tag_name:str, ts_tag_id:int) -> None:
    global tags_checked
    global implications_found
    global implications_added
    tag_implications = await get_implications(session, booru_tag_name)
    tags_checked += 1
    if tags_checked % 25 == 0:
        print(f"Im still running :)    {tags_checked} tags checked so far")

    for tag_implication in tag_implications:
        if tag_implication.get('status') != 'active':
            continue
        implications_found += 1
        is_antecedent_name = True if tag_implication.get('antecedent_name') == booru_tag_name else False
        other_id = database.get_tag_id(tag_implication.get('consequent_name') if is_antecedent_name else tag_implication.get('antecedent_name'))
        if other_id == -1:
            continue
        implications_added += 1
        if is_antecedent_name:
            database.add_parent_to_tag(ts_tag_id, other_id)
        else:
            database.add_parent_to_tag(other_id, ts_tag_id)


async def _add_tags_to_ts_file(session, database: Database, tags: List[str], file_name:str, namespace:str, slug:str, category_id:int):
    if not tags:
        return
    entry_id = database.get_file_id(file_name)
    if entry_id == -1:
        return
    check_tag_id = database.get_tag_id(tags[0])
    if check_tag_id != -1:
        if database.does_file_have_tag(check_tag_id, entry_id):
            return # If it has the first tag, assume this file has been processed already
    
    for tag in tags:
        tag_id = database.get_tag_id(tag)
        if tag_id == -1:
            database.insert_new_tag(tag, namespace, slug)
            tag_id = database.get_tag_id(tag)
            await create_parents_from_implications(session, database, tag, tag_id)
            database.add_parent_to_tag(tag_id, category_id)
        database.add_tag_to_file(tag_id, entry_id)
    database.commit()



async def add_tags_to_ts_file(session, database: Database, file_info:PostData,  categories:dict[str,int])-> None:
    await _add_tags_to_ts_file(session, database, file_info.tags_artist, file_info.file_name, ARTIST_COLOR.get('namespace'), ARTIST_COLOR.get('slug'), categories.get('Artist'))
    await _add_tags_to_ts_file(session, database, file_info.tags_copyright, file_info.file_name, COPYRIGHT_COLOR.get('namespace'), COPYRIGHT_COLOR.get('slug'), categories.get('Copyright'))
    await _add_tags_to_ts_file(session, database, file_info.tags_character, file_info.file_name, CHARACTER_COLOR.get('namespace'), CHARACTER_COLOR.get('slug'), categories.get('Character'))
    await _add_tags_to_ts_file(session, database, file_info.tags_general, file_info.file_name, GENERAL_COLOR.get('namespace'), GENERAL_COLOR.get('slug'), categories.get('General'))
    await _add_tags_to_ts_file(session, database, file_info.tags_meta, file_info.file_name, META_COLOR.get('namespace'), META_COLOR.get('slug'), categories.get('Meta'))
    await _add_tags_to_ts_file(session, database, [f"rating:{file_info.rating}"], file_info.file_name, META_COLOR.get('namespace'), META_COLOR.get('slug'), categories.get('Meta'))
        



async def a_main():
    print("This process can take a while. There is a limit with how fast data can be polled from Danbooru.")
    print("Please be patient :)")
    global tags_checked
    global implications_found
    global implications_added
    start = time.time()
    async with aiohttp.ClientSession() as session:
        
        with Database(DPD_SQLITE_LOCATION,TS_SQLITE_LOCATION) as database:
            categories = database.get_categories()
            last_id = 0
            chunk_size = 200
            post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)
            while post_datas is not None and len(post_datas) != 0:
                for post_data in post_datas:
                    await add_tags_to_ts_file(session, database, post_data, categories)
                last_id = post_datas[len(post_datas)-1].post_id
                post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)

    print("Done")
    end = time.time()
    print(f"Runtime: {end - start} seconds")
    print(f"{int((end-start) // 60)} Minutes and {int((end-start) % 60)} Seconds")
    print(f"{tags_checked} tags checked")
    print(f"{implications_found} implications found")
    print(f"{implications_added} implications added")
    time.sleep(3)
        

def main():
    asyncio.run(a_main())

if __name__ == "__main__":
    main()