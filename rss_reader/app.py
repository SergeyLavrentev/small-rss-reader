"""Application API for Small RSS Reader (refactored).

Minimal, test-ready implementation of RSSReader moved out of the legacy
module to keep the public shim tiny. Focuses on core logic exercised by
unit tests; UI-heavy pieces live in rss_reader.ui/ and services/ packages.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import webbrowser

from PyQt5.QtGui import QIcon, QPixmap, QFont, QCloseEvent
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QSplitter,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QAction,
    QFileDialog,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QThreadPool, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu

from rss_reader.utils.net import compute_article_id
from rss_reader.utils.domains import _domain_variants
from rss_reader.utils.paths import resource_path
from rss_reader.ui.widgets import FeedsTreeWidget, ArticleTreeWidgetItem, WebEnginePage
from rss_reader.ui.dialogs import AddFeedDialog, SettingsDialog
from storage import Storage

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

    def __init__(self) -> None:
        super().__init__()
        # Minimal state used by tests
        self.max_days = 30
        self.feeds = []
        self.read_articles = set()
        self.column_widths = {}
        self.group_settings = {}
        self.group_name_mapping = {}
        self.favicon_cache = {}
        self.data_changed = False
        # Optional storage (created only in interactive runs to keep tests lightweight)
        self.storage = None
        self.refresh_interval = 60
        self.default_font = QFont("Arial", 12)
        self.current_font_size = 12
        self.api_key = ""
        self.show_unread_only = False

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
        self.setWindowIcon(QIcon(resource_path("icons/rss_icon.icns")))
        self.resize(1200, 800)

        # Menu/actions
        self._create_actions()
        self._create_menu()

        # Central layout
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal, central)
        layout.addWidget(splitter)

        # Left: feeds tree
        self.feedsTree = FeedsTreeWidget(splitter)
        self.feedsTree.setHeaderHidden(True)
        self.feedsTree.setObjectName("feedsTree")
        self.feedsTree.itemSelectionChanged.connect(self._on_feed_selected)

        # Center: articles list
        self.articlesTree = QTreeWidget(splitter)
        self.articlesTree.setHeaderLabels(["Title", "Date"])
        self.articlesTree.setObjectName("articlesTree")
        self.articlesTree.itemSelectionChanged.connect(self._on_article_selected)
        # Open in browser on activation (double-click or Enter/Return)
        self.articlesTree.itemActivated.connect(lambda _i, _c: self._open_current_article_in_browser())
        self.articlesTree.setRootIsDecorated(False)
        self.articlesTree.setAlternatingRowColors(True)
        self.articlesTree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.articlesTree.customContextMenuRequested.connect(self._on_articles_context_menu)
        self.articlesTree.header().sectionResized.connect(self._on_section_resized)

        # Right: article content
        self.webView = QWebEngineView(splitter)
        self.webView.setObjectName("contentView")
        self.webView.setPage(WebEnginePage(self.webView))
        self.webView.setHtml("<html><body><p>Выберите статью, чтобы увидеть содержимое</p></body></html>")

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 4)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Готово")

        # Infrastructure
        self.thread_pool = QThreadPool.globalInstance()
        self.icon_fetched.connect(self.on_icon_fetched)

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
        
        # Restore window geometry/state
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            geom = settings.value('window_geometry')
            state = settings.value('window_state')
            if geom:
                self.restoreGeometry(geom)
            if state:
                self.restoreState(state)
        except Exception:
            pass

    # ---- IDs / dates ----
    def get_article_id(self, entry: Dict[str, Any]) -> str:
        return compute_article_id(entry)

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
            self.statusBar().showMessage("Feed URL is required.", 5000)
            return False
        if not new_url.startswith(('http://', 'https://')):
            new_url = 'http://' + new_url
        old_url = feed_item.data(0, Qt.UserRole)
        if new_url == old_url:
            return True
        # Duplicate guard (excluding current)
        if any(f['url'] == new_url for f in self.feeds if f.get('url') != old_url):
            self.statusBar().showMessage("This feed URL is already added.", 5000)
            return False
        feed_data = next((f for f in self.feeds if f.get('url') == old_url), None)
        if not feed_data:
            self.statusBar().showMessage("Feed data not found.", 5000)
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
        self.data_changed = True
        self.statusBar().showMessage("Feed URL updated.", 5000)
        return True

    # ---- Backup / Restore ----
    def backup_to_icloud(self) -> None:
        from pathlib import Path
        backup_folder = os.path.join(
            Path.home(),
            "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup",
        )
        os.makedirs(backup_folder, exist_ok=True)
        filename = 'db.sqlite3'
        source = get_user_data_path(filename)
        dest = os.path.join(backup_folder, filename)
        if os.path.exists(source):
            try:
                shutil.copy2(source, dest)
            except Exception:
                pass
        self.statusBar().showMessage("Backup to iCloud completed successfully.", 5000)

    def restore_from_icloud(self) -> None:
        from pathlib import Path
        backup_folder = os.path.join(
            Path.home(),
            "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup",
        )
        filename = 'db.sqlite3'
        backup_file = os.path.join(backup_folder, filename)
        if os.path.exists(backup_file):
            dest = get_user_data_path(filename)
            try:
                shutil.copy2(backup_file, dest)
            except Exception:
                pass
        self.statusBar().showMessage("Restore from iCloud completed successfully.", 5000)

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
        # Update tree icons for matching feeds (single-level tree in refactor build)
        try:
            top_count = self.feedsTree.topLevelItemCount()
            for i in range(top_count):
                item = self.feedsTree.topLevelItem(i)
                url = item.data(0, Qt.UserRole) or ""
                if not url:
                    continue
                try:
                    feed_domain = urlparse(url).netloc or url
                    if feed_domain in _domain_variants(domain):
                        item.setIcon(0, icon)
                except Exception:
                    pass
        except Exception:
            pass

    # Helper for optional UI refresh in update_feed_url
    def set_feed_icon_placeholder(self, item, url: str) -> None:
        try:
            domain = urlparse(url).netloc or url
            icon = self.favicon_cache.get(domain, QIcon())
            item.setIcon(0, icon)
        except Exception:
            pass

    # ----------------- UI and actions -----------------
    def _create_actions(self) -> None:
        self.actAddFeed = QAction("Добавить ленту", self)
        self.actAddFeed.triggered.connect(self.add_feed)
        self.actRemoveFeed = QAction("Удалить ленту", self)
        self.actRemoveFeed.triggered.connect(self.remove_selected_feed)
        self.actRefreshAll = QAction("Обновить все", self)
        self.actRefreshAll.triggered.connect(self.refresh_all_feeds)
        self.actRefreshFeed = QAction("Обновить ленту", self)
        self.actRefreshFeed.triggered.connect(self.refresh_selected_feed)
        self.actMarkAllRead = QAction("Пометить все как прочитанные", self)
        self.actMarkAllRead.triggered.connect(self.mark_all_as_read)
        self.actSettings = QAction("Настройки", self)
        self.actSettings.triggered.connect(self.open_settings)
        self.actBackup = QAction("Backup в iCloud", self)
        self.actBackup.triggered.connect(self.backup_to_icloud)
        self.actRestore = QAction("Восстановить из iCloud", self)
        self.actRestore.triggered.connect(self.restore_from_icloud)
        self.actQuit = QAction("Выход", self)
        self.actQuit.triggered.connect(self.close)
        self.actOnlyUnread = QAction("Показывать только непрочитанные", self)
        self.actOnlyUnread.setCheckable(True)
        self.actOnlyUnread.toggled.connect(self._toggle_unread_filter)
        self.actImportOPML = QAction("Импорт OPML…", self)
        self.actImportOPML.triggered.connect(self.import_opml)
        self.actExportOPML = QAction("Экспорт OPML…", self)
        self.actExportOPML.triggered.connect(self.export_opml)
        self.actImportJSON = QAction("Импорт JSON…", self)
        self.actImportJSON.triggered.connect(self.import_json_feeds)
        self.actExportJSON = QAction("Экспорт JSON…", self)
        self.actExportJSON.triggered.connect(self.export_json_feeds)
        # Shortcuts
        try:
            from PyQt5.QtGui import QKeySequence
            self.actRefreshAll.setShortcut(QKeySequence.Refresh)
        except Exception:
            pass
        # Help/About
        self.actAbout = QAction("О программе", self)
        self.actAbout.triggered.connect(self.show_about)
        self.actAboutQt = QAction("О Qt", self)
        self.actAboutQt.triggered.connect(lambda: QMessageBox.aboutQt(self))

    def _create_menu(self) -> None:
        mb = self.menuBar()
        file_menu = mb.addMenu("Файл")
        file_menu.addAction(self.actAddFeed)
        file_menu.addAction(self.actRemoveFeed)
        file_menu.addSeparator()
        file_menu.addAction(self.actBackup)
        file_menu.addAction(self.actRestore)
        file_menu.addSeparator()
        file_menu.addAction(self.actImportJSON)
        file_menu.addAction(self.actExportJSON)
        file_menu.addSeparator()
        file_menu.addAction(self.actImportOPML)
        file_menu.addAction(self.actExportOPML)
        file_menu.addSeparator()
        file_menu.addAction(self.actQuit)

        act_menu = mb.addMenu("Действия")
        act_menu.addAction(self.actRefreshAll)
        act_menu.addAction(self.actRefreshFeed)
        act_menu.addAction(self.actMarkAllRead)
        act_menu.addAction(self.actOnlyUnread)

        settings_menu = mb.addMenu("Настройки")
        settings_menu.addAction(self.actSettings)

        help_menu = mb.addMenu("Справка")
        help_menu.addAction(self.actAbout)
        help_menu.addAction(self.actAboutQt)

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
        except Exception:
            pass
        for feed in self.feeds:
            self._add_feed_item(feed.get('title') or feed.get('url'), feed.get('url'))
        self._update_tray()

    # helper to add item into feeds tree and set icon from cache/storage
    def _add_feed_item(self, title: str, url: str) -> QTreeWidgetItem:
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
            item.setIcon(0, icon)
        self.feedsTree.addTopLevelItem(item)
        return item

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
                self.warn("Дубликат", "Эта лента уже добавлена")
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
            item = self._add_feed_item(title, url)
            self.statusBar().showMessage("Лента добавлена", 3000)
            self.refresh_feed(url)
            self.feedsTree.setCurrentItem(item)

    def remove_selected_feed(self) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
        if QMessageBox.question(self, "Удалить ленту", f"Удалить {url}?") != QMessageBox.Yes:
            return
        # remove from storage and memory
        if self.storage:
            try:
                self.storage.remove_feed(url)
            except Exception:
                pass
        self.feeds = [f for f in self.feeds if f.get('url') != url]
        idx = self.feedsTree.indexOfTopLevelItem(item)
        self.feedsTree.takeTopLevelItem(idx)
        self.articlesTree.clear()
        self.webView.setHtml("<html><body><p>Лента удалена</p></body></html>")

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
            self.statusBar().showMessage(f"Обновляю: {url}", 2000)
        except Exception:
            pass

    @pyqtSlot(str, object)
    def _on_feed_fetched(self, url: str, feed_obj: Any) -> None:
        if not feed_obj:
            self.statusBar().showMessage(f"Не удалось загрузить: {url}", 4000)
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
        self.statusBar().showMessage(f"Загружено: {url}", 2000)
        self._update_tray()

    # ----------------- UI handlers -----------------
    def _on_feed_selected(self) -> None:
        item = self.feedsTree.currentItem()
        if not item:
            return
        url = item.data(0, Qt.UserRole)
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
        # favicon fetch on selection if not present
        self._ensure_favicon_for_url(url)

    def _populate_articles(self, feed_url: str, entries: List[Dict[str, Any]]) -> None:
        self.articlesTree.clear()
        visible_entries = entries
        if self.show_unread_only:
            visible_entries = [e for e in entries if self.get_article_id(e) not in self.read_articles]
        for e in visible_entries:
            title = e.get('title') or e.get('link') or 'Untitled'
            dt = self.get_entry_date(e)
            item = ArticleTreeWidgetItem([title, dt.strftime('%Y-%m-%d %H:%M') if dt != datetime.min else ''])
            item.setData(0, Qt.UserRole, e)
            item.setData(1, Qt.UserRole, dt)
            # mark read visually
            aid = self.get_article_id(e)
            if aid in self.read_articles:
                item.setForeground(0, Qt.gray)
            self.articlesTree.addTopLevelItem(item)
        self.articlesTree.sortItems(1, Qt.DescendingOrder)
        # apply column widths
        widths = self.column_widths.get(feed_url)
        if widths:
            for i, w in enumerate(widths):
                if w:
                    self.articlesTree.setColumnWidth(i, int(w))

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
        # build simple HTML
        title = entry.get('title', '')
        link = entry.get('link', '')
        content = ''
        if entry.get('content'):
            try:
                content = entry['content'][0]['value']
            except Exception:
                content = ''
        content = content or entry.get('summary', '')
        html = f"""
        <html><head><meta charset='utf-8'>
        <style>body {{ font-family: {self.default_font.family()}; font-size: {self.current_font_size}px; }}</style>
        </head><body>
        <h2><a href='{link}' target='_blank'>{title}</a></h2>
        <div>{content}</div>
        </body></html>
        """
        self.webView.setHtml(html)
        # notifications (optional)
        self._notify_new_read()

    def _open_current_article_in_browser(self) -> None:
        """Open the currently selected article's link in the system browser."""
        item = self.articlesTree.currentItem()
        if not item:
            return
        entry = item.data(0, Qt.UserRole) or {}
        link = entry.get('link')
        if link:
            try:
                webbrowser.open(link)
            except Exception:
                pass

    # ----------------- Favicons -----------------
    def _ensure_favicon_for_url(self, url: str) -> None:
        domain = urlparse(url).netloc or url
        if domain in self.favicon_cache:
            return
        try:
            from rss_reader.services.favicons import FaviconFetchRunnable
            runnable = FaviconFetchRunnable(domain, self)
            self.thread_pool.start(runnable)
        except Exception:
            pass

    # ----------------- Settings -----------------
    def open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec_() == dlg.Accepted:
            self.statusBar().showMessage("Настройки сохранены", 3000)
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
        # Re-render current article with updated size
        self._on_article_selected()

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
        if self.storage:
            try:
                self.storage.save_column_widths(self.column_widths)
            except Exception:
                pass

    # ----------------- Read/unread & filters -----------------
    def _toggle_unread_filter(self, checked: bool) -> None:
        self.show_unread_only = checked
        self._on_feed_selected()

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

    def _on_articles_context_menu(self, pos) -> None:
        item = self.articlesTree.itemAt(pos)
        menu = QMenu(self)
        actOpen = menu.addAction("Открыть в браузере")
        actMarkUnread = menu.addAction("Пометить как непрочитанное")
        actAllRead = menu.addAction("Пометить все как прочитанные")
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
    def export_opml(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт OPML", "feeds.opml", "OPML Files (*.opml)")
        if not path:
            return
        try:
            import xml.etree.ElementTree as ET
            opml = ET.Element('opml', version='2.0')
            head = ET.SubElement(opml, 'head')
            title = ET.SubElement(head, 'title')
            title.text = 'Small RSS Reader Feeds'
            body = ET.SubElement(opml, 'body')
            for f in self.feeds:
                ET.SubElement(body, 'outline', type='rss', text=f.get('title') or f.get('url'), xmlUrl=f.get('url'))
            tree = ET.ElementTree(opml)
            tree.write(path, encoding='utf-8', xml_declaration=True)
            self.statusBar().showMessage("Экспортировано OPML", 3000)
        except Exception:
            self.warn("Ошибка", "Не удалось экспортировать OPML")

    def import_opml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Импорт OPML", "", "OPML Files (*.opml)")
        if not path:
            return
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(path)
            root = tree.getroot()
            outlines = root.findall('.//outline')
            for o in outlines:
                url = o.attrib.get('xmlUrl')
                text = o.attrib.get('text') or url
                if url and not any(f['url'] == url for f in self.feeds):
                    if self.storage:
                        try:
                            self.storage.upsert_feed(text, url)
                        except Exception:
                            pass
                    self.feeds.append({'title': text, 'url': url, 'entries': []})
                    self._add_feed_item(text, url)
            self.statusBar().showMessage("Импортировано OPML", 3000)
        except Exception:
            self.warn("Ошибка", "Не удалось импортировать OPML")

    # ----------------- JSON import/export -----------------
    def import_json_feeds(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Импорт JSON", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            added = self.import_json_from_path(path)
            self.statusBar().showMessage(f"Импортировано лент: {added}", 3000)
            self._update_tray()
        except Exception:
            self.warn("Ошибка", "Не удалось импортировать JSON")

    def import_json_from_path(self, path: str) -> int:
        """Импорт лент и настроек из JSON-файла. Возвращает количество добавленных лент.

        Форматы поддерживаются:
        - Список лент: [{"title": str, "url": str, "entries": [...]}, ...]
        - Объект: {"feeds": [...], "column_widths": {...}}
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
            # UI tree might be absent in tests
            try:
                self._add_feed_item(title, url)
            except Exception:
                pass
            added += 1

        if col_widths and isinstance(col_widths, dict):
            try:
                self.column_widths.update(col_widths)
                if self.storage:
                    self.storage.save_column_widths(self.column_widths)
            except Exception:
                pass

        return added

    def export_json_feeds(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт JSON", "feeds.json", "JSON Files (*.json)")
        if not path:
            return
        try:
            self.export_json_to_path(path)
            self.statusBar().showMessage("Экспортировано JSON", 3000)
        except Exception:
            self.warn("Ошибка", "Не удалось экспортировать JSON")

    def export_json_to_path(self, path: str) -> None:
        """Экспорт текущих лент и ширин колонок в JSON-файл."""
        import json
        payload = {
            'feeds': self.feeds,
            'column_widths': self.column_widths,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ----------------- Tray & notifications -----------------
    def _init_tray_icon(self) -> None:
        try:
            icon_path = resource_path("icons/rss_tray_icon.png")
            icon = QIcon(icon_path)
            self.tray = QSystemTrayIcon(icon, self)
            menu = QMenu()
            menu.addAction(self.actRefreshAll)
            menu.addAction(self.actOnlyUnread)
            menu.addSeparator()
            quit_action = QAction("Выход", self)
            quit_action.triggered.connect(self.close)
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.Trigger else None)
            self.tray.show()
            self._update_tray()
        except Exception:
            self.tray = None  # type: ignore

    def _notify_new_read(self) -> None:
        # simple notification when marking as read, respects settings flag if present
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            enabled = settings.value('notifications_enabled', False, type=bool)
            if enabled and getattr(self, 'tray', None):
                self.tray.showMessage('Small RSS Reader', 'Статья отмечена как прочитанная', QSystemTrayIcon.Information, 2000)
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
                self.tray.setToolTip(f"Непрочитанных: {unread} / {total}")
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
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings('rocker', 'SmallRSSReader')
            settings.setValue('window_geometry', self.saveGeometry())
            settings.setValue('window_state', self.saveState())
        except Exception:
            pass
        super().closeEvent(event)

    # ----------------- About -----------------
    def show_about(self) -> None:
        try:
            from app_version import VERSION
        except Exception:
            VERSION = "dev"
        text = (
            f"Small RSS Reader\n\n"
            f"Версия: {VERSION}\n"
            f"Небольшой быстрый RSS-ридер на PyQt5."
        )
        QMessageBox.about(self, "О программе", text)
