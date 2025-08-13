import os
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def compute_article_id(entry: Dict[str, Any]) -> str:
    unique = (
        entry.get('id')
        or entry.get('guid')
        or entry.get('link')
        or (entry.get('title', '') + entry.get('published', ''))
        or ''
    )
    return hashlib.md5(unique.encode('utf-8')).hexdigest()


class Storage:
    """SQLite-backed storage for feeds, articles, settings and caches."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        ensure_dir(os.path.dirname(db_path))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feeds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    sort_column INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY,
                    feed_id INTEGER NOT NULL,
                    json TEXT NOT NULL,
                    published_at TEXT,
                    FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS read_articles (
                    id TEXT PRIMARY KEY
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS group_settings (
                    group_name TEXT PRIMARY KEY,
                    omdb_enabled INTEGER DEFAULT 0,
                    notifications_enabled INTEGER DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS column_widths (
                    feed_url TEXT NOT NULL,
                    col_index INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    PRIMARY KEY(feed_url, col_index)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS movie_cache (
                    title TEXT PRIMARY KEY,
                    json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS icon_cache (
                    domain TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.commit()

    # ---------------------- Migration ----------------------
    def migrate_from_json_if_needed(self, user_dir: str) -> None:
        """Migrate legacy JSON files to SQLite and remove the JSON files upon success."""
        feeds_json = os.path.join(user_dir, 'feeds.json')
        read_articles_json = os.path.join(user_dir, 'read_articles.json')
        group_settings_json = os.path.join(user_dir, 'group_settings.json')
        movie_cache_json = os.path.join(user_dir, 'movie_data_cache.json')

        exists_any = any(os.path.exists(p) for p in [feeds_json, read_articles_json, group_settings_json, movie_cache_json])
        if not exists_any:
            return

        with self._connect() as con:
            cur = con.cursor()
            # Feeds and entries
            if os.path.exists(feeds_json):
                try:
                    with open(feeds_json, 'r') as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        feeds = data.get('feeds', [])
                        col_widths = data.get('column_widths', {})
                    elif isinstance(data, list):
                        feeds = data
                        col_widths = {}
                    else:
                        feeds, col_widths = [], {}

                    url_to_id: Dict[str, int] = {}
                    for feed in feeds:
                        title = feed.get('title') or feed.get('url')
                        url = feed.get('url')
                        sort_column = int(feed.get('sort_column', 1))
                        sort_order = int(feed.get('sort_order', 0))
                        cur.execute(
                            "INSERT OR IGNORE INTO feeds(title, url, sort_column, sort_order) VALUES(?,?,?,?)",
                            (title, url, sort_column, sort_order),
                        )
                        cur.execute("SELECT id FROM feeds WHERE url=?", (url,))
                        feed_id = cur.fetchone()[0]
                        url_to_id[url] = feed_id

                        # Entries
                        for entry in feed.get('entries', []) or []:
                            eid = compute_article_id(entry)
                            # crude published date extraction for index
                            published = entry.get('published') or entry.get('updated') or ''
                            cur.execute(
                                "INSERT OR REPLACE INTO entries(id, feed_id, json, published_at) VALUES(?,?,?,?)",
                                (eid, feed_id, json.dumps(entry), published),
                            )

                    # column widths
                    for feed_url, widths in (col_widths or {}).items():
                        if isinstance(widths, list):
                            for idx, w in enumerate(widths):
                                cur.execute(
                                    "INSERT OR REPLACE INTO column_widths(feed_url, col_index, width) VALUES(?,?,?)",
                                    (feed_url, idx, int(w or 0)),
                                )
                except Exception:
                    # best-effort: do not raise to avoid blocking app start
                    pass

            # Read articles
            if os.path.exists(read_articles_json):
                try:
                    with open(read_articles_json, 'r') as f:
                        read_ids = json.load(f)
                    for aid in read_ids or []:
                        cur.execute("INSERT OR IGNORE INTO read_articles(id) VALUES(?)", (aid,))
                except Exception:
                    pass

            # Group settings
            if os.path.exists(group_settings_json):
                try:
                    with open(group_settings_json, 'r') as f:
                        gs = json.load(f)
                    for name, cfg in (gs or {}).items():
                        cur.execute(
                            "INSERT OR REPLACE INTO group_settings(group_name, omdb_enabled, notifications_enabled) VALUES(?,?,?)",
                            (name, 1 if cfg.get('omdb_enabled') else 0, 1 if cfg.get('notifications_enabled') else 0),
                        )
                except Exception:
                    pass

            # Movie cache
            if os.path.exists(movie_cache_json):
                try:
                    with open(movie_cache_json, 'r') as f:
                        mc = json.load(f)
                    for title, obj in (mc or {}).items():
                        cur.execute(
                            "INSERT OR REPLACE INTO movie_cache(title, json) VALUES(?,?)",
                            (title, json.dumps(obj)),
                        )
                except Exception:
                    pass

            con.commit()

        # Remove JSON files after successful import
        for p in [feeds_json, read_articles_json, group_settings_json, movie_cache_json]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    # ---------------------- Feeds ----------------------
    def get_all_feeds(self) -> List[Dict[str, Any]]:
        with self._connect() as con:
            cur = con.cursor()
            feeds: List[Dict[str, Any]] = []
            for row in cur.execute("SELECT id, title, url, sort_column, sort_order FROM feeds ORDER BY title"):
                feed = {
                    'id': row['id'],
                    'title': row['title'],
                    'url': row['url'],
                    'sort_column': row['sort_column'],
                    'sort_order': row['sort_order'],
                    'entries': self.get_entries_by_feed_id(row['id']),
                }
                feeds.append(feed)
            return feeds

    def upsert_feed(self, title: str, url: str, sort_column: int = 1, sort_order: int = 0) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO feeds(title, url, sort_column, sort_order) VALUES(?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title, sort_column=excluded.sort_column, sort_order=excluded.sort_order",
                (title, url, sort_column, sort_order),
            )
            con.commit()

    def remove_feed(self, url: str) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM feeds WHERE url=?", (url,))
            con.commit()

    def update_feed_url(self, old_url: str, new_url: str) -> None:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT id FROM feeds WHERE url=?", (old_url,))
            row = cur.fetchone()
            if not row:
                return
            feed_id = row['id']
            cur.execute("UPDATE feeds SET url=? WHERE id=?", (new_url, feed_id))
            con.commit()

    # ---------------------- Entries ----------------------
    def get_entries_by_feed_id(self, feed_id: int) -> List[Dict[str, Any]]:
        with self._connect() as con:
            cur = con.cursor()
            entries: List[Dict[str, Any]] = []
            for row in cur.execute("SELECT json FROM entries WHERE feed_id=?", (feed_id,)):
                try:
                    entries.append(json.loads(row['json']))
                except Exception:
                    pass
            return entries

    def save_entries(self, feed_url: str, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            return
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT id FROM feeds WHERE url=?", (feed_url,))
            row = cur.fetchone()
            if not row:
                return
            feed_id = row['id']
            for entry in entries:
                eid = compute_article_id(entry)
                published = entry.get('published') or entry.get('updated') or ''
                cur.execute(
                    "INSERT OR REPLACE INTO entries(id, feed_id, json, published_at) VALUES(?,?,?,?)",
                    (eid, feed_id, json.dumps(entry), published),
                )
            con.commit()

    def replace_entries(self, feed_url: str, entries: List[Dict[str, Any]]) -> None:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT id FROM feeds WHERE url=?", (feed_url,))
            row = cur.fetchone()
            if not row:
                return
            feed_id = row['id']
            cur.execute("DELETE FROM entries WHERE feed_id=?", (feed_id,))
            for entry in entries or []:
                eid = compute_article_id(entry)
                published = entry.get('published') or entry.get('updated') or ''
                cur.execute(
                    "INSERT OR REPLACE INTO entries(id, feed_id, json, published_at) VALUES(?,?,?,?)",
                    (eid, feed_id, json.dumps(entry), published),
                )
            con.commit()

    # ---------------------- Read articles ----------------------
    def load_read_articles(self) -> List[str]:
        with self._connect() as con:
            return [r['id'] for r in con.execute("SELECT id FROM read_articles")]

    def save_read_articles(self, ids: List[str]) -> None:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM read_articles")
            for aid in ids:
                cur.execute("INSERT OR IGNORE INTO read_articles(id) VALUES(?)", (aid,))
            con.commit()

    # ---------------------- Group settings ----------------------
    def load_group_settings(self) -> Dict[str, Dict[str, bool]]:
        with self._connect() as con:
            result: Dict[str, Dict[str, bool]] = {}
            for r in con.execute("SELECT group_name, omdb_enabled, notifications_enabled FROM group_settings"):
                result[r['group_name']] = {
                    'omdb_enabled': bool(r['omdb_enabled']),
                    'notifications_enabled': bool(r['notifications_enabled']),
                }
            return result

    def save_group_settings(self, group_settings: Dict[str, Dict[str, bool]]) -> None:
        with self._connect() as con:
            cur = con.cursor()
            for name, cfg in (group_settings or {}).items():
                cur.execute(
                    "INSERT OR REPLACE INTO group_settings(group_name, omdb_enabled, notifications_enabled) VALUES(?,?,?)",
                    (name, 1 if cfg.get('omdb_enabled') else 0, 1 if cfg.get('notifications_enabled') else 0),
                )
            con.commit()

    # ---------------------- Column widths ----------------------
    def load_column_widths(self) -> Dict[str, List[int]]:
        with self._connect() as con:
            result: Dict[str, List[int]] = {}
            cur = con.cursor()
            for r in cur.execute("SELECT feed_url, col_index, width FROM column_widths"):
                arr = result.setdefault(r['feed_url'], [])
                idx = int(r['col_index'])
                # ensure length
                while len(arr) <= idx:
                    arr.append(0)
                arr[idx] = int(r['width'])
            return result

    def save_column_widths(self, column_widths: Dict[str, List[int]]) -> None:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM column_widths")
            for url, widths in (column_widths or {}).items():
                if not isinstance(widths, list):
                    continue
                for idx, w in enumerate(widths):
                    cur.execute(
                        "INSERT OR REPLACE INTO column_widths(feed_url, col_index, width) VALUES(?,?,?)",
                        (url, idx, int(w or 0)),
                    )
            con.commit()

    # ---------------------- Movie cache ----------------------
    def load_movie_cache(self) -> Dict[str, Any]:
        with self._connect() as con:
            result: Dict[str, Any] = {}
            for r in con.execute("SELECT title, json FROM movie_cache"):
                try:
                    result[r['title']] = json.loads(r['json'])
                except Exception:
                    pass
            return result

    def save_movie_cache(self, movie_cache: Dict[str, Any]) -> None:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM movie_cache")
            for title, obj in (movie_cache or {}).items():
                cur.execute(
                    "INSERT OR REPLACE INTO movie_cache(title, json) VALUES(?,?)",
                    (title, json.dumps(obj)),
                )
            con.commit()

    # ---------------------- Icon cache ----------------------
    def get_icon(self, domain: str) -> Optional[bytes]:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT data FROM icon_cache WHERE domain=?", (domain,))
            row = cur.fetchone()
            return row[0] if row else None

    def save_icon(self, domain: str, data: bytes) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO icon_cache(domain, data, updated_at) VALUES(?,?,?)",
                (domain, data, datetime.utcnow().isoformat()),
            )
            con.commit()
