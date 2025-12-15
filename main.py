
from sys import exit as sys_exit
import os
from typing import List
from database import Database, PostData
from dotenv import load_dotenv
import asyncio
import aiohttp
#from alive_progress import alive_bar
import time
from enum import Enum, auto

class ImplicationsMode(Enum):
    NONE = auto()
    ALL  = auto()

RATE_LIMIT_INTERVAL = 1.0 # make sure to never hit poll limit
request_lock = asyncio.Lock()
load_dotenv()
DPD_SQLITE_LOCATION = os.getenv('DANBOORU_DOWNLOADER_SQLITE_LOCATION') or ''
TS_SQLITE_LOCATION = os.getenv('TAG_STUDIO_SQLITE_LOCATION') or ''

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
request_time = 1.0

total_coroutines = 0


async def get_implications(session:aiohttp.ClientSession, booru_tag_name:str) -> list[dict]:
    global request_time
    global total_coroutines
    async with request_lock:
        await asyncio.sleep(max(0, RATE_LIMIT_INTERVAL - request_time))
        start = time.time()
        total_coroutines += 1
        async with session.get(f'https://danbooru.donmai.us/tag_implications.json?search[name_matches]={booru_tag_name}') as resp:
            resp.raise_for_status()
            request_time = time.time() - start
            return await resp.json()

async def create_parents_from_implications(session:aiohttp.ClientSession, database: Database, booru_tag_name:str, ts_tag_id:int) -> None:
    # This takes ages because there are HUNDREDS of necessary http requests on a limited rate of
    #     1 per second (to make sure we don't deplete burst pool)
    # Potentially finish adding tags first, and then do the implications afterwards to allow user
    #     to use the tags while this finishes in the background
    global tags_checked
    global implications_found
    global implications_added
    tag_implications: list[dict] = await get_implications(session, booru_tag_name)
    tags_checked += 1
    if tags_checked % 25 == 0:
        print(f"Im still running :)    {tags_checked} tags checked so far")

    for tag_implication in tag_implications:
        if tag_implication.get('status') != 'active':
            continue
        implications_found += 1
        is_antecedent_name = True if tag_implication.get('antecedent_name') == booru_tag_name else False
        other_id = database.get_tag_id(str(tag_implication.get('consequent_name') if is_antecedent_name else tag_implication.get('antecedent_name')))
        if other_id == -1:
            continue
        implications_added += 1
        if is_antecedent_name:
            database.add_parent_to_tag(ts_tag_id, other_id)
        else:
            database.add_parent_to_tag(other_id, ts_tag_id)


async def _add_tags_to_ts_file(session:aiohttp.ClientSession, database: Database, tags: List[str], file_name:str, color:dict[str,str], category_id:int | None, mode:ImplicationsMode):
    if category_id is None:
        return
    if not tags:
        return
    entry_id: int = database.get_file_id(file_name)
    if entry_id == -1:
        return
    check_tag_id = database.get_tag_id(tags[0])
    if check_tag_id != -1:
        if database.does_file_have_tag(check_tag_id, entry_id):
            return # If it has the first tag, assume this file has been processed already
    for tag in tags:
        tag_id: int = database.get_tag_id(tag)
        if tag_id == -1:
            database.insert_new_tag(tag, color.get('namespace'), color.get('slug'))
            tag_id = database.get_tag_id(tag)
            if mode is ImplicationsMode.ALL:
                await create_parents_from_implications(session, database, tag, tag_id)
            database.add_parent_to_tag(tag_id, category_id)
        database.add_tag_to_file(tag_id, entry_id)
    database.commit()



async def add_tags_to_ts_file(session:aiohttp.ClientSession, database: Database, file_info:PostData,  categories:dict[str, int], mode:ImplicationsMode) -> None:
    await _add_tags_to_ts_file(session, database, file_info.tags_artist, file_info.file_name, ARTIST_COLOR, categories.get('Artist'), mode)
    await _add_tags_to_ts_file(session, database, file_info.tags_copyright, file_info.file_name, COPYRIGHT_COLOR, categories.get('Copyright'), mode)
    await _add_tags_to_ts_file(session, database, file_info.tags_character, file_info.file_name, CHARACTER_COLOR, categories.get('Character'), mode)
    await _add_tags_to_ts_file(session, database, file_info.tags_general, file_info.file_name, GENERAL_COLOR, categories.get('General'), mode)
    await _add_tags_to_ts_file(session, database, file_info.tags_meta, file_info.file_name, META_COLOR, categories.get('Meta'), mode)
    await _add_tags_to_ts_file(session, database, [f"rating:{file_info.rating}"], file_info.file_name, META_COLOR, categories.get('Meta'), mode)
        



async def a_main(mode:ImplicationsMode):
    if mode is ImplicationsMode.ALL:
        print("This process can take a while. There is a limit with how fast data can be polled from Danbooru.")
        print("Please be patient :)")

    start = time.time()
    async with aiohttp.ClientSession() as session:
        
        with Database(DPD_SQLITE_LOCATION,TS_SQLITE_LOCATION) as database:
            categories = database.get_categories()
            last_id = 0
            chunk_size = 200
            post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)
            while post_datas is not None and len(post_datas) != 0:
                for post_data in post_datas:
                    await add_tags_to_ts_file(session, database, post_data, categories, mode)
                last_id = post_datas[len(post_datas)-1].post_id
                post_datas: List[PostData] = database.get_table_chunk(last_id, chunk_size)

    print("Done")
    end = time.time()
    print(f"Runtime: {end - start} seconds")
    print(f"{int((end-start) // 60)} Minutes and {int((end-start) % 60)} Seconds")
    if mode is ImplicationsMode.ALL:
        print(f"{tags_checked} tags checked")
        print(f"{implications_found} implications found")
        print(f"{implications_added} implications added")
    time.sleep(3)
        

def main(mode:ImplicationsMode):
    asyncio.run(a_main(mode))

if __name__ == "__main__":
    main(ImplicationsMode.ALL)