"""Application API for Small RSS Reader (refactored)."""
import os
import sys
import logging
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from urllib.parse import urlparse
import webbrowser

# В тестах глушим шумные логи Qt WebEngine, чтобы не мешали выводу pytest
try:
    if os.environ.get('SMALL_RSS_TESTS') or os.environ.get('PYTEST_CURRENT_TEST'):
        _rules = os.environ.get('QT_LOGGING_RULES', '')
        _supp = 'qt.webengine.*=false;qt.webengineprofile.*=false;qt.webenginecontext.*=false'
        os.environ['QT_LOGGING_RULES'] = (_rules + ';' + _supp) if _rules else _supp
except Exception:
    pass

from PyQt5.QtGui import QIcon, QPixmap, QFont, QCloseEvent, QPainter, QColor
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QAction,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QStyle,
    QTextBrowser,
    QLabel,
)
from PyQt5.QtCore import Qt, QThreadPool, pyqtSignal, pyqtSlot, QTimer, QSize, QEvent, QUrl, QRunnable
import os as _os
if not (_os.environ.get('SMALL_RSS_TESTS') or _os.environ.get('PYTEST_CURRENT_TEST')):
    from PyQt5.QtWebEngineWidgets import QWebEngineView
else:  # pragma: no cover - tests run with QTextBrowser
    QWebEngineView = object  # type: ignore

# В тестовой среде глушим шумное предупреждение QtWebEngine об удалении профиля/страницы
try:
    if _os.environ.get('SMALL_RSS_TESTS') or _os.environ.get('PYTEST_CURRENT_TEST'):
        from PyQt5.QtCore import qInstallMessageHandler
        _prev_qt_handler = None

        def _qt_msg_filter(msg_type, context, message):  # noqa: ANN001
            m = str(message)
            if 'WebEnginePage still not deleted' in m or 'Release of profile requested' in m:
                return
            try:
                if _prev_qt_handler:
                    _prev_qt_handler(msg_type, context, message)
            except Exception:
                pass

        _prev_qt_handler = qInstallMessageHandler(_qt_msg_filter)
except Exception:
    pass
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu

from rss_reader.utils.net import compute_article_id
from rss_reader.utils.domains import _domain_variants
from rss_reader.ui.widgets import FeedsTreeWidget, ArticleTreeWidgetItem, WebEnginePage
from rss_reader.ui.dialogs import AddFeedDialog, SettingsDialog
from rss_reader.ui.actions import create_actions as _ui_create_actions
from rss_reader.ui.menus import create_menu as _ui_create_menu
from rss_reader.ui.tray import init_tray as _ui_init_tray
from rss_reader.ui.toolbar import setup_toolbar as _ui_setup_toolbar, apply_toolbar_styles as _ui_apply_toolbar_styles
from storage import Storage
from rss_reader.io.opml import export_opml as opml_export, import_opml as opml_import
from rss_reader.io.json_io import import_json as json_import, export_json as json_export
from rss_reader.backup.icloud import backup_db as icloud_backup_db, restore_db as icloud_restore_db
from rss_reader.features.omdb.queue import OmdbQueueManager
from rss_reader.controllers.view_state import load_window_state, save_window_state

# Prefer small_rss_reader.get_user_data_path to allow test monkeypatching
try:
    from rss_reader.utils.paths import get_user_data_path as _default_get_user_data_path
except Exception:  # pragma: no cover
    _default_get_user_data_path = lambda name: name  # type: ignore


def get_user_data_path(filename: str) -> str:
    mod = sys.modules.get("small_rss_reader")
    fn = getattr(mod, "get_user_data_path", None) if mod else None
    if callable(fn):
        try:
            return fn(filename)
        except Exception:
            pass
    return _default_get_user_data_path(filename)


