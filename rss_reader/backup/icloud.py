import os
import shutil
from pathlib import Path
from typing import Optional


def get_backup_folder() -> str:
    return os.path.join(
        Path.home(),
        "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup",
    )


def backup_db(db_path: str, dest_path: Optional[str] = None) -> str:
    folder = dest_path or get_backup_folder()
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, 'db.sqlite3')
    if os.path.exists(db_path):
        shutil.copy2(db_path, dst)
    return dst


def restore_db(dest_db_path: str, src_path: Optional[str] = None) -> bool:
    folder = src_path or get_backup_folder()
    src = os.path.join(folder, 'db.sqlite3')
    if not os.path.exists(src):
        return False
    shutil.copy2(src, dest_db_path)
    return True
