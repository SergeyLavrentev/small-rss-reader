import os
import shutil
from pathlib import Path

import pytest

from small_rss_reader import RSSReader
from storage import Storage


@pytest.fixture
def app(qtbot, tmp_path, monkeypatch):
    # Force user data dir into tmp so backup/restore work on isolated files
    def fake_user_data_path(name):
        return str(tmp_path / name)

    import small_rss_reader as appmod
    monkeypatch.setattr(appmod, 'get_user_data_path', fake_user_data_path)

    w = RSSReader()
    w.statusBar = lambda: type('SB', (), {'showMessage': lambda *a, **k: None})()
    return w


def test_backup_and_restore_includes_sqlite_and_json(app, tmp_path, monkeypatch):
    # Prepare sample files to backup
    user_files = ['feeds.json', 'read_articles.json', 'group_settings.json', 'movie_data_cache.json', 'db.sqlite3']
    for name in user_files:
        p = tmp_path / name
        if name.endswith('.json'):
            p.write_text('{}')
        else:
            # Create a tiny sqlite file or marker
            p.write_bytes(b'\x00')

    # iCloud backup path redirected into temp dir
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    icloud_path = (
        Path.home()
        / 'Library'
        / 'Mobile Documents'
        / 'com~apple~CloudDocs'
        / 'SmallRSSReaderBackup'
    )

    app.backup_to_icloud()

    # All files should be present in backup
    for name in user_files:
        assert (icloud_path / name).exists()

    # Remove originals, then restore back
    for name in user_files:
        f = tmp_path / name
        if f.exists():
            f.unlink()

    app.restore_from_icloud()

    for name in user_files:
        assert (tmp_path / name).exists()