class RSSReader(QMainWindow):
    """Lean version sufficient for tests.

    It implements:
    - get_article_id
    - prune_old_entries / get_entry_date
    - update_feed_url
    - backup_to_icloud / restore_from_icloud
    - on_icon_fetched (favicon cache + optional storage save)
    """

    # Signals used by favicon runnable
    icon_fetched = pyqtSignal(str, bytes)
    icon_fetch_failed = pyqtSignal(str)
    # Signals for article page prefetch
    page_fetched = pyqtSignal(str, str, str)  # aid, link, html
    page_fetch_failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        # Minimal state used by tests
        self.max_days = 30
        self.feeds: List[Dict[str, Any]] = []
        self.read_articles = set()
        self.column_widths: Dict[str, List[int]] = {}
        self.group_settings: Dict[str, Dict[str, bool]] = {}
        self.favicon_cache: Dict[str, QIcon] = {}
        self.data_changed = False
        # Optional storage (created only in interactive runs to keep tests lightweight)
        self.storage = None
        self.refresh_interval = 60
        self.default_font = QFont("Arial", 16)
        self.current_font_size = 16
        # try load saved font size
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            fs = settings.value('content_font_size', None)
            if fs is not None:
                self.current_font_size = int(fs)
        except Exception:
            pass
        self.api_key = ""
        self.show_unread_only = False
        self.search_text = ""
        self.movie_cache: Dict[str, Any] = {}
        self.omdb_columns_by_feed: Dict[str, List[str]] = {}
        # OMDb queue manager (lazy wired during UI init)
        self._omdb_mgr: Optional[OmdbQueueManager] = None
        # Track domains with in-flight favicon fetch to avoid duplicates
        self._favicon_fetching = set()
        # Cache for cleaned article HTML by article id
        self.article_html_cache: Dict[str, str] = {}
        self._page_fetching_aids = set()

        # Interactive runs: show a basic UI so the window isn't empty
        try:
            headless = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        except Exception:
            headless = False
        if not headless:
            self._init_full_ui()

    # ---- Full UI for interactive runs ----
    def _init_full_ui(self) -> None:
        self.setWindowTitle("Small RSS Reader")
        # Logging: configure from QSettings (default INFO)
        try:
            from PyQt5.QtCore import QSettings
            level_name = QSettings('rocker', 'SmallRSSReader').value('log_level', 'INFO')
            level = getattr(logging, str(level_name).upper(), logging.INFO)
            log_path = get_user_data_path('rss_reader.log')
            logging.basicConfig(
                level=level,
                format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                handlers=[logging.FileHandler(log_path, encoding='utf-8'), logging.StreamHandler(sys.stdout)],
            )
            logging.getLogger(__name__).debug('Logging initialized, level=%s, file=%s', level_name, log_path)
        except Exception:
            pass

        # Actions and menu
        self._create_actions()
        self._create_menu()
        # Initialize unread-only from settings so action/checkbox start in sync
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            checked = settings.value('show_only_unread', False, type=bool)
            self.show_unread_only = bool(checked)
            try:
                self.actOnlyUnread.setChecked(bool(checked))
            except Exception:
                pass
        except Exception:
            pass

        # Toolbar
        _ui_setup_toolbar(self)
        # Search UX: clear button + ESC to clear
        try:
            self.searchEdit.setClearButtonEnabled(True)
            self.searchEdit.installEventFilter(self)
        except Exception:
            pass
        # Central layout
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal, central)
        layout.addWidget(splitter)
        self._splitter = splitter
        # Автосохранение размеров сплиттера при перемещении
        try:
            splitter.splitterMoved.connect(lambda _pos, _idx: self._save_splitter_sizes())
        except Exception:
            pass
        # Thin handles + resize cursor
        try:
            splitter.setStyleSheet(
                """
                QSplitter::handle { background: rgba(0,0,0,32); }
                QSplitter::handle:hover { background: rgba(66,133,244,140); }
                QSplitter::handle:horizontal { width: 4px; }
                QSplitter::handle:vertical { height: 4px; }
                """
            )
            for i in range(1, splitter.count()):
                try:
                    h = splitter.handle(i)
                    if h:
                        h.setCursor(Qt.SplitHCursor)
                except Exception:
                    pass
        except Exception:
            pass
        # Thin handles + clear resize cursor on hover
        try:
            splitter.setHandleWidth(4)
            splitter.setStyleSheet(
                """
                QSplitter::handle { background: rgba(0,0,0,32); }
                QSplitter::handle:hover { background: rgba(0,0,0,96); }
                """
            )
        except Exception:
            pass

        # Left: feeds tree
        self.feedsTree = FeedsTreeWidget(splitter)
        self.feedsTree.setHeaderHidden(True)
        self.feedsTree.setObjectName("feedsTree")
        try:
            self.feedsTree.setMinimumWidth(180)
        except Exception:
            pass
        self.feedsTree.itemSelectionChanged.connect(self._on_feed_selected)
        self.feedsTree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.feedsTree.customContextMenuRequested.connect(self._on_feeds_context_menu)

        # Center: articles list
        self.articlesTree = QTreeWidget(splitter)
        self.articlesTree.setHeaderLabels(["Title", "Date"])
        self.articlesTree.setObjectName("articlesTree")
        try:
            self.articlesTree.setMinimumWidth(260)
        except Exception:
            pass
        # Keep a consistent left offset in the Title column by reserving icon space
        # regardless of read/unread state (we'll use a transparent placeholder for read)
        try:
            from PyQt5.QtCore import QSize
            self.articlesTree.setIconSize(QSize(12, 12))  # small but noticeable gap from the splitter
        except Exception:
            pass
        # Apply initial font size to the list and header
        try:
            init_font = QFont(self.default_font.family(), int(self.current_font_size))
            self.articlesTree.setFont(init_font)
            self.articlesTree.header().setFont(init_font)
        except Exception:
            pass
        # Enable sorting by clicking on headers
        try:
            self.articlesTree.setSortingEnabled(True)
            hdr = self.articlesTree.header()
            hdr.setSortIndicatorShown(True)
            hdr.setSectionsClickable(True)
        except Exception:
            pass
        self.articlesTree.itemSelectionChanged.connect(self._on_article_selected)
        # Open in browser on activation (double-click or Enter/Return)
        self.articlesTree.itemActivated.connect(lambda _i, _c: self._open_current_article_in_browser())
        self.articlesTree.setRootIsDecorated(False)
        self.articlesTree.setAlternatingRowColors(True)
        self.articlesTree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.articlesTree.customContextMenuRequested.connect(self._on_articles_context_menu)
        self.articlesTree.header().sectionResized.connect(self._on_section_resized)
        # Auto-resize column to contents on header double-click
        try:
            self.articlesTree.header().sectionDoubleClicked.connect(self._on_header_section_double_clicked)
        except Exception:
            pass
    # Меню заголовка отключено: расширенные OMDb колонки в минимальной конфигурации
        try:
            self.articlesTree.header().setContextMenuPolicy(Qt.DefaultContextMenu)
        except Exception:
            pass

        # Right: article content — avoid QWebEngineView under tests to prevent segfaults
        use_light_content = bool(os.environ.get("SMALL_RSS_TESTS"))
        if use_light_content:
            view = QTextBrowser(splitter)
            view.setObjectName("contentView")
            view.setHtml("<html><body><p>Select an article to view its content</p></body></html>")
            try:
                view.setOpenExternalLinks(True)
                # Fallback: ensure anchorClicked opens in system browser
                from PyQt5.QtGui import QDesktopServices
                view.anchorClicked.connect(lambda url: QDesktopServices.openUrl(url))
            except Exception:
                pass
            self.webView = view
        else:
            self.webView = QWebEngineView(splitter)
            self.webView.setObjectName("contentView")
            self.webView.setPage(WebEnginePage(self.webView))
            self.webView.setHtml("<html><body><p>Select an article to view its content</p></body></html>")
        try:
            self.webView.setMinimumWidth(320)
        except Exception:
            pass

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 4)
        # Sensible defaults for first run (overridden by saved sizes below)
        try:
            splitter.setSizes([280, 420, 720])
        except Exception:
            pass
        # Restore splitter sizes if saved
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            sizes = settings.value('splitter_sizes')
            if sizes:
                splitter.setSizes([int(x) for x in list(sizes)])
        except Exception:
            pass
        # Guard against collapsed panels (ensure 3 panes visible)
        # Ensure resize cursor on handles (Qt usually does this by default, but make explicit)
        try:
            for i in range(1, splitter.count()):
                h = splitter.handle(i)
                if h:
                    h.setCursor(Qt.SplitHCursor)
        except Exception:
            pass
        try:
            sizes_now = splitter.sizes()
            if any(int(s or 0) <= 1 for s in sizes_now):
                splitter.setSizes([max(180, sizes_now[0] or 180), max(260, sizes_now[1] or 260), max(320, sizes_now[2] or 320)])
        except Exception:
            pass

        self.setCentralWidget(central)
        # Коалесцированный автосейв геометрии окна
        try:
            from PyQt5.QtCore import QTimer
            self._geom_save_timer = QTimer(self)
            self._geom_save_timer.setSingleShot(True)
            self._geom_save_timer.setInterval(800)
            self._geom_save_timer.timeout.connect(lambda: save_window_state(self))
            # Перехват изменения размера/перемещения окна для триггера таймера
            self.installEventFilter(self)
        except Exception:
            self._geom_save_timer = None  # type: ignore

    # Status bar intentionally disabled per requirement — do not create it
    # self._omdbStatusLabel is not created; related updates are guarded by hasattr checks elsewhere

        # Ensure toolbar visible by default
        try:
            if hasattr(self, 'toolbar') and self.toolbar:
                self.toolbar.setVisible(True)
        except Exception:
            pass

        # Infrastructure
        self.thread_pool = QThreadPool.globalInstance()
        self.icon_fetched.connect(self.on_icon_fetched)
        try:
            self.icon_fetch_failed.connect(self._on_icon_fetch_failed)
        except Exception:
            pass
        # Prefetch page signals
        try:
            self.page_fetched.connect(self._on_page_fetched)
            self.page_fetch_failed.connect(lambda _aid: None)
        except Exception:
            pass
        # OMDb worker signals (created lazily)
        try:
            from rss_reader.services.omdb import OmdbWorker
            self._omdb_worker = OmdbWorker()
            # queue manager wiring
            self._omdb_mgr = OmdbQueueManager(self)
            self._omdb_mgr.set_worker(self._omdb_worker)
            self._omdb_mgr.set_thread_pool(self.thread_pool)
            self._omdb_mgr.set_cache_proxy(self.movie_cache)
            self._omdb_mgr.set_get_api_key(self._get_omdb_api_key)
            # worker -> app
            self._omdb_worker.movie_fetched.connect(self._on_movie_fetched)
            self._omdb_worker.movie_failed.connect(self._on_movie_failed)
        except Exception:
            self._omdb_worker = None  # type: ignore

        # Storage (SQLite)
        db_path = get_user_data_path("db.sqlite3")
        try:
            self.storage = Storage(db_path)
            self.storage.migrate_from_json_if_needed(os.path.dirname(db_path))
        except Exception:
            self.storage = None

        # Load initial state
        self._load_state_from_storage()
        self.update_refresh_timer()
        self._init_tray_icon()
        # Startup UX: focus first feed and open first article; kick off background refresh
        try:
            if self.feedsTree.topLevelItemCount() > 0:
                first_feed = self.feedsTree.topLevelItem(0)
                if first_feed:
                    self.feedsTree.setCurrentItem(first_feed)
                    QTimer.singleShot(0, lambda: self._select_first_article_in_current_feed(open_article=True))
            # Initial background refresh (non-blocking) — skip in debug mode
            import sys as _sys
            if '--debug' not in (_sys.argv or []):
                QTimer.singleShot(0, self.refresh_all_feeds)
        except Exception:
            pass

        # Restore window geometry/state, maximize on first run
        load_window_state(self)
        try:
            from PyQt5.QtCore import QSettings
            s = QSettings('rocker', 'SmallRSSReader')
            if not s.value('window_geometry') and not s.value('window_state'):
                try:
                    self.setWindowState(self.windowState() | Qt.WindowMaximized)
                except Exception:
                    self.showMaximized()
        except Exception:
            pass

    # ---- IDs / dates ----
    def get_article_id(self, entry: Dict[str, Any]) -> str:
        return compute_article_id(entry)
    # ---- Icons helper ----
    def _theme_icon(self, names: List[str], fallback: QStyle.StandardPixmap) -> QIcon:
        try:
            for n in names:
                ic = QIcon.fromTheme(n)
                if ic and not ic.isNull():
                    return ic
        except Exception:
            pass
        try:
            return self.style().standardIcon(fallback)
        except Exception:
            return QIcon()


    def get_entry_date(self, entry: Dict[str, Any]) -> datetime:
        date_struct = entry.get('published_parsed') or entry.get('updated_parsed')
        return datetime(*date_struct[:6]) if date_struct else datetime.min

    # ---- Core updates ----
    def prune_old_entries(self) -> None:
        cutoff_date = datetime.now() - timedelta(days=self.max_days)
        for feed in self.feeds:
            feed['entries'] = [e for e in feed.get('entries', []) if self.get_entry_date(e) >= cutoff_date]

    def update_feed_url(self, feed_item, new_url: str) -> bool:
        if not new_url:
            return False
        if not new_url.startswith(('http://', 'https://')):
            new_url = 'http://' + new_url
        old_url = feed_item.data(0, Qt.UserRole)
        if new_url == old_url:
            return True
        # Duplicate guard (excluding current)
        if any(f['url'] == new_url for f in self.feeds if f.get('url') != old_url):
            pass
            return False
        feed_data = next((f for f in self.feeds if f.get('url') == old_url), None)
        if not feed_data:
            pass
            return False
        # Migrate column widths
        if old_url in self.column_widths:
            self.column_widths[new_url] = self.column_widths.pop(old_url)
        # Update feed data & UI item
        feed_data['url'] = new_url
        feed_item.setData(0, Qt.UserRole, new_url)
        # Optionally refresh icon if item supports it (tests' dummy doesn't)
        if hasattr(feed_item, 'setIcon'):
            try:
                self.set_feed_icon_placeholder(feed_item, new_url)
            except Exception:
                pass
        # Persist change in storage
        if self.storage:
            try:
                self.storage.update_feed_url(old_url, new_url)
            except Exception:
                pass
        self.data_changed = True
        # Rebuild tree in case domain grouping changed; reselect updated feed
        try:
            self._rebuild_feeds_tree()
            # select by new_url
            for it in self._iter_feed_items() or []:
                try:
                    if it.data(0, Qt.UserRole) == new_url:
                        self.feedsTree.setCurrentItem(it)
                        break
                except Exception:
                    pass
        except Exception:
            pass
        return True

    # ---- Backup / Restore ----
    def backup_to_icloud(self) -> None:
        source = get_user_data_path('db.sqlite3')
        try:
            icloud_backup_db(source)
        except Exception:
            pass

    def restore_from_icloud(self) -> None:
        dest = get_user_data_path('db.sqlite3')
        try:
            icloud_restore_db(dest)
        except Exception:
            pass

    # ---- Favicons ----
    def on_icon_fetched(self, domain: str, data: bytes) -> None:
        # Persist if storage is present
        if getattr(self, 'storage', None):
            try:
                self.storage.save_icon(domain, data)
            except Exception:
                pass
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        # Scale to 16x16 and cache icon for domain and variants
        pm = pm.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QIcon(pm)
        for d in _domain_variants(domain):
            self.favicon_cache[d] = icon
        # Update tree icons for matching feeds and groups
        try:
            # Проставить иконку для группы, если её имя совпадает с доменом
            try:
                top_count = self.feedsTree.topLevelItemCount()
            except Exception:
                top_count = 0
            for i in range(top_count):
                top = self.feedsTree.topLevelItem(i)
                if not top:
                    continue
                if not (top.data(0, Qt.UserRole) or None):
                    name = top.text(0)
                    if name in _domain_variants(domain):
                        top.setIcon(0, icon)
            for item in self._iter_feed_items():
                url = item.data(0, Qt.UserRole) or ""
                if not url:
                    continue
                try:
                    feed_domain = urlparse(url).netloc or url
                    if feed_domain in _domain_variants(domain):
                        # store base icon (оставляем для бейджа), не показываем favicon напрямую
                        item.setData(0, Qt.UserRole + 1, icon)
                        self._apply_feed_unread_badge(item)
                except Exception:
                    pass
        except Exception:
            pass
        # Clear in-flight guard
        try:
            self._favicon_fetching.discard(domain)
        except Exception:
            pass

    # Helper for optional UI refresh in update_feed_url
    def set_feed_icon_placeholder(self, item, url: str) -> None:
        try:
            domain = urlparse(url).netloc or url
            icon = self.favicon_cache.get(domain, QIcon())
            # store base and apply badge
            item.setData(0, Qt.UserRole + 1, icon)
            self._apply_feed_unread_badge(item)
        except Exception:
            pass

    # ----------------- UI and actions -----------------
    def _create_actions(self) -> None:
        # delegate to UI helper
        _ui_create_actions(self)

    # ----------------- Storage & state -----------------
    def _load_state_from_storage(self) -> None:
        self.feeds.clear()
        self.feedsTree.clear()
        if not self.storage:
            return
        try:
            self.feeds = self.storage.get_all_feeds()
            self.read_articles = set(self.storage.load_read_articles())
            self.column_widths = self.storage.load_column_widths()
            # optional
            try:
                self.group_settings = self.storage.load_group_settings()
            except Exception:
                self.group_settings = {}
            try:
                self.movie_cache = self.storage.load_movie_cache()
            except Exception:
                pass
        except Exception:
            pass
        # Build the feeds tree with domain grouping
        self._rebuild_feeds_tree()
        self._update_tray()
        self._update_feed_unread_badges()

    # helper to add item into feeds tree and set icon from cache/storage
    def _add_feed_item(self, title: str, url: str, parent: Optional[QTreeWidgetItem] = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, url)
        domain = urlparse(url).netloc or url
        # icon from cache or storage
        icon = self.favicon_cache.get(domain)
        if not icon and self.storage:
            try:
                data = self.storage.get_icon(domain)
                if data:
                    self.on_icon_fetched(domain, data)
                    icon = self.favicon_cache.get(domain)
            except Exception:
                pass
        if icon:
            # store base icon for badge overlay
            item.setData(0, Qt.UserRole + 1, icon)
            # показываем favicon только у одиночных фидов (верхний уровень)
            if parent is None:
                item.setIcon(0, icon)
        if parent is not None:
            parent.addChild(item)
        else:
            self.feedsTree.addTopLevelItem(item)
        return item

    def _iter_feed_items(self):
        """Yield all feed leaf items regardless of grouping."""
        try:
            top_count = self.feedsTree.topLevelItemCount()
        except Exception:
            return
        for i in range(top_count):
            top = self.feedsTree.topLevelItem(i)
            if top is None:
                continue
            url = top.data(0, Qt.UserRole)
            if url:
                yield top
            else:
                for j in range(top.childCount()):
                    ch = top.child(j)
                    if ch and ch.data(0, Qt.UserRole):
                        yield ch

    def _rebuild_feeds_tree(self) -> None:
        """Rebuild the feeds tree with automatic grouping by domain
        (only when multiple feeds share a domain)."""
        try:
            # Preserve current selection
            cur_url = None
            try:
                cur_item = self.feedsTree.currentItem()
                if cur_item:
                    cur_url = cur_item.data(0, Qt.UserRole)
            except Exception:
                pass

            self.feedsTree.clear()
            # Build mapping: domain -> list of feeds
            domain_map: Dict[str, List[Dict[str, Any]]] = {}
            for f in self.feeds:
                u = f.get('url') or ''
                d = urlparse(u).netloc or u
                domain_map.setdefault(d, []).append(f)

            # Create items: group only when domain has >1 feeds
            url_to_item: Dict[str, QTreeWidgetItem] = {}
            for domain, flist in domain_map.items():
                if len(flist) > 1:
                    group_item = QTreeWidgetItem([domain])
                    group_item.setFirstColumnSpanned(False)
                    # иконка группы по домену (если есть)
                    try:
                        gicon = self.favicon_cache.get(domain)
                        if gicon:
                            group_item.setIcon(0, gicon)
                    except Exception:
                        pass
                    self.feedsTree.addTopLevelItem(group_item)
                    # раскрывать группу по умолчанию
                    try:
                        group_item.setExpanded(True)
                    except Exception:
                        pass
                    for f in flist:
                        it = self._add_feed_item(f.get('title') or f.get('url'), f.get('url'), parent=group_item)
                        url_to_item[f.get('url')] = it
                else:
                    f = flist[0]
                    it = self._add_feed_item(f.get('title') or f.get('url'), f.get('url'))
                    url_to_item[f.get('url')] = it

            # Restore selection if possible
            if cur_url and cur_url in url_to_item:
                self.feedsTree.setCurrentItem(url_to_item[cur_url])
        except Exception:
            pass

    # ----------------- Feed operations -----------------
    def add_feed(self) -> None:
        dlg = AddFeedDialog(self)
        if dlg.exec_() == dlg.Accepted:
            name, url = dlg.get_inputs()
            if not url:
                return
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            if any(f['url'] == url for f in self.feeds):
                self.warn("Duplicate", "This feed is already added")
                return
            title = name or url
            # storage
            if self.storage:
                try:
                    self.storage.upsert_feed(title, url)
                except Exception:
                    pass
            feed = {'title': title, 'url': url, 'entries': []}
            self.feeds.append(feed)
            # Rebuild to place the new feed in its domain group if needed
            self._rebuild_feeds_tree()
            # Try to locate the new item
            item = None
            try:
                for it in self._iter_feed_items():
                    if it.data(0, Qt.UserRole) == url:
                        item = it
                        break
            except Exception:
                pass
            pass
            self.refresh_feed(url)
            if item:
                self.feedsTree.setCurrentItem(item)

    def remove_selected_feed(self) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        if QMessageBox.question(self, "Remove Feed", f"Remove {url}?") != QMessageBox.Yes:
            return
        # remove from storage and memory
        if self.storage:
            try:
                self.storage.remove_feed(url)
            except Exception:
                pass

    # Context menu for feeds tree
    def _on_feeds_context_menu(self, pos) -> None:
        item = self.feedsTree.itemAt(pos)
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        # Group node menu
        if not url:
            domain = item.text(0) or ""
            if not domain:
                return
            menu = QMenu(self)
            actOmdbDomain = menu.addAction(f"Enable OMDb for this group ({domain})")
            actOmdbDomain.setCheckable(True)
            try:
                curd = (self.group_settings or {}).get(domain, {})
                actOmdbDomain.setChecked(bool(curd.get('omdb_enabled')))
            except Exception:
                pass
            chosen = menu.exec_(self.feedsTree.viewport().mapToGlobal(pos))
            if chosen == actOmdbDomain:
                try:
                    gs = dict(self.group_settings or {})
                    dcfg = dict(gs.get(domain) or {})
                    enabled = bool(actOmdbDomain.isChecked())
                    dcfg['omdb_enabled'] = enabled
                    gs[domain] = dcfg
                    # mirror to each child feed URL
                    for i in range(item.childCount()):
                        ch = item.child(i)
                        f_url = ch.data(0, Qt.UserRole)
                        if not f_url:
                            continue
                        fcfg = dict(gs.get(f_url) or {})
                        fcfg['omdb_enabled'] = enabled
                        gs[f_url] = fcfg
                        if not enabled:
                            try:
                                self.omdb_columns_by_feed.pop(f_url, None)
                            except Exception:
                                pass
                    self.group_settings = gs
                    if self.storage:
                        try:
                            self.storage.save_group_settings(self.group_settings)
                        except Exception:
                            pass
                    # Refresh all child feeds' article views
                    for i in range(item.childCount()):
                        ch = item.child(i)
                        f_url = ch.data(0, Qt.UserRole)
                        if not f_url:
                            continue
                        fd = next((f for f in self.feeds if f.get('url') == f_url), None)
                        ents = fd.get('entries', []) if fd else []
                        self._populate_articles(f_url, ents)
                        self._maybe_fetch_omdb_for_entries(f_url, ents)
                except Exception:
                    pass
            return

        # Feed node menu
        menu = QMenu(self)
        actRename = menu.addAction("Rename")
        actEditUrl = menu.addAction("Edit URL")
        actRefresh = menu.addAction("Refresh")
        actOmdb = menu.addAction("Enable OMDb (per feed)")
        actOmdb.setCheckable(True)
        try:
            cur = (self.group_settings or {}).get(url, {})
            actOmdb.setChecked(bool(cur.get('omdb_enabled')))
        except Exception:
            pass
        actRemove = menu.addAction("Remove")
        action = menu.exec_(self.feedsTree.viewport().mapToGlobal(pos))
        if action == actRename:
            self.rename_feed(item)
        elif action == actEditUrl:
            old_url = url
            new_url, ok = QInputDialog.getText(self, "Edit URL", "New URL:", text=old_url)
            if ok and new_url:
                self.update_feed_url(item, new_url.strip())
        elif action == actRefresh:
            self.refresh_feed(url)
        elif action == actOmdb:
            try:
                gs = dict(self.group_settings or {})
                cfg = dict(gs.get(url) or {})
                cfg['omdb_enabled'] = bool(actOmdb.isChecked())
                gs[url] = cfg
                self.group_settings = gs
                if self.storage:
                    try:
                        self.storage.save_group_settings(self.group_settings)
                    except Exception:
                        pass
                # Clear any cached columns when disabling per-feed
                if not cfg.get('omdb_enabled'):
                    try:
                        self.omdb_columns_by_feed.pop(url, None)
                    except Exception:
                        pass
                feed = next((f for f in self.feeds if f.get('url') == url), None)
                entries = feed.get('entries', []) if feed else []
                self._populate_articles(url, entries)
                self._maybe_fetch_omdb_for_entries(url, entries)
            except Exception:
                pass
        elif action == actRemove:
            prev = self.feedsTree.currentItem()
            try:
                self.feedsTree.setCurrentItem(item)
                self.remove_selected_feed()
            finally:
                if prev and prev != item:
                    self.feedsTree.setCurrentItem(prev)

    def rename_feed(self, item: QTreeWidgetItem) -> None:
        old_title = item.text(0)
        url = item.data(0, Qt.UserRole) or ""
        new_title, ok = QInputDialog.getText(self, "Rename Feed", "New title:", text=old_title)
        if not ok or not new_title:
            return
        item.setText(0, new_title)
        # Update in-memory model
        for f in self.feeds:
            if f.get('url') == url:
                f['title'] = new_title
                break
        # Persist title change
        if self.storage:
            try:
                self.storage.upsert_feed(new_title, url)
            except Exception:
                pass

    def refresh_selected_feed(self) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        self.refresh_feed(url)

    def refresh_all_feeds(self) -> None:
        for feed in self.feeds:
            self.refresh_feed(feed.get('url'))

    def refresh_feed(self, url: str) -> None:
        try:
            from rss_reader.services.feeds import Worker, FetchFeedRunnable
            worker = Worker()
            worker.feed_fetched.connect(self._on_feed_fetched)
            runnable = FetchFeedRunnable(url, worker)
            self.thread_pool.start(runnable)
            pass
        except Exception:
            pass

    @pyqtSlot(str, object)
    def _on_feed_fetched(self, url: str, feed_obj: Any) -> None:
        if not feed_obj:
            pass
            return
        # normalize entries
        entries = list(feed_obj.entries or [])
        # save to storage
        if self.storage:
            try:
                if any(f['url'] == url for f in self.feeds):
                    self.storage.replace_entries(url, entries)
            except Exception:
                pass
        # update in-memory and UI if this feed selected
        for f in self.feeds:
            if f.get('url') == url:
                f['entries'] = entries
                break
        current = self.feedsTree.currentItem()
        if current and current.data(0, Qt.UserRole) == url:
            self._populate_articles(url, entries)
            # trigger OMDb fetch for visible entries (if enabled)
            self._maybe_fetch_omdb_for_entries(url, entries)
        self._update_tray()
        self._update_feed_unread_badges()

    # ----------------- UI handlers -----------------
    def _on_feed_selected(self) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        # If group node selected, move selection to first child feed
        if not url and item.childCount() > 0:
            ch = item.child(0)
            if ch:
                self.feedsTree.setCurrentItem(ch)
                return
        feed = next((f for f in self.feeds if f.get('url') == url), None)
        entries = feed.get('entries', []) if feed else []
        if not entries and self.storage:
            # lazy load from storage
            try:
                # storage.get_all_feeds already loads entries, but just in case
                pass
            except Exception:
                pass
        self._populate_articles(url, entries)
        # trigger OMDb fetch for visible entries (if enabled)
        self._maybe_fetch_omdb_for_entries(url, entries)
        # favicon fetch on selection if not present
        self._ensure_favicon_for_url(url)

    def _populate_articles(self, feed_url: str, entries: List[Dict[str, Any]]) -> None:
        self.articlesTree.clear()
        visible_entries = list(entries or [])
        # unread filter
        if self.show_unread_only:
            visible_entries = [e for e in visible_entries if self.get_article_id(e) not in self.read_articles]
        # search filter
        try:
            q = (self.search_text or "").strip().lower()
            if q:
                def _matches(e: Dict[str, Any]) -> bool:
                    title = (e.get('title') or '').lower()
                    summary = (e.get('summary') or '').lower()
                    link = (e.get('link') or '').lower()
                    return q in title or q in summary or q in link
                visible_entries = [e for e in visible_entries if _matches(e)]
        except Exception:
            pass

    # Columns based on OMDb flag (для OMDb показываем расширенный набор колонок, теперь с колонкой IMDb)
        omdb_enabled = self._is_omdb_enabled(feed_url)
        if omdb_enabled:
            cols = [
                "Title",
                "Date",
                "Year",
                "IMDb",
                "Director",
                "Actors",
                "Genre",
                "Runtime",
                "Rated",
            ]
        else:
            cols = ["Title", "Date"]
        # explicitly set column count then labels to ensure shrink
        try:
            self.articlesTree.setColumnCount(len(cols))
        except Exception:
            pass
        self.articlesTree.setHeaderLabels(cols)

        # index of Date column for sorting and role storage
        try:
            date_col_index = cols.index("Date")
        except ValueError:
            date_col_index = 0

        for e in visible_entries:
            title = e.get('title') or e.get('link') or 'Untitled'
            dt = self.get_entry_date(e)
            date_str = dt.strftime('%d.%m.%Y') if dt != datetime.min else ''
            # OMDb-derived fields (only if enabled)
            year = ''
            imdb = ''
            director = ''
            actors = ''
            genre = ''
            runtime = ''
            rated = ''
            rec = {}
            if omdb_enabled and self.movie_cache:
                try:
                    # Prefer raw-title key; fallback to normalized to support older cache layouts
                    from rss_reader.features.omdb.queue import OmdbQueueManager as _QM
                    norm_key = _QM._norm_title(title)
                    rec = self.movie_cache.get(title) or self.movie_cache.get(norm_key) or {}
                    year = rec.get('Year') or rec.get('year') or ''
                    imdb = rec.get('imdbRating') or rec.get('imdbrating') or ''
                    director = rec.get('Director') or rec.get('director') or ''
                    actors = rec.get('Actors') or rec.get('actors') or ''
                    genre = rec.get('Genre') or rec.get('genre') or ''
                    runtime = rec.get('Runtime') or rec.get('runtime') or ''
                    rated = rec.get('Rated') or rec.get('rated') or ''
                except Exception:
                    pass
            row: List[str] = []
            for c in cols:
                if c == "Title":
                    row.append(title)
                elif c == "Date":
                    row.append(date_str)
                elif c == "Year":
                    row.append(str(year))
                elif c == "IMDb":
                    row.append(str(imdb))
                elif c == "Director":
                    row.append(director)
                elif c == "Actors":
                    row.append(actors)
                elif c == "Genre":
                    row.append(genre)
                elif c == "Runtime":
                    row.append(runtime)
                elif c == "Rated":
                    row.append(rated)
                else:
                    row.append('')
            item = ArticleTreeWidgetItem(row)
            # store entry on first column role
            item.setData(0, Qt.UserRole, e)
            # store dt on Date column role for potential sorting helpers
            try:
                item.setData(date_col_index, Qt.UserRole, dt)
            except Exception:
                pass
            # store numeric roles for Year to improve sorting
            try:
                hdr_cols = cols
                if "Year" in hdr_cols:
                    idxy = hdr_cols.index("Year")
                    try:
                        yv = int(str(year)) if str(year).isdigit() else None
                    except Exception:
                        yv = None
                    if yv is not None:
                        item.setData(idxy, Qt.UserRole, yv)
                # store numeric role for IMDb (float) to improve sorting
                if "IMDb" in hdr_cols:
                    idxi = hdr_cols.index("IMDb")
                    try:
                        s = str(imdb)
                        s_num = s.split('/', 1)[0]
                        rv = float(s_num) if s_num.replace('.', '', 1).isdigit() else None
                    except Exception:
                        rv = None
                    if rv is not None:
                        item.setData(idxi, Qt.UserRole, rv)
            except Exception:
                pass
            # mark read visually
            aid = self.get_article_id(e)
            if aid in self.read_articles:
                try:
                    # Use transparent placeholder so text doesn't jump when dot disappears
                    item.setIcon(0, QIcon(self._unread_dot_pixmap(8, QColor(0, 0, 0, 0))))
                except Exception:
                    pass
            else:
                # unread -> blue dot icon at column 0
                try:
                    item.setIcon(0, QIcon(self._unread_dot_pixmap(8)))
                except Exception:
                    pass
            self.articlesTree.addTopLevelItem(item)

        # Prefetch pages for items without inline content (skip in tests)
        try:
            headless_tests = bool(os.environ.get('SMALL_RSS_TESTS') or os.environ.get('PYTEST_CURRENT_TEST'))
        except Exception:
            headless_tests = False
        if not headless_tests:
            for e in visible_entries:
                try:
                    aid = self.get_article_id(e)
                    if aid in self.article_html_cache or aid in self._page_fetching_aids:
                        continue
                    link = (e.get('link') or '').strip()
                    has_inline = bool(e.get('content') or e.get('summary') or e.get('description'))
                    if link and not has_inline:
                        self._page_fetching_aids.add(aid)
                        self.thread_pool.start(_PageFetchRunnable(aid, link, self))
                except Exception:
                    pass

        # Sort by Date if present
        try:
            sort_idx = cols.index("Date") if "Date" in cols else max(0, len(cols) - 1)
            self.articlesTree.sortItems(sort_idx, Qt.DescendingOrder)
        except Exception:
            pass

        # apply column widths (with first-run defaults)
        widths = self.column_widths.get(feed_url)
        # Если в хранилище пусто — попробуем поднять из QSettings для переживания переустановки
        if not widths:
            try:
                from PyQt5.QtCore import QSettings
                v = QSettings('rocker', 'SmallRSSReader').value(f'column_widths:{feed_url}')
                if v:
                    widths = [int(x) for x in list(v)]
                    self.column_widths[feed_url] = widths
            except Exception:
                pass
        if widths:
            for i, w in enumerate(widths):
                if w:
                    self.articlesTree.setColumnWidth(i, int(w))
        else:
            # First run: set defaults and remember
            try:
                if omdb_enabled:
                    # Title, Date, Year, IMDb, Director, Actors, Genre, Runtime, Rated
                    defaults = [520, 140, 70, 60, 180, 240, 180, 100, 80]
                else:
                    defaults = [540, 140]      # Title, Date
                for i, w in enumerate(defaults[: self.articlesTree.columnCount()]):
                    self.articlesTree.setColumnWidth(i, int(w))
                self.column_widths[feed_url] = [
                    self.articlesTree.columnWidth(i) for i in range(self.articlesTree.columnCount())
                ]
                # Сохраним дефолты ещё и в QSettings, чтобы переживали переустановку
                try:
                    from PyQt5.QtCore import QSettings
                    QSettings('rocker', 'SmallRSSReader').setValue(f'column_widths:{feed_url}', self.column_widths[feed_url])
                except Exception:
                    pass
                if self.storage:
                    try:
                        self.storage.save_column_widths(self.column_widths)
                    except Exception:
                        pass
            except Exception:
                pass

        # After listing, try to fetch OMDb data for missing items (async)
        try:
            self._maybe_fetch_omdb_for_entries(feed_url, visible_entries)
        except Exception:
            pass

    def _is_omdb_enabled(self, feed_url: str) -> bool:
        try:
            # Prefer explicit per-feed setting; fall back to domain-level
            cfg = (self.group_settings or {}).get(feed_url)
            if cfg is not None and 'omdb_enabled' in cfg:
                return bool(cfg.get('omdb_enabled'))
            domain = urlparse(feed_url).netloc or feed_url
            dcfg = (self.group_settings or {}).get(domain)
            if dcfg is not None and 'omdb_enabled' in dcfg:
                return bool(dcfg.get('omdb_enabled'))
            return False
        except Exception:
            return False

    def _on_articles_header_menu(self, pos) -> None:
        # Меню отключено — расширенные колонки OMDb не используются
        return

    def _apply_toolbar_styles(self) -> None:
        # delegate to UI helper
        _ui_apply_toolbar_styles(self)

    def _add_toolbar_spacer(self, width: int = 8, expand: bool = False) -> None:
        # Kept for backward-compat; now handled by ui.toolbar
        try:
            _ = width or expand
        except Exception:
            pass

    # ----------------- Helpers -----------------
    def _select_first_article_in_current_feed(self, open_article: bool = False) -> None:
        try:
            if self.articlesTree.topLevelItemCount() == 0:
                # ensure articles are populated for the current feed
                cur = self.feedsTree.currentItem()
                if cur:
                    url = cur.data(0, Qt.UserRole)
                    feed = next((f for f in self.feeds if f.get('url') == url), None)
                    entries = feed.get('entries', []) if feed else []
                    if entries:
                        self._populate_articles(url, entries)
            if self.articlesTree.topLevelItemCount() > 0:
                first = self.articlesTree.topLevelItem(0)
                self.articlesTree.setCurrentItem(first)
                if open_article:
                    entry = first.data(0, Qt.UserRole)
                    if entry:
                        self._show_article(entry)
        except Exception:
            pass

    # ----------------- OMDb background fetching -----------------
    def _get_omdb_api_key(self) -> str:
        # Read OMDb key directly from QSettings (no Keychain)
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            return settings.value('omdb_api_key', '', type=str) or ''
        except Exception:
            return ''

    def _maybe_fetch_omdb_for_entries(self, feed_url: str, entries: List[Dict[str, Any]]) -> None:
        if not self._is_omdb_enabled(feed_url) or not self._omdb_mgr:
            return
        try:
            # allow processing unless previously marked as auth failed
            self._omdb_mgr.set_cache_proxy(self.movie_cache)
            # In минимальной конфигурации OMDb-колонки всегда видимы — не гейтить запросы
            self._omdb_mgr.set_columns_visible(True)
            self._omdb_mgr.request_for_entries(entries or [])
        except Exception:
            pass

    def _on_movie_fetched(self, title: str, data: Dict[str, Any]) -> None:
        try:
            logging.getLogger(__name__).debug('OMDb fetched: %s -> keys=%s', title, list((data or {}).keys()))
            if self._omdb_mgr:
                self._omdb_mgr.on_movie_fetched(title)
            from rss_reader.features.omdb.queue import OmdbQueueManager as _QM
            norm = _QM._norm_title(title)
            # Store under both raw and normalized keys for better cache hits
            self.movie_cache[title] = data or {}
            self.movie_cache[norm] = data or {}
            if self.storage:
                try:
                    self.storage.save_movie_cache(self.movie_cache)
                except Exception:
                    pass
            # Update currently visible rows if any match
            try:
                count = self.articlesTree.topLevelItemCount()
                for i in range(count):
                    it = self.articlesTree.topLevelItem(i)
                    e = it.data(0, Qt.UserRole) or {}
                    row_title = (e.get('title') or e.get('link') or '').strip()
                    if _QM._norm_title(row_title) == norm:
                        cols = [self.articlesTree.headerItem().text(c) for c in range(self.articlesTree.columnCount())]
                        # Year
                        if "Year" in cols:
                            yr = data.get('Year') or data.get('year') or ''
                            idxy = cols.index("Year")
                            it.setText(idxy, str(yr))
                            try:
                                yv = int(str(yr)) if str(yr).isdigit() else None
                                if yv is not None:
                                    it.setData(idxy, Qt.UserRole, yv)
                            except Exception:
                                pass
                        # Director
                        if "Director" in cols:
                            it.setText(cols.index("Director"), data.get('Director') or data.get('director') or '')
                        # IMDb
                        if "IMDb" in cols:
                            val = data.get('imdbRating') or data.get('imdbrating') or ''
                            idxi = cols.index("IMDb")
                            it.setText(idxi, str(val))
                            try:
                                s = str(val)
                                s_num = s.split('/', 1)[0]
                                rv = float(s_num) if s_num.replace('.', '', 1).isdigit() else None
                                if rv is not None:
                                    it.setData(idxi, Qt.UserRole, rv)
                            except Exception:
                                pass
                        # Actors
                        if "Actors" in cols:
                            it.setText(cols.index("Actors"), data.get('Actors') or data.get('actors') or '')
                        # Genre
                        if "Genre" in cols:
                            it.setText(cols.index("Genre"), data.get('Genre') or data.get('genre') or '')
                        # Runtime
                        if "Runtime" in cols:
                            it.setText(cols.index("Runtime"), data.get('Runtime') or data.get('runtime') or '')
                        # Rated
                        if "Rated" in cols:
                            it.setText(cols.index("Rated"), data.get('Rated') or data.get('rated') or '')
            except Exception:
                pass
        except Exception:
            pass

    def _on_movie_failed(self, title: str, _err: Exception) -> None:
        try:
            logging.getLogger(__name__).warning('OMDb failed: %s -> %s', title, _err)
            if self._omdb_mgr:
                # If it's auth error (401), pause queue until key is updated
                try:
                    msg = str(_err)
                    if '401' in msg or 'Unauthorized' in msg:
                        self._omdb_mgr.set_auth_failed(True)
                        # Status bar UI is disabled, but tests can stub a label;
                        # update it if present for observability.
                        try:
                            if hasattr(self, '_omdbStatusLabel') and hasattr(self._omdbStatusLabel, 'setText'):
                                self._omdbStatusLabel.setText(f"OMDb: {msg}")
                        except Exception:
                            pass
                except Exception:
                    pass
                self._omdb_mgr.on_movie_failed(title)
        except Exception:
            pass

    def _clear_omdb_status(self) -> None:
        # Status bar disabled: nothing to clear
        pass

    def _on_article_selected(self) -> None:
        item = self.articlesTree.currentItem()
        if not item:
            return
        entry = item.data(0, Qt.UserRole)
        if not entry:
            return
        self._show_article(entry)
        self._update_tray()

    def _show_article(self, entry: Dict[str, Any]) -> None:
        # mark as read
        aid = self.get_article_id(entry)
        if aid not in self.read_articles:
            self.read_articles.add(aid)
            if self.storage:
                try:
                    self.storage.save_read_articles(list(self.read_articles))
                except Exception:
                    pass
            # update current item visuals and feed badge
            try:
                item = self.articlesTree.currentItem()
                if item:
                    # Keep left offset by using transparent placeholder instead of removing icon
                    item.setIcon(0, QIcon(self._unread_dot_pixmap(8, QColor(0, 0, 0, 0))))
                self._update_feed_unread_badges()
            except Exception:
                pass
        # Build robust HTML (with base href and fallbacks) and show
        # 1) Try inline HTML content
        try:
            html, base_url = self._build_article_html(entry)
        except Exception:
            html, base_url = ("<html><body><p>No content</p></body></html>", "")

        # Heuristic: decide if we actually have real inline content
        link = (entry.get('link') or '').strip()
        def _has_real_content(h: str) -> bool:
            s = (h or '').lower()
            # more than just the header and footer around an empty body
            return any(tag in s for tag in ('<p', '<div', '<img', '<ul', '<ol', '<table', '<article')) and len(s) > 40

        showed_inline = False
        try:
            if hasattr(self.webView, 'setHtml') and _has_real_content(html):
                if base_url:
                    self.webView.setHtml(html, QUrl(base_url))
                else:
                    self.webView.setHtml(html)
                showed_inline = True
        except Exception:
            # QTextBrowser uses setHtml too; this is just in case
            try:
                self.webView.setText(html)
                showed_inline = True
            except Exception:
                pass

        # 2) Fallback: if no inline content and we have a link, load full page
        try:
            headless_tests = bool(os.environ.get('SMALL_RSS_TESTS') or os.environ.get('PYTEST_CURRENT_TEST'))
        except Exception:
            headless_tests = False
        if not showed_inline and link:
            try:
                # If it's a QWebEngineView, load the URL directly
                if isinstance(self.webView, QWebEngineView):
                    self.webView.load(QUrl(link))
                    showed_inline = True
                # If it's a QTextBrowser (tests or light mode), try to fetch HTML
                elif not headless_tests:
                    try:
                        import requests  # lazy import
                        resp = requests.get(link, timeout=8, headers={
                            'User-Agent': 'SmallRSSReader/1.0 (+https://github.com/SergeyLavrentev)'
                        })
                        txt = resp.text if hasattr(resp, 'text') else ''
                        if txt:
                            try:
                                self.webView.setHtml(txt, QUrl(link))
                            except Exception:
                                self.webView.setHtml(txt)
                            showed_inline = True
                    except Exception:
                        showed_inline = False
            except Exception:
                pass

        # 3) As a last resort, show minimal link card
        if not showed_inline:
            try:
                title = entry.get('title') or link or ''
                minimal = f"<html><body style=\"font-family:{self.default_font.family()};font-size:{int(self.current_font_size)}px\"><h3>{title}</h3>"
                if link:
                    minimal += f"<p><a href='{link}' target='_blank'>{link}</a></p>"
                else:
                    minimal += "<p>No content</p>"
                minimal += "</body></html>"
                self.webView.setHtml(minimal, QUrl(link) if link else QUrl())
            except Exception:
                pass
        # notifications (optional)
        self._notify_new_read()

    def _open_current_article_in_browser(self) -> None:
        """Open the currently selected article's link in the system browser."""
        item = self.articlesTree.currentItem()
        # Fallback to first article if nothing is selected
        if not item and self.articlesTree.topLevelItemCount() > 0:
            item = self.articlesTree.topLevelItem(0)
            try:
                self.articlesTree.setCurrentItem(item)
            except Exception:
                pass
        if not item:
            return
        entry = item.data(0, Qt.UserRole) or {}
        link = entry.get('link')
        if link:
            try:
                if sys.platform == 'darwin':
                    subprocess.run(['open', '-g', link], check=False)
                else:
                    webbrowser.open(link)
            except Exception:
                pass

    def _build_article_html(self, entry: Dict[str, Any]) -> Tuple[str, str]:
        """Return (html, base_url) built from feed entry.
        Keeps current parsing approach but improves robustness and layout.
        """
        import html as _html
        title = entry.get('title') or entry.get('link') or ''
        link = entry.get('link') or ''
        base_url = link or ''
        # If we have a prefetched/cleaned version, prefer it
        try:
            aid = self.get_article_id(entry)
            cached = self.article_html_cache.get(aid)
            if cached:
                return cached, base_url
        except Exception:
            pass
        # Prefer content.value if available
        raw = ''
        try:
            if entry.get('content'):
                raw = entry['content'][0].get('value') or ''
        except Exception:
            raw = ''
        if not raw:
            raw = entry.get('summary') or entry.get('description') or ''
        # If raw seems plain text (no tags), escape and wrap
        def _looks_html(s: str) -> bool:
            s2 = (s or '').strip().lower()
            return any(t in s2 for t in ('<p', '<div', '<br', '<img', '<a ', '<ul', '<ol', '<h1', '<h2', '<table'))
        if raw and not _looks_html(raw):
            raw = '<p>' + _html.escape(str(raw)).replace('\n', '<br>') + '</p>'
        if not raw:
            if link:
                raw = f"<p><a href='{_html.escape(link)}' target='_blank'>{_html.escape(link)}</a></p>"
            else:
                raw = "<p>No content</p>"
        # Compose HTML with base and sane defaults
        css_body_font = f"{self.default_font.family()}"
        css_font_size = int(self.current_font_size)
        base_tag = f"<base href='{_html.escape(base_url)}'>" if base_url else ''
        html = f"""
        <html>
            <head>
                <meta charset='utf-8'>
                {base_tag}
                <style>
                    body {{ font-family: {css_body_font}; font-size: {css_font_size}px; margin: 16px; }}
                    img, video, iframe {{ max-width: 100%; height: auto; }}
                    pre {{ white-space: pre-wrap; }}
                    a {{ color: #0366d6; text-decoration: none; }}
                    a:hover {{ text-decoration: underline; }}
                </style>
            </head>
            <body>
                <h2>{_html.escape(title)}</h2>
                <div>{raw}</div>
                <hr>
                <p><a href='{_html.escape(link)}' target='_blank'>Open original</a></p>
            </body>
        </html>
        """
        return html, base_url

    # -------- Prefetch support --------
    def _on_page_fetched(self, aid: str, link: str, html: str) -> None:
        try:
            self.article_html_cache[aid] = html
        except Exception:
            pass
        try:
            self._page_fetching_aids.discard(aid)
        except Exception:
            pass

 

    # ----------------- Favicons -----------------
    def _ensure_favicon_for_url(self, url: str) -> None:
        domain = urlparse(url).netloc or url
        if domain in self.favicon_cache:
            return
        try:
            if domain in self._favicon_fetching:
                return
            self._favicon_fetching.add(domain)
            from rss_reader.services.favicons import FaviconFetchRunnable
            runnable = FaviconFetchRunnable(domain, self)
            self.thread_pool.start(runnable)
        except Exception:
            pass

    def _on_icon_fetch_failed(self, domain: str) -> None:
        try:
            self._favicon_fetching.discard(domain)
        except Exception:
            pass

    # ----------------- Settings -----------------
    def open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec_() == dlg.Accepted:
            # Read updated font size and apply instantly
            try:
                from PyQt5.QtCore import QSettings
                settings = QSettings('rocker', 'SmallRSSReader')
                fs = settings.value('content_font_size', None)
                if fs is not None:
                    self.current_font_size = int(fs)
                    self.apply_font_size()
            except Exception:
                pass
            self._update_tray()

    def update_refresh_timer(self) -> None:
        try:
            if hasattr(self, '_refresh_timer') and self._refresh_timer:
                self._refresh_timer.stop()
        except Exception:
            pass
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(max(1, int(self.refresh_interval)) * 60_000)
        self._refresh_timer.timeout.connect(self.refresh_all_feeds)
        self._refresh_timer.start()

    def apply_font_size(self) -> None:
        # Apply to articles list and header immediately
        try:
            font = QFont(self.default_font.family(), int(self.current_font_size))
            self.articlesTree.setFont(font)
            try:
                self.articlesTree.header().setFont(font)
            except Exception:
                pass
            # Apply to existing items
            count = self.articlesTree.topLevelItemCount()
            cols = self.articlesTree.columnCount()
            for i in range(count):
                it = self.articlesTree.topLevelItem(i)
                if not it:
                    continue
                for c in range(cols):
                    try:
                        it.setFont(c, font)
                    except Exception:
                        pass
            self.articlesTree.viewport().update()
        except Exception:
            pass
        # Re-render current article with updated size
        self._on_article_selected()

    def _on_search_changed(self, text: str) -> None:
        self.search_text = text or ""
        # repopulate current feed
        try:
            item = self.feedsTree.currentItem()
            if not item:
                return
            url = item.data(0, Qt.UserRole)
            feed = next((f for f in self.feeds if f.get('url') == url), None)
            entries = feed.get('entries', []) if feed else []
            self._populate_articles(url, entries)
        except Exception:
            pass

    # ----------------- Utilities -----------------
    def warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    # ----------------- Column widths persistence -----------------
    def _on_section_resized(self, index: int, old: int, new: int) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        widths = [self.articlesTree.columnWidth(i) for i in range(self.articlesTree.columnCount())]
        self.column_widths[url] = widths
        # Дублируем в QSettings, чтобы переживало переустановку
        try:
            from PyQt5.QtCore import QSettings
            s = QSettings('rocker', 'SmallRSSReader')
            s.setValue(f'column_widths:{url}', widths)
        except Exception:
            pass
        if self.storage:
            try:
                self.storage.save_column_widths(self.column_widths)
            except Exception:
                pass

    def _on_header_section_double_clicked(self, index: int) -> None:
        """Resize a column to fit its contents and persist widths."""
        try:
            self.articlesTree.resizeColumnToContents(index)
        except Exception:
            pass
        # Persist via the same path as manual resize
        try:
            self._on_section_resized(index, 0, self.articlesTree.columnWidth(index))
        except Exception:
            pass

    def _save_splitter_sizes(self) -> None:
        """Persist splitter sizes immediately to QSettings."""
        try:
            from PyQt5.QtCore import QSettings
            if hasattr(self, '_splitter') and self._splitter:
                QSettings('rocker', 'SmallRSSReader').setValue('splitter_sizes', self._splitter.sizes())
        except Exception:
            pass

    # ----------------- Read/unread & filters -----------------
    def _toggle_unread_filter(self, checked: bool) -> None:
        self.show_unread_only = checked
        # persist to settings
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            settings.setValue('show_only_unread', bool(checked))
        except Exception:
            pass
        try:
            if hasattr(self, 'feedsTree') and self.feedsTree is not None:
                self._on_feed_selected()
        except Exception:
            pass

    def mark_all_as_read(self) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        feed = next((f for f in self.feeds if f.get('url') == url), None)
        if not feed:
            return
        for e in feed.get('entries', []) or []:
            self.read_articles.add(self.get_article_id(e))
        if self.storage:
            try:
                self.storage.save_read_articles(list(self.read_articles))
            except Exception:
                pass
        self._on_feed_selected()
        self._update_tray()
        self._update_feed_unread_badges()

    def mark_all_as_unread(self) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        feed = next((f for f in self.feeds if f.get('url') == url), None)
        if not feed:
            return
        for e in feed.get('entries', []) or []:
            aid = self.get_article_id(e)
            if aid in self.read_articles:
                self.read_articles.remove(aid)
        if self.storage:
            try:
                self.storage.save_read_articles(list(self.read_articles))
            except Exception:
                pass
        self._on_feed_selected()
        self._update_tray()
        self._update_feed_unread_badges()

    def _on_articles_context_menu(self, pos) -> None:
        item = self.articlesTree.itemAt(pos)
        menu = QMenu(self)
        actOpen = menu.addAction("Open in Browser")
        actMarkUnread = menu.addAction("Mark as Unread")
        actAllRead = menu.addAction("Mark All as Read")
        action = menu.exec_(self.articlesTree.viewport().mapToGlobal(pos))
        if action == actOpen and item:
            entry = item.data(0, Qt.UserRole) or {}
            link = entry.get('link')
            if link:
                try:
                    webbrowser.open(link)
                except Exception:
                    pass
        elif action == actMarkUnread and item:
            entry = item.data(0, Qt.UserRole) or {}
            aid = self.get_article_id(entry)
            if aid in self.read_articles:
                self.read_articles.remove(aid)
                if self.storage:
                    try:
                        self.storage.save_read_articles(list(self.read_articles))
                    except Exception:
                        pass
                self._on_feed_selected()
                self._update_tray()
                self._update_feed_unread_badges()
        elif action == actAllRead:
            self.mark_all_as_read()

    # ----------------- Key handling -----------------
    def keyPressEvent(self, event):  # noqa: N802
        try:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._open_current_article_in_browser()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    # ----------------- OPML import/export -----------------
    def _create_menu(self) -> None:
        # delegate to UI helper
        _ui_create_menu(self)
        
    # ----------------- OPML import/export -----------------
    def export_opml(self) -> None:
        try:
            opml_export(self, self.feeds)
        except Exception:
            self.warn("Error", "Failed to export OPML")

    def import_opml(self) -> None:
        try:
            items = opml_import(self)
            for it in items:
                url = it.get('url')
                title = it.get('title') or url
                if not url or any(f['url'] == url for f in self.feeds):
                    continue
                if self.storage:
                    try:
                        self.storage.upsert_feed(title, url)
                    except Exception:
                        pass
                self.feeds.append({'title': title, 'url': url, 'entries': []})
            try:
                self._rebuild_feeds_tree()
            except Exception:
                pass
        except Exception:
            self.warn("Error", "Failed to import OPML")

    # ----------------- JSON import/export -----------------
    def import_json_feeds(self) -> None:
        try:
            items = json_import(self)
            added = 0
            for it in items:
                url = (it.get('url') or '').strip()
                title = (it.get('title') or url).strip()
                if not url or any(f['url'] == url for f in self.feeds):
                    continue
                if self.storage:
                    try:
                        self.storage.upsert_feed(title, url)
                    except Exception:
                        pass
                self.feeds.append({'title': title, 'url': url, 'entries': []})
                added += 1
            try:
                self._rebuild_feeds_tree()
            except Exception:
                pass
            self._update_tray()
        except Exception:
            self.warn("Error", "Failed to import JSON")

    def import_json_from_path(self, path: str) -> int:
        """Import feeds and settings from a JSON file. Returns count of added feeds.

        Supported formats:
        - List of feeds: [{"title": str, "url": str, "entries": [...]}, ...]
        - Object: {"feeds": [...], "column_widths": {...}}
        """
        import json
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, dict):
            feeds = data.get('feeds', [])
            col_widths = data.get('column_widths', {})
        else:
            feeds = data or []
            col_widths = {}

        added = 0
        for feed in feeds:
            url = (feed.get('url') or '').strip()
            title = (feed.get('title') or url).strip()
            if not url or any(f['url'] == url for f in self.feeds):
                continue
            if self.storage:
                try:
                    self.storage.upsert_feed(title, url, int(feed.get('sort_column', 1)), int(feed.get('sort_order', 0)))
                    if feed.get('entries'):
                        self.storage.replace_entries(url, feed.get('entries') or [])
                except Exception:
                    pass
            self.feeds.append({'title': title, 'url': url, 'entries': feed.get('entries', [])})
            added += 1

        # Rebuild tree once after import
        try:
            self._rebuild_feeds_tree()
        except Exception:
            pass

        if col_widths and isinstance(col_widths, dict):
            try:
                self.column_widths.update(col_widths)
                if self.storage:
                    self.storage.save_column_widths(self.column_widths)
            except Exception:
                pass

        return added

    def export_json_feeds(self) -> None:
        try:
            json_export(self, self.feeds)
        except Exception:
            self.warn("Error", "Failed to export JSON")

    def export_json_to_path(self, path: str) -> None:
        """Export current feeds and column widths to a JSON file."""
        import json
        payload = {
            'feeds': self.feeds,
            'column_widths': self.column_widths,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ----------------- Unread badges (blue dot) -----------------
    def _unread_dot_pixmap(self, size: int = 8, color: QColor = QColor(0, 122, 255)) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, size, size)
        painter.end()
        return pm

    def _icon_with_unread_dot(self, base_icon: Optional[QIcon]) -> QIcon:
        # Compose a 16x16 icon with a small blue dot at bottom-right
        size = 16
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        if base_icon and not base_icon.isNull():
            base_pm = base_icon.pixmap(size, size)
            painter.drawPixmap(0, 0, base_pm)
        # draw dot
        dot = self._unread_dot_pixmap(6)
        painter.drawPixmap(size - dot.width(), size - dot.height(), dot)
        painter.end()
        return QIcon(pm)

    def _apply_feed_unread_badge(self, item: QTreeWidgetItem) -> None:
        try:
            url = item.data(0, Qt.UserRole) or ""
            if not url:
                return
            feed = next((f for f in self.feeds if f.get('url') == url), None)
            if not feed:
                return
            ents = feed.get('entries', []) or []
            has_unread = any(self.get_article_id(e) not in self.read_articles for e in ents)
            base_icon = item.data(0, Qt.UserRole + 1)
            if not isinstance(base_icon, QIcon):
                # fallback to current icon
                base_icon = item.icon(0)
            if has_unread:
                item.setIcon(0, self._icon_with_unread_dot(base_icon))
            else:
                # restore base icon
                item.setIcon(0, base_icon if isinstance(base_icon, QIcon) else QIcon())
        except Exception:
            pass

    def _update_feed_unread_badges(self) -> None:
        try:
            for item in self._iter_feed_items():
                self._apply_feed_unread_badge(item)
        except Exception:
            pass

    # ----------------- Tray & notifications -----------------
    def _init_tray_icon(self) -> None:
        # delegate to UI helper if enabled in settings
        enabled = True
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            enabled = settings.value('tray_icon_enabled', True, type=bool)
        except Exception:
            pass
        if enabled:
            _ui_init_tray(self)

    def eventFilter(self, obj, event):  # noqa: N802
        try:
            if obj is getattr(self, 'searchEdit', None) and event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self.searchEdit.clear()
                    return True
            # Коалесцированное сохранение геометрии окна при изменении размера/перемещении
            if obj is self and event.type() in (QEvent.Resize, QEvent.Move):
                try:
                    if getattr(self, '_geom_save_timer', None):
                        self._geom_save_timer.start()
                except Exception:
                    pass
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _notify_new_read(self) -> None:
        # simple notification when marking as read, respects settings flag if present
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            enabled = settings.value('notifications_enabled', False, type=bool)
            if enabled and getattr(self, 'tray', None):
                self.tray.showMessage('Small RSS Reader', 'Article marked as read', QSystemTrayIcon.Information, 2000)
        except Exception:
            pass

    def _update_tray(self) -> None:
        try:
            total = 0
            unread = 0
            for f in self.feeds:
                ents = f.get('entries', []) or []
                total += len(ents)
                unread += sum(1 for e in ents if self.get_article_id(e) not in self.read_articles)
            if getattr(self, 'tray', None):
                self.tray.setToolTip(f"Unread: {unread} / {total}")
        except Exception:
            pass

    # ----------------- Close/persist -----------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # save read articles & column widths
        if self.storage:
            try:
                self.storage.save_read_articles(list(self.read_articles))
                self.storage.save_column_widths(self.column_widths)
            except Exception:
                pass
        # auto-backup to iCloud if enabled
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            if settings.value('icloud_backup_enabled', False, type=bool):
                self.backup_to_icloud()
        except Exception:
            pass
        # save window geometry/state
        save_window_state(self)
        # persist splitter sizes and font size
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            if hasattr(self, '_splitter') and self._splitter:
                settings.setValue('splitter_sizes', self._splitter.sizes())
            settings.setValue('content_font_size', int(self.current_font_size))
        except Exception:
            pass
        # Hide tray on quit for cleaner shutdown UX
        try:
            if getattr(self, 'tray', None):
                self.tray.hide()
        except Exception:
            pass
        super().closeEvent(event)

    # ----------------- View toggles -----------------
    def _toggle_toolbar(self, visible: bool) -> None:
        try:
            self.toolbar.setVisible(bool(visible))
        except Exception:
            pass

    def _toggle_menubar(self, visible: bool) -> None:
        try:
            self.menuBar().setVisible(bool(visible))
        except Exception:
            pass

    # ----------------- About -----------------
    def show_about(self) -> None:
        # Collect version and paths info
        VERSION = TAG = COMMIT = ORIGIN = "unknown"
        try:
            from app_version import VERSION as _V, TAG as _T, COMMIT as _C, ORIGIN as _O
            VERSION, TAG, COMMIT, ORIGIN = _V, _T, _C, _O
        except Exception:
            pass
        try:
            db_path = get_user_data_path("db.sqlite3")
        except Exception:
            db_path = os.path.abspath("db.sqlite3")
        try:
            log_path = get_user_data_path("rss_reader.log")
            if not os.path.isabs(log_path):
                log_path = os.path.abspath(log_path)
        except Exception:
            log_path = os.path.abspath("rss_reader.log")

        html = f"""
        <html><head><meta charset='utf-8'>
        <style>
          body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; font-size: 13px; }}
          code {{ font-family: SFMono-Regular, Menlo, monospace; }}
          .lbl {{ color: #666; }}
        </style>
        </head><body>
        <h3>Small RSS Reader</h3>
        <p class='lbl'>A small, fast RSS reader built with PyQt5.</p>
        <p><b>Version:</b> {VERSION} (<code>{TAG}</code>, <code>{COMMIT}</code>)</p>
        <p><b>Database:</b> <code>{db_path}</code></p>
        <p><b>Log file:</b> <code>{log_path}</code></p>
        <p><b>Repository:</b> <a href='{ORIGIN}'>{ORIGIN}</a></p>
        </body></html>
        """
        QMessageBox.about(self, "About", html)


