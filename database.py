import sqlite3
import os
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class PostData:
    post_id: int
    file_name: str
    tags_artist: List[str]
    tags_copyright: List[str]
    tags_character: List[str]
    tags_general: List[str]
    tags_meta: List[str]
    rating: str

class Database:
    def __init__(self, path_to_did_db, path_to_ts_db):
        self.dfd_con = sqlite3.connect(path_to_did_db)
        self.dfd_cur = self.dfd_con.cursor()
        self.ts_con = sqlite3.connect(path_to_ts_db)
        self.ts_cur = self.ts_con.cursor()
        self._prepare_ts_db()

    def _prepare_ts_db(self) -> None:
        sql_add_category_tags_queries = [ 
        """INSERT INTO tags (name, color_namespace, color_slug, is_category)
            SELECT 'Artist', 'tagstudio-neon', 'neon-red-orange', 1
            WHERE NOT EXISTS (
            SELECT 1 FROM tags WHERE name='Artist'
        );""",
        """INSERT INTO tags (name, color_namespace, color_slug, is_category)
            SELECT 'Copyright', 'tagstudio-neon', 'neon-indigo', 1
            WHERE NOT EXISTS (
            SELECT 1 FROM tags WHERE name='Copyright'
        );""",
        """INSERT INTO tags (name, color_namespace, color_slug, is_category)
            SELECT 'Character', 'tagstudio-neon', 'neon-green', 1
            WHERE NOT EXISTS (
            SELECT 1 FROM tags WHERE name='Character'
        );""",
        """INSERT INTO tags (name, color_namespace, color_slug, is_category)
            SELECT 'General', 'tagstudio-neon', 'neon-blue', 1
            WHERE NOT EXISTS (
            SELECT 1 FROM tags WHERE name='General'
        );""",
        """INSERT INTO tags (name, color_namespace, color_slug, is_category)
            SELECT 'Meta', 'tagstudio-neon', 'neon-yellow', 1
            WHERE NOT EXISTS (
            SELECT 1 FROM tags WHERE name='Meta'
        );"""
        ]
        for query in sql_add_category_tags_queries:
            self.ts_cur.execute(query)
        self.ts_con.commit()
        

# TS DATABASE ACCESS

    def get_categories(self) -> dict[str, int]:
        query = """SELECT name, id
                        FROM tags
                        WHERE name IN ('Artist', 'Copyright', 'Character', 'General', 'Meta')"""
        ret = self.ts_cur.execute(query)
        ret_fetch = ret.fetchall()
        return dict(ret_fetch)

    def get_file_id(self, file_name: str) -> int:
        query_data = (file_name,)
        query = """SELECT id
                        FROM entries
                        WHERE filename = ?"""
        
        ret = self.ts_cur.execute(query, query_data)
        id = ret.fetchall()
        if len(id) > 1:
            print(f"Multiple files with the name {file_name} found!")
            return -1
        if len(id) == 0: 
            print(f"Couldn't find file '{file_name}' in the tag studios database")
            return -1
        return id[0][0]


    def get_tag_id(self, tag_name:str)-> int:
        query_data = (tag_name,)
        query = """SELECT id
                        FROM tags
                        WHERE name = ?"""
        ret = self.ts_cur.execute(query, query_data)
        id = ret.fetchone()
        if id is not None:
            return id[0]
        return -1
    
    def does_file_have_tag(self, tag_id:int, entry_id:int) -> bool:
        query_data = (tag_id,entry_id)
        query = """SELECT *
                        FROM tag_entries
                        WHERE tag_id = ? AND entry_id = ?"""
        ret = self.ts_cur.execute(query, query_data)
        id = ret.fetchone()
        if id is not None:
            return True
        return False

    def add_tag_to_file(self, tag_id:int, entry_id:int) -> None:
        query_data = (tag_id, entry_id)
        query = """INSERT INTO tag_entries
                        (tag_id, entry_id)
                        VALUES(?,?)"""
        self.ts_cur.execute(query, query_data)


    def insert_new_tag(self, tag_name, color_namespace, color_slug) -> None:
        query_data = (tag_name, color_namespace, color_slug, False)
        query = """INSERT INTO tags
                        (name, color_namespace, color_slug, is_category)
                        VALUES(?,?,?,?)"""
        self.ts_cur.execute(query, query_data)
       

    def does_parent_exist(self, tag_id:int, parent_id:int) -> bool:
        query_data = (parent_id, tag_id)
        query = """SELECT 1 FROM tag_parents WHERE parent_id = ? AND child_id = ?"""
        ret = self.ts_cur.execute(query, query_data)
        return ret.fetchone() is not None

    def add_parent_to_tag(self, tag_id:int, parent_id:int) -> bool:
        query_data = (parent_id, tag_id)
        query = """INSERT OR IGNORE INTO tag_parents
                        (parent_id, child_id)
                        VALUES(?,?)"""
        self.ts_cur.execute(query, query_data)
        return self.ts_cur.rowcount == 1


# DFD DATABASE ACCESS        

    def get_table_chunk(self, last_id : int, chunk_size : int, is_webp:bool) -> List[PostData]:
        query_data = (last_id, chunk_size)
        query = """SELECT post_id, tag_string_general, tag_string_character, tag_string_copyright, tag_string_meta, tag_string_artist, rating, file_ext
                        FROM posts
                        WHERE post_id > ?
                        ORDER BY post_id ASC
                        LIMIT ?"""
        ret = self.dfd_cur.execute(query, query_data)
        rows = ret.fetchall()
        retVal = []
        for row in rows:
            r_post_id, r_general, r_character, r_copyright, r_meta, r_artist, r_rating, r_file_ext = row
            if str.lower(r_file_ext) == 'zip':
                if is_webp:
                    r_file_ext = 'webp'
            pd = PostData(
                post_id=r_post_id,
                file_name = f"Danbooru_{str(r_post_id)}.{r_file_ext}",
                tags_artist=r_artist.split(),
                tags_copyright=r_copyright.split(),
                tags_character=r_character.split(),
                tags_general=r_general.split(),
                tags_meta=r_meta.split(),
                rating = r_rating
            )
            retVal.append(pd)
        return retVal
     


    def commit(self):
        self.dfd_con.commit()
        self.ts_con.commit()

    def close(self):
        self.dfd_con.close()
        self.ts_con.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc, tb):
        self.close()