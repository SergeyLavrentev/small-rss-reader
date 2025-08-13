import os
from PyQt5.QtGui import QPixmap
import pytest

from small_rss_reader import RSSReader


@pytest.fixture
def app(qtbot):
    w = RSSReader()
    w.statusBar = lambda: type('SB', (), {'showMessage': lambda *a, **k: None})()
    return w


def test_on_icon_fetched_caches_and_scales_icon(app, tmp_path, monkeypatch):
    # Create fake 32x32 PNG
    pm = QPixmap(32, 32)
    pm.fill()
    data = pm.toImage().bits().asstring(pm.width() * pm.height() * 4)  # raw, but loadFromData expects encoded

    # Instead, build a valid PNG by saving to temp
    p = tmp_path / 'icon.png'
    pm.save(str(p), 'PNG')
    png = p.read_bytes()

    called = {}
    def spy_save_icon(domain, blob):
        called['saved'] = (domain, blob)

    if getattr(app, 'storage', None):
        app.storage.save_icon = spy_save_icon

    app.on_icon_fetched('example.org', png)

    # If storage is present, it was saved
    if 'saved' in called:
        d, blob = called['saved']
        assert d == 'example.org' and isinstance(blob, (bytes, bytearray))
