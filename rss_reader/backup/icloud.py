import os
import shutil
from pathlib import Path
from typing import Optional
import subprocess
import sys


def get_backup_folder() -> str:
    return os.path.join(
        Path.home(),
        "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup",
    )


def _same_file(src: str, dst: str) -> bool:
    """Fast check: files are the same if both exist and have identical size and mtime.
    This avoids expensive hashing and is enough to decide whether to recopy the DB.
    """
    try:
        if not (os.path.exists(src) and os.path.exists(dst)):
            return False
        s1 = os.stat(src)
        s2 = os.stat(dst)
        return (s1.st_size == s2.st_size) and (getattr(s1, 'st_mtime_ns', int(s1.st_mtime * 1e9)) == getattr(s2, 'st_mtime_ns', int(s2.st_mtime * 1e9)))
    except Exception:
        return False


def backup_db(db_path: str, dest_path: Optional[str] = None) -> str:
    folder = dest_path or get_backup_folder()
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, 'db.sqlite3')
    if not os.path.exists(db_path):
        return dst

    # Skip copying if nothing changed since the last backup
    if _same_file(db_path, dst):
        return dst

    # For large files on POSIX/macOS, spawn background copy to avoid blocking UI on app exit
    try:
        size = os.path.getsize(db_path)
    except Exception:
        size = 0
    ASYNC_THRESHOLD = 5 * 1024 * 1024  # 5 MiB
    if size >= ASYNC_THRESHOLD and os.name == 'posix':
        try:
            # Use cp -p to preserve times/metadata; detach so app can exit immediately
            subprocess.Popen(
                ['/bin/cp', '-p', db_path, dst],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            return dst
        except Exception:
            # Fallback to synchronous copy below
            pass

    # Perform the copy (preserve metadata). If anything goes wrong, fall back gracefully.
    try:
        shutil.copy2(db_path, dst)
    except Exception:
        try:
            shutil.copy(db_path, dst)
        except Exception:
            # Best-effort: keep behavior non-fatal
            pass
    return dst


def restore_db(dest_db_path: str, src_path: Optional[str] = None) -> bool:
    folder = src_path or get_backup_folder()
    src = os.path.join(folder, 'db.sqlite3')
    if not os.path.exists(src):
        return False
    shutil.copy2(src, dest_db_path)
    return True
