import pytest

from small_rss_reader import RSSReader


@pytest.fixture
def ui_app(qtbot, monkeypatch):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def test_window_state_save_load_smoke(ui_app, monkeypatch):
    # Just call save and load helpers to ensure no exceptions with UI present
    app = ui_app
    from rss_reader.controllers.view_state import save_window_state, load_window_state
    save_window_state(app)
    load_window_state(app)
