import types
import pytest

from small_rss_reader import RSSReader
from rss_reader.features.omdb.queue import OmdbQueueManager
from rss_reader.services.omdb import OmdbWorker, FetchOmdbRunnable


@pytest.fixture
def ui_app(qtbot, tmp_path, monkeypatch):
    # Ensure user data path is isolated
    import small_rss_reader as appmod
    monkeypatch.setattr(appmod, 'get_user_data_path', lambda name: str(tmp_path / name))
    # Avoid non-debug auto-refresh
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    # Ensure not headless-minimal: drop PYTEST_CURRENT_TEST env so full UI is built
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def test_extract_title_year_from_noisy_title():
    noisy = (
        "[Обновлено] Фантастические твари: Преступления Грин-де-Вальда / "
        "Fantastic Beasts: The Crimes of Grindelwald (Дэвид Йейтс / David Yates) "
        "[2018, Великобритания, США, фэнтези, приключения, семейный, WEB-DL 2160p] [25.13 GB]"
    )
    title, year = OmdbQueueManager._extract_title_year(noisy)
    assert 'fantastic beasts' in title.lower()
    assert year == 2018


def test_extract_title_year_trims_lang_and_plus_tails():
    samples = [
        "American Hustle (David O. Russell) 2x Dub + 2x MVO + AVO + VO + MVO Ukr + Original Eng + Sub",
        "The Power of Few (David A. Armstrong) MVO + Original Eng + Sub Eng",
        "Stalingrad (Joseph Vilsmaier) VO + Sub + Original Deu",
    ]
    for s in samples:
        title, year = OmdbQueueManager._extract_title_year(s)
        assert "+" not in title
        assert ")" not in title
        assert any(word in title for word in ["Hustle", "Power", "Stalingrad"]) or len(title.split()) >= 1


def test_app_sets_auth_failed_on_401_shows_status(ui_app, qtbot, monkeypatch):
    app = ui_app
    # Provide dummy manager to capture set_auth_failed calls
    calls = {}
    class DummyMgr:
        def set_auth_failed(self, v):
            calls['auth_failed'] = v
        def on_movie_failed(self, _title):
            calls['failed_called'] = True
    app._omdb_mgr = DummyMgr()
    # Provide a status label
    app._omdbStatusLabel = types.SimpleNamespace(text='', setText=lambda s: setattr(app._omdbStatusLabel, 'text', s))
    app._on_movie_failed('X', Exception('401 Client Error: Unauthorized for url'))
    assert calls.get('auth_failed') is True
    assert 'Unauthorized' in app._omdbStatusLabel.text


def test_settings_save_resets_auth_failed(ui_app, qtbot, monkeypatch):
    app = ui_app
    # Prepare dummy mgr to capture reset
    calls = {'auth_failed': None, 'cleared': False}
    class DummyMgr:
        def set_auth_failed(self, v):
            calls['auth_failed'] = v
    app._omdb_mgr = DummyMgr()
    app._clear_omdb_status = lambda: calls.__setitem__('cleared', True)
    # Open settings dialog and save
    from rss_reader.ui.dialogs import SettingsDialog
    dlg = SettingsDialog(app)
    dlg.api_key_input.setText('abc123456789')
    dlg.save_settings()
    assert calls['auth_failed'] is False
    assert calls['cleared'] is True


def test_fetch_runnable_uses_omdbapi(monkeypatch, qtbot):
    captured = {'api_key': None, 'title': None, 'year': None}
    class DummyMovie:
        def __init__(self, api_key):
            captured['api_key'] = api_key
        def get_movie(self, title, year=None):
            captured['title'] = title
            captured['year'] = year
            return {'Title': title, 'Year': str(year or '')}
    monkeypatch.setattr('omdbapi.movie_search.GetMovie', DummyMovie)
    worker = OmdbWorker()
    results = {}
    worker.movie_fetched.connect(lambda t, d: results.setdefault('ok', (t, d)))
    r = FetchOmdbRunnable('Inception', 'KEY123', worker, year=2010)
    r.run()
    assert captured == {'api_key': 'KEY123', 'title': 'Inception', 'year': 2010}
    assert results.get('ok')[0] == 'Inception'
    assert results.get('ok')[1].get('Year') == '2010'


def test_settings_test_key_uses_http_probe(qtbot, ui_app, monkeypatch):
    captured = {'url': None, 'opened': False}
    # Suppress QMessageBox
    import rss_reader.ui.dialogs as dialogs_mod
    monkeypatch.setattr(dialogs_mod.QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setattr(dialogs_mod.QMessageBox, 'warning', lambda *a, **k: None)
    monkeypatch.setattr(dialogs_mod.QMessageBox, 'critical', lambda *a, **k: None)

    class DummyResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    def dummy_urlopen(req, timeout=10):
        captured['opened'] = True
        url = getattr(req, 'full_url', req)
        captured['url'] = url
        return DummyResp(b'{"Response":"True","Title":"Guardians of the Galaxy Vol. 2"}')

    monkeypatch.setattr('urllib.request.urlopen', dummy_urlopen)

    from rss_reader.ui.dialogs import SettingsDialog
    dlg = SettingsDialog(ui_app)
    dlg.api_key_input.setText('VALIDKEY')
    dlg.test_api_key()
    assert captured['opened'] is True
    assert 'i=tt3896198' in captured['url']
    assert 'apikey=VALIDKEY' in captured['url']