# Background page prefetch runnable (module-level)
class _PageFetchRunnable(QRunnable):
    def __init__(self, aid: str, link: str, app: RSSReader) -> None:
        super().__init__()
        self.aid = aid
        self.link = link
        self.app = app

    def run(self) -> None:  # pragma: no cover - network
        try:
            import requests
            from bs4 import BeautifulSoup
            resp = requests.get(self.link, timeout=8, headers={
                'User-Agent': 'SmallRSSReader/1.0 (+https://github.com/SergeyLavrentev)'
            })
            text = resp.text if hasattr(resp, 'text') else ''
            html = text
            try:
                if text:
                    soup = BeautifulSoup(text, 'html.parser')
                    # Remove noisy elements
                    for tag in soup(['script', 'style', 'noscript']):
                        tag.decompose()
                    # Heuristic: main content by common containers
                    container = None
                    for sel in ['article', 'main', '#content', '.post', '.entry-content', '.article-content']:
                        container = soup.select_one(sel)
                        if container:
                            break
                    if not container:
                        container = soup.body or soup
                    cleaned = str(container)
                    html = f"<html><head><meta charset='utf-8'><base href='{self.link}'></head><body>{cleaned}</body></html>"
            except Exception:
                pass
            self.app.page_fetched.emit(self.aid, self.link, html)
        except Exception:
            try:
                self.app.page_fetch_failed.emit(self.aid)
            except Exception:
                pass
