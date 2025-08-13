#!/usr/bin/env python3
import sys
import os
import json
import logging
from logging.handlers import RotatingFileHandler
import feedparser
import signal
import re
import unicodedata
import hashlib
import argparse
import sqlite3
import shutil
import threading
import requests
import subprocess
import plistlib
from datetime import datetime, timedelta
from urllib.parse import urlparse
from omdbapi.movie_search import GetMovie
from PyQt5.QtWidgets import QFontComboBox, QComboBox
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox, QAction, QFileDialog, QMenu, QToolBar,
    QHeaderView, QDialog, QFormLayout, QSizePolicy, QStyle, QSpinBox, QAbstractItemView, QInputDialog,
    QDialogButtonBox, QCheckBox, QSplashScreen, QSystemTrayIcon
)
from PyQt5.QtGui import (
    QCursor, QFont, QIcon, QPixmap, QPainter, QBrush, QColor, QTransform, QDesktopServices
)
from PyQt5.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QUrl, QSettings, QSize, QEvent, QObject, QRunnable, QThreadPool, pyqtSlot,
    qInstallMessageHandler, QtMsgType, QByteArray, QBuffer
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from pathlib import Path
from storage import Storage
try:
    # Build-time constants injected by setup.py
    from app_version import VERSION as APP_VERSION, TAG as APP_TAG, COMMIT as APP_COMMIT, ORIGIN as APP_ORIGIN
except Exception:
    APP_VERSION = APP_TAG = APP_COMMIT = ""
    APP_ORIGIN = "https://github.com/SergeyLavrentev/small-rss-reader"

# Fallback URL of the remote repository (used when .git is unavailable in packaged app)
REMOTE_REPO_FALLBACK = "https://github.com/SergeyLavrentev/small-rss-reader"

# =========================
# 1. Helper functions and classes
# =========================

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_path, relative_path)
    if not os.path.exists(full_path):
        logging.error(f"Resource not found: {full_path}")
        QMessageBox.critical(None, "Resource Error", f"Required resource not found: {full_path}")
        sys.exit(1)
    return full_path

def get_user_data_path(filename):
    """Get path to user data directory for the application."""
    if getattr(sys, 'frozen', False):
        if sys.platform == "darwin":
            return os.path.join(Path.home(), "Library", "Application Support", "SmallRSSReader", filename)
        elif sys.platform == "win32":
            return os.path.join(os.getenv('APPDATA'), "SmallRSSReader", filename)
        else:
            return os.path.join(Path.home(), ".smallrssreader", filename)
    else:
        return os.path.join(os.path.abspath("."), filename)

def _strip_www(domain: str) -> str:
    try:
        return domain[4:] if domain.lower().startswith('www.') else domain
    except Exception:
        return domain

def _base_domain(domain: str) -> str:
    """Heuristic to get base domain without heavy deps (tldextract).
    - If TLD length is 2 (e.g., .uk) and second-level is short (<=3), take last 3 labels.
    - Else take last 2 labels.
    """
    try:
        parts = [p for p in domain.split('.') if p]
        if len(parts) <= 2:
            return domain
        if len(parts[-1]) == 2 and len(parts[-2]) <= 3:
            return '.'.join(parts[-3:])
        return '.'.join(parts[-2:])
    except Exception:
        return domain

def _domain_variants(domain: str):
    try:
        d = _strip_www(domain)
        base = _base_domain(d)
        variants = [d]
        if base != d:
            variants.append(base)
        www_base = f"www.{base}"
        if www_base not in variants:
            variants.append(www_base)
        return variants
    except Exception:
        return [domain]

def fetch_favicon(url):
    """Fetch the favicon for a given URL and resize it to a standard size."""
    try:
        domain = urlparse(url).netloc
        favicon_url = f"https://{domain}/favicon.ico"
        logging.debug(f"Attempting to fetch favicon from: {favicon_url}")
        response = requests.get(favicon_url, stream=True, timeout=5)
        if response.status_code == 200:
            pixmap = QPixmap()
            if pixmap.loadFromData(response.content):
                logging.debug(f"Successfully loaded favicon for {domain}")
                # Resize the favicon to a standard size (e.g., 16x16)
                return pixmap.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                logging.warning(f"Failed to load favicon data for {domain}.")
        else:
            logging.warning(f"Failed to fetch favicon for {domain}: {response.status_code}")
    except Exception as e:
        logging.error(f"Error fetching favicon for {domain}: {e}")
    return None

def format_date_column(entry_date):
    """Format the date column to display only the date."""
    return entry_date.strftime('%Y-%m-%d')

class FetchFeedRunnable(QRunnable):
    def __init__(self, url, worker):
        super().__init__()
        self.url = url
        self.worker = worker

    @pyqtSlot()
    def run(self):
        try:
            feed = feedparser.parse(self.url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            self.worker.feed_fetched.emit(self.url, feed)
        except Exception as e:
            logging.error(f"Failed to fetch feed {self.url}: {e}")
            self.worker.feed_fetched.emit(self.url, None)

class Worker(QObject):
    feed_fetched = pyqtSignal(str, object)  # Emits (url, feed)

class FetchMovieDataThread(QThread):
    movie_data_fetched = pyqtSignal(int, str, dict)

    def __init__(self, entries, api_key, cache, quit_flag):
        super().__init__()
        self.entries = entries
        self.api_key = api_key
        self.movie_data_cache = cache
        self.quit_flag = quit_flag  # threading.Event for graceful shutdown
        # Local stop flag to cancel this specific thread without touching global quit_flag
        self._stop_event = threading.Event()

    def request_stop(self):
        try:
            self._stop_event.set()
        except Exception:
            pass

    def run(self):
        if not self.api_key:
            logging.warning("OMDb API key not provided. Skipping movie data fetching.")
            return
        for index, entry in enumerate(self.entries):
            if self.quit_flag.is_set() or self._stop_event.is_set():
                break
            title = entry.get('title', 'No Title')
            movie_title = self.extract_movie_title(title)
            # Compute a stable article id compatible with UI mapping
            unique_string = entry.get('id') or entry.get('guid') or entry.get('link') or (entry.get('title', '') + entry.get('published', ''))
            try:
                article_id = hashlib.md5(unique_string.encode('utf-8')).hexdigest()
            except Exception:
                article_id = ''
            if movie_title in self.movie_data_cache:
                movie_data = self.movie_data_cache[movie_title]
                logging.debug(f"Retrieved cached movie data for '{movie_title}'.")
            else:
                movie_data = self.fetch_movie_data(movie_title)
                if not movie_data:
                    # Negative cache to avoid spamming requests for not found
                    movie_data = {"_not_found": True}
                self.movie_data_cache[movie_title] = movie_data
                logging.debug(f"Fetched and cached movie data for '{movie_title}'.")
            self.movie_data_fetched.emit(index, article_id, movie_data)

    @staticmethod
    def extract_movie_title(text):
        text = re.sub(r'^\[.*?\]\s*', '', text)
        parts = text.split('/')

        def is_mostly_latin(s):
            try:
                latin_count = sum('LATIN' in unicodedata.name(c) for c in s if c.isalpha())
                total_count = sum(c.isalpha() for c in s)
                return latin_count > total_count / 2 if total_count > 0 else False
            except ValueError:
                return False

        for part in parts:
            part = part.strip()
            if is_mostly_latin(part):
                english_title = part
                break
        else:
            english_title = text.strip()

        english_title = re.split(r'[\(\[]', english_title)[0].strip()
        return english_title

    def fetch_movie_data(self, movie_title):
        try:
            movie = GetMovie(api_key=self.api_key)
            movie_data = movie.get_movie(title=movie_title)
            if not movie_data:
                logging.debug(f"No data returned from OMDb for '{movie_title}'.")
            return movie_data
        except Exception as e:
            msg = str(e)
            if 'Movie not found' in msg:
                logging.debug(f"OMDb: not found for '{movie_title}'.")
            else:
                logging.error(f"Failed to fetch movie data for '{movie_title}': {e}")
            return {}
class FaviconFetchRunnable(QRunnable):
    """Background task to fetch a site's favicon by domain."""
    def __init__(self, domain: str, reader: 'RSSReader'):
        super().__init__()
        self.domain = domain
        self.reader = reader

    @pyqtSlot()
    def run(self):
        try:
            # Try https first, then http
            for scheme in ("https", "http"):
                url = f"{scheme}://{self.domain}/favicon.ico"
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200 and resp.content:
                        self.reader.icon_fetched.emit(self.domain, resp.content)
                        return
                except Exception:
                    continue
            # Fallback to Google S2 favicon service
            try:
                s2 = f"https://www.google.com/s2/favicons?sz=64&domain={self.domain}"
                resp = requests.get(s2, timeout=5)
                if resp.status_code == 200 and resp.content:
                    self.reader.icon_fetched.emit(self.domain, resp.content)
                    return
            except Exception:
                pass
            # All attempts failed
            try:
                self.reader.icon_fetch_failed.emit(self.domain)
            except Exception:
                pass
        except Exception:
            try:
                self.reader.icon_fetch_failed.emit(self.domain)
            except Exception:
                pass


class ArticleTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        data1 = self.data(column, Qt.UserRole)
        data2 = other.data(column, Qt.UserRole)

        if data1 is None or data1 == '':
            data1 = self.text(column)
        if data2 is None or data2 == '':
            data2 = other.text(column)

        if isinstance(data1, datetime) and isinstance(data2, datetime):
            return data1 < data2
        elif isinstance(data1, float) and isinstance(data2, float):
            return data1 < data2
        else:
            return str(data1) < str(data2)

class FeedsTreeWidget(QTreeWidget):
    def dropEvent(self, event):
        source_item = self.currentItem()
        target_item = self.itemAt(event.pos())

        if target_item and source_item and target_item.parent() != source_item.parent():
            try:
                parent = self.parent()
                if hasattr(parent, 'warn'):
                    parent.warn("Invalid Move", "Feeds can only be moved within their own groups.")
                else:
                    QMessageBox.warning(self, "Invalid Move", "Feeds can only be moved within their own groups.")
            except Exception:
                pass
            event.ignore()
            return
        super().dropEvent(event)

class WebEnginePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if (_type == QWebEnginePage.NavigationTypeLinkClicked):
            QDesktopServices.openUrl(url)  # Open the link in the default browser
            return False  # Prevent the WebEngineView from handling the link
        return super().acceptNavigationRequest(url, _type, isMainFrame)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Completely suppress all JavaScript console messages
        pass

    def handleUnsupportedContent(self, reply):
        # Silently handle unsupported content without logging
        reply.abort()

# =========================
# 2. КЛАССЫ ДИАЛОГОВ И НАСТРОЕК (UI)
# =========================

class AddFeedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Feed")
        self.setModal(True)
        self.setFixedSize(400, 150)
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("Enter custom feed name (optional)")
        layout.addRow("Feed Name:", self.name_input)
        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("Enter feed URL")
        layout.addRow("Feed URL:", self.url_input)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def get_inputs(self):
        return self.name_input.text().strip(), self.url_input.text().strip()

    def accept(self):
        feed_name, feed_url = self.get_inputs()
        if not feed_url:
            self.warn("Input Error", "Feed URL is required.")
            return
        super().accept()

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.api_key_input = QLineEdit(self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setText(self.parent.api_key)
        layout.addRow("OMDb API Key:", self.api_key_input)
        self.api_key_notice = QLabel()
        self.api_key_notice.setStyleSheet("color: red;")
        self.update_api_key_notice()
        layout.addRow("", self.api_key_notice)
        self.refresh_interval_input = QSpinBox(self)
        self.refresh_interval_input.setRange(1, 1440)
        self.refresh_interval_input.setValue(self.parent.refresh_interval)
        layout.addRow("Refresh Interval (minutes):", self.refresh_interval_input)
        self.font_name_combo = QFontComboBox(self)
        self.font_name_combo.setCurrentFont(self.parent.default_font)
        layout.addRow("Font Name:", self.font_name_combo)
        self.font_size_spin = QSpinBox(self)
        self.font_size_spin.setRange(8, 48)
        self.font_size_spin.setValue(self.parent.current_font_size)
        layout.addRow("Font Size:", self.font_size_spin)
        self.global_notifications_checkbox = QCheckBox("Enable Notifications", self)
        settings = QSettings('rocker', 'SmallRSSReader')
        global_notifications = settings.value('notifications_enabled', False, type=bool)
        self.global_notifications_checkbox.setChecked(global_notifications)
        layout.addRow("Global Notifications:", self.global_notifications_checkbox)
        self.tray_icon_checkbox = QCheckBox("Enable Tray Icon", self)
        tray_icon_enabled = settings.value('tray_icon_enabled', True, type=bool)
        self.tray_icon_checkbox.setChecked(tray_icon_enabled)
        layout.addRow("Tray Icon:", self.tray_icon_checkbox)
        # New iCloud backup controls:
        self.icloud_backup_checkbox = QCheckBox("Enable iCloud Backup", self)
        icloud_enabled = settings.value('icloud_backup_enabled', False, type=bool)
        self.icloud_backup_checkbox.setChecked(icloud_enabled)
        layout.addRow("iCloud Backup:", self.icloud_backup_checkbox)
        self.restore_backup_button = QPushButton("Restore from iCloud", self)
        self.restore_backup_button.clicked.connect(self.restore_backup)
        layout.addRow("", self.restore_backup_button)
        # Log level selector
        self.log_level_combo = QComboBox(self)
        self.log_level_combo.addItems(["ERROR", "WARNING", "INFO", "DEBUG"]) 
        current_level = settings.value('log_level', 'INFO')
        if current_level not in ["ERROR", "WARNING", "INFO", "DEBUG"]:
            current_level = 'INFO'
        self.log_level_combo.setCurrentText(current_level)
        layout.addRow("Log level:", self.log_level_combo)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)
        self.max_days_input = QSpinBox(self)
        self.max_days_input.setRange(1, 365)
        self.max_days_input.setValue(self.parent.max_days)
        layout.addRow("Max Days to Keep Articles:", self.max_days_input)

    def update_api_key_notice(self):
        if not self.parent.api_key:
            self.api_key_notice.setText("Ratings feature is disabled without an API key.")
        else:
            self.api_key_notice.setText("")

    def restore_backup(self):
        reply = QMessageBox.question(self, "Restore Backup", 
                                     "Are you sure you want to restore settings and feeds from iCloud? This will overwrite your current data.",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.parent.restore_from_icloud()

    def save_settings(self):
        api_key = self.api_key_input.text().strip()
        refresh_interval = self.refresh_interval_input.value()
        font_name = self.font_name_combo.currentFont().family()
        font_size = self.font_size_spin.value()
        self.parent.api_key = api_key
        self.parent.refresh_interval = refresh_interval
        self.parent.current_font_size = font_size
        self.parent.default_font = QFont(font_name, font_size)
        notifications_enabled = self.global_notifications_checkbox.isChecked()
        tray_icon_enabled = self.tray_icon_checkbox.isChecked()
        icloud_enabled = self.icloud_backup_checkbox.isChecked()
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('omdb_api_key', api_key)
        settings.setValue('refresh_interval', refresh_interval)
        settings.setValue('font_name', font_name)
        settings.setValue('font_size', font_size)
        settings.setValue('notifications_enabled', notifications_enabled)
        settings.setValue('tray_icon_enabled', tray_icon_enabled)
        settings.setValue('icloud_backup_enabled', icloud_enabled)
        self.parent.icloud_backup_enabled = icloud_enabled
        self.parent.update_refresh_timer()
        self.parent.apply_font_size()
        self.update_api_key_notice()
        if tray_icon_enabled:
            if self.parent.tray_icon is None:
                self.parent.init_tray_icon()
            else:
                tray_icon_pixmap = QPixmap(resource_path('icons/rss_tray_icon.png'))
                self.parent.tray_icon.setIcon(QIcon(tray_icon_pixmap))
                self.parent.tray_icon.show()
        else:
            if self.parent.tray_icon is not None:
                transparent_pixmap = QPixmap(1, 1)
                transparent_pixmap.fill(Qt.transparent)
                self.parent.tray_icon.setIcon(QIcon(transparent_pixmap))
                self.parent.tray_icon.hide()
        self.parent.max_days = self.max_days_input.value()
        settings.setValue('max_days', self.parent.max_days)
        self.parent.prune_old_entries()
        self.parent.save_feeds()
        self.parent.load_feeds()
        self.parent.load_articles()
        # Removed backup_to_icloud call here to prevent unnecessary backups during startup.

    def accept(self):
        self.save_settings()
        super().accept()

# =========================
# 3. ОСНОВНОЙ КЛАСС ПРИЛОЖЕНИЯ (ИНТЕРФЕЙС, ЛОГИКА)
# =========================

class PopulateArticlesThread(QThread):
    articles_ready = pyqtSignal(list, dict)  # Emits (entries, article_id_to_item)

    def __init__(self, entries, read_articles, max_days):
        super().__init__()
        self.entries = entries
        self.read_articles = read_articles
        self.max_days = max_days
        # Cooperative stop flag
        self._stop_event = threading.Event()

    def stop(self):
        """Request cooperative stop for this thread."""
        try:
            self._stop_event.set()
        except Exception:
            pass

    def run(self):
        filtered_entries = []
        article_id_to_item = {}
        # Reminder: Do not modify the following line under any circumstances:
        cutoff_date = datetime.now() - timedelta(days=self.max_days)

        for entry in self.entries:
            # Allow cooperative cancellation between items
            if self._stop_event.is_set():
                break
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                entry_date = datetime(*date_struct[:6])
                entry['formatted_date'] = format_date_column(entry_date)
                if entry_date >= cutoff_date:
                    filtered_entries.append(entry)
            else:
                filtered_entries.append(entry)

            article_id = hashlib.md5(
                (entry.get('id') or entry.get('guid') or entry.get('link') or (entry.get('title', '') + entry.get('published', ''))).encode('utf-8')
            ).hexdigest()
            article_id_to_item[article_id] = entry

        self.articles_ready.emit(filtered_entries, article_id_to_item)

class RSSReader(QMainWindow):
    REFRESH_SELECTED_ICON = QStyle.SP_BrowserReload
    REFRESH_ALL_ICON = QStyle.SP_DialogResetButton
    notify_signal = pyqtSignal(str, str, str, str)  # title, subtitle, message, link
    icon_fetched = pyqtSignal(str, bytes)  # domain, icon bytes
    # Emitted when favicon fetch fails; used to clear in-flight guards so we can retry later
    icon_fetch_failed = pyqtSignal(str)  # domain

    def initialize_variables(self):
        """Initialize instance variables and timers used across the app."""
        # Lifecycle and threading
        self.is_quitting = False
        self.is_shutting_down = False
        self._shutdown_in_progress = False
        self._shutdown_done = False
        self.threads = []
        self.thread_pool = QThreadPool.globalInstance()
        # Hold references to threads being stopped to avoid premature GC
        self._stale_threads = []
        # Timers
        self.auto_refresh_timer = QTimer(self)
        self.icon_rotation_timer = QTimer(self)
        self.icon_rotation_timer.timeout.connect(self.rotate_refresh_icon)
        # Flags
        self.is_refreshing = False
        self.refresh_icon_angle = 0
        # Guard for UI population to debounce clicks during startup/refresh
        self.is_populating_articles = False
        # Track domains with an in-flight favicon fetch to avoid duplicates
        self._favicon_fetching = set()

        # Debounce for feed selection to avoid thrashing loaders/threads
        self.selection_debounce = QTimer(self)
        self.selection_debounce.setSingleShot(True)
        self.selection_debounce.setInterval(250)
        self.selection_debounce.timeout.connect(self.load_articles)

        # Debounce for article selection to avoid re-entrant content loads
        self.article_selection_debounce = QTimer(self)
        self.article_selection_debounce.setSingleShot(True)
        self.article_selection_debounce.setInterval(150)
        self.article_selection_debounce.timeout.connect(self.display_content)

        # Defaults for settings-dependent values used before load_settings
        self.refresh_interval = 60  # minutes
        self.api_key = ''
        self.max_days = 30

        # Fonts
        self.default_font_size = 12
        self.default_font = QFont("Arial", self.default_font_size)
        self.current_font_size = self.default_font_size

        # Data structures
        self.article_id_to_item = {}
        self.group_settings = {}
        self.group_name_mapping = {}
        self.column_widths = {}
        self.movie_data_cache = {}
        self.feeds = []
        self.read_articles = set()
        self.feeds_dirty = False

        # Tray and backup
        self.tray_icon = None
        self.tray_menu = None
        self.quit_flag = threading.Event()
        settings = QSettings('rocker', 'SmallRSSReader')
        self.icloud_backup_enabled = settings.value('icloud_backup_enabled', False, type=bool)

        # Icons and caches
        self.favicon_cache = {}
        self.blue_dot_icon = self.create_blue_dot_icon()
        movie_pix = QPixmap(resource_path('icons/movie_icon.png'))
        if movie_pix.isNull():
            self.movie_icon = QIcon()
        else:
            self.movie_icon = QIcon(movie_pix.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        # Content loading tracking (for timeouts/cleanup)
        self.active_content_loads = {}
        # Disable hover popups on article items
        self.tooltips_enabled = False

        # Track threads with names for robust shutdown
        self.threads = self.threads  # ensure attribute exists

    def register_thread(self, thread: QThread, name: str = ""):
        """Register a QThread for lifecycle management and add lifecycle logs."""
        try:
            if name:
                thread.setObjectName(name)
            thread.started.connect(lambda t=thread: logging.debug(f"QThread started: {t.objectName() or t}") )
            thread.finished.connect(lambda t=thread: logging.debug(f"QThread finished: {t.objectName() or t}"))
        except Exception:
            pass
        self.threads.append(thread)

    def shutdown_threads(self):
        """Stop all running threads and timers safely before app exit."""
        # Idempotent & re-entrant safe
        if getattr(self, '_shutdown_done', False):
            return
        if getattr(self, '_shutdown_in_progress', False):
            logging.info("Shutdown already in progress...")
            return
        self._shutdown_in_progress = True
        self.is_shutting_down = True
        # Stop timers early to avoid new work
        try:
            self.auto_refresh_timer.stop()
        except Exception:
            pass
        try:
            self.icon_rotation_timer.stop()
        except Exception:
            pass
        try:
            self.selection_debounce.stop()
        except Exception:
            pass
        try:
            self.article_selection_debounce.stop()
        except Exception:
            pass
        try:
            getattr(self, 'cleanup_timer', None) and self.cleanup_timer.stop()
        except Exception:
            pass
        logging.info("Shutting down threads...")
        # Stop content fetch watchdogs and threads
        try:
            for aid in list(self.active_content_loads.keys()):
                try:
                    self._on_content_fetch_timeout(aid)
                except Exception:
                    pass
        except Exception:
            pass

        # Stop movie thread cooperatively
        if hasattr(self, 'movie_thread') and isinstance(self.movie_thread, QThread):
            try:
                try:
                    self.movie_thread.movie_data_fetched.disconnect(self.update_movie_info)
                except Exception:
                    pass
                # Prefer cooperative stop if available
                try:
                    if hasattr(self.movie_thread, 'request_stop'):
                        self.movie_thread.request_stop()
                except Exception:
                    pass
                if self.movie_thread.isRunning():
                    self.movie_thread.quit()
                    self.movie_thread.wait()
                self.movie_thread.deleteLater()
            except Exception:
                pass

        # Stop PopulateArticlesThread cooperatively
        if hasattr(self, 'populate_thread') and isinstance(getattr(self, 'populate_thread'), QThread):
            try:
                # Use cooperative stop flag instead of quit()
                try:
                    self.populate_thread.stop()
                except Exception:
                    pass
                if self.populate_thread.isRunning():
                    # Give it a moment to observe the flag
                    if not self.populate_thread.wait(500):
                        self.populate_thread.quit()
                        self.populate_thread.wait()
                self.populate_thread.deleteLater()
                logging.info("PopulateArticlesThread terminated and deleted.")
            except Exception:
                pass

        # Stop any remaining threads that were registered
        try:
            for thread in list(self.threads):
                if isinstance(thread, QThread) and thread.isRunning():
                    logging.warning(f"Thread still running at shutdown: {thread.objectName() or thread}")
                    try:
                        thread.quit()
                        if not thread.wait(500):
                            try:
                                thread.terminate()
                            except Exception:
                                pass
                            thread.wait(500)
                    finally:
                        try:
                            thread.deleteLater()
                        except Exception:
                            pass
                try:
                    self.threads.remove(thread)
                except ValueError:
                    pass
        except Exception:
            pass

        # Ensure QThreadPool tasks are completed
        try:
            self.thread_pool.waitForDone()
        except Exception:
            pass
        logging.info("All threads and tasks shut down.")
        # Mark as done
        self._shutdown_done = True
        self._shutdown_in_progress = False

    # Helpers to avoid modal dialogs in test runs
    def is_test_mode(self):
        try:
            import os
            return bool(os.environ.get("PYTEST_CURRENT_TEST")) or getattr(self, "suppress_modals", False)
        except Exception:
            return getattr(self, "suppress_modals", False)

    def warn(self, title: str, message: str):
        logging.warning(f"{title}: {message}")
        if self.is_test_mode():
            try:
                self.statusBar().showMessage(message, 3000)
            except Exception:
                pass
            return
        QMessageBox.warning(self, title, message)

    def __init__(self):
        super().__init__()
        # Headless mode for tests (no WebEngine/tray, no modals)
        self.headless = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        if self.headless:
            self.suppress_modals = True
        self.data_changed = False  # Track if data has been modified
        self.feed_cache = {}  # Cache for feed data with timestamps
        self.cache_expiry = timedelta(minutes=5)
        self.setWindowTitle("Small RSS Reader")
        self.resize(1200, 800)
        # Initialize SQLite storage and migrate legacy JSON, if any
        try:
            db_path = get_user_data_path('db.sqlite3')
            self.storage = Storage(db_path)
            # user data dir is the folder containing db.sqlite3
            data_dir = os.path.dirname(db_path)
            self.storage.migrate_from_json_if_needed(data_dir)
        except Exception as e:
            logging.warning(f"Storage initialization failed, falling back to JSON: {e}")
            self.storage = None
        self.initialize_variables()
        self.init_ui()
        self.load_group_names()
        # Centralized startup: load settings (which loads feeds, read articles, tray, timers)
        self.load_settings()
        self.notify_signal.connect(self.show_notification)
        # Ensure orderly shutdown on app quit
        try:
            QApplication.instance().aboutToQuit.connect(self.shutdown_threads)
        except Exception:
            pass
        # Connect favicon signal
        try:
            self.icon_fetched.connect(self.on_icon_fetched)
            # Ensure we clear in-flight guards on failure to allow retry
            self.icon_fetch_failed.connect(lambda d: self._favicon_fetching.discard(d))
        except Exception:
            pass

    def mark_feeds_dirty(self):
        self.feeds_dirty = True

    def prune_old_entries(self):
        cutoff_date = datetime.now() - timedelta(days=self.max_days)
        feeds_updated = False
        for feed in self.feeds:
            original_count = len(feed.get('entries', []))
            feed['entries'] = [entry for entry in feed.get('entries', []) if self.get_entry_date(entry) >= cutoff_date]
            pruned_count = original_count - len(feed['entries'])
            if pruned_count > 0:
                logging.info(f"Pruned {pruned_count} old articles from feed '{feed['title']}'.")
                feeds_updated = True
        if feeds_updated:
            self.mark_feeds_dirty()
        # После удаления старых статей чистим связанные данные
        self.cleanup_orphaned_data()

    def perform_periodic_cleanup(self):
        logging.info("Performing periodic cleanup of old articles.")
        self.prune_old_entries()
        self.statusBar().showMessage("Periodic cleanup completed.")
        # После prune_old_entries cleanup_orphaned_data вызовется автоматически

    def add_feed(self, feed_name, feed_url):
        if not feed_url:
            self.statusBar().showMessage("Feed URL is required.", 5000)
            return
        if not feed_url.startswith(('http://', 'https://')):
            feed_url = 'http://' + feed_url
        if feed_url in [feed['url'] for feed in self.feeds]:
            self.statusBar().showMessage("This feed URL is already added.", 5000)
            return
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
        except Exception as e:
            self.statusBar().showMessage(f"Failed to load feed: {e}", 5000)
            logging.error(f"Failed to load feed {feed_url}: {e}")
            return
        if not feed_name:
            feed_name = feed.feed.get('title', feed_url)
        if feed_name in [feed['title'] for feed in self.feeds]:
            self.statusBar().showMessage("A feed with this name already exists.", 5000)
            return
        self.create_feed_data(feed_name, feed_url, feed)
        self.statusBar().showMessage(f"Added feed: {feed_name}", 5000)
        logging.info(f"Added new feed: {feed_name} ({feed_url})")
        self.prune_old_entries()
        self.mark_feeds_dirty()
        self.save_feeds()
        self.load_feeds()

    def remove_feed(self, item=None):
        # Allow calling from context menu with the clicked item or fallback to current selection
        if item is None:
            selected_items = self.feeds_list.selectedItems()
            if not selected_items:
                self.statusBar().showMessage("Please select a feed to remove.", 5000)
                return
            item = selected_items[0]
        if item.data(0, Qt.UserRole) is None:
            self.statusBar().showMessage("Please select a feed, not a group.", 5000)
            return
        feed_url = item.data(0, Qt.UserRole)
        feed_data = next((f for f in self.feeds if f['url'] == feed_url), None)
        if not feed_data:
            self.statusBar().showMessage("Feed data not found.", 5000)
            return
    # Skip modal in tests/headless
        if not self.is_test_mode():
            reply = QMessageBox.question(self, "Remove Feed",
                                         f"Are you sure you want to remove '{feed_data['title']}'?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
    # Remove feed and associated read markers
        self.feeds = [f for f in self.feeds if f['url'] != feed_url]
        try:
            # Remove entries and feed from storage if available
            if getattr(self, 'storage', None):
                try:
                    # Remove the feed and cascade delete entries
                    self.storage.remove_feed(feed_url)
                except Exception:
                    pass
        except Exception:
            pass
        # Remove read markers for this feed's articles
        try:
            to_remove = []
            for entry in feed_data.get('entries', []):
                aid = self.get_article_id(entry)
                if aid in self.read_articles:
                    to_remove.append(aid)
            for aid in to_remove:
                self.read_articles.discard(aid)
        except Exception:
            pass
        self.save_feeds()
        self.load_feeds()
        # Select the first available feed after deletion
        try:
            self.select_first_feed()
        except Exception:
            pass
        self.statusBar().showMessage(f"Removed feed: {feed_data['title']}", 5000)

    def create_blue_dot_icon(self):
        """Create a reusable blue dot icon."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(0, 0, 255))  # Blue color
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 8, 8)
        painter.end()
        return QIcon(pixmap)

    def quit_app(self):
        self.is_quitting = True
        self.is_shutting_down = True
        self.quit_flag.set()
        self.statusBar().showMessage("Saving your data before exiting...", 5000)
        # Centralized, robust shutdown
        self.shutdown_threads()
        # Explicitly delete QWebEngineView to ensure cleanup
        try:
            if hasattr(self, 'content_view') and not getattr(self, '_view_deleted', False):
                self.content_view.deleteLater()
                self._view_deleted = True
                logging.info("Deleted QWebEngineView to ensure proper cleanup.")
        except Exception:
            pass
        self.close()

    def save_font_size(self):
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('font_size', self.current_font_size)

    def apply_font_size(self):
        font = QFont(self.default_font.family(), self.current_font_size)
        try:
            self.articles_tree.setFont(font)
        except Exception:
            pass
        try:
            self.content_view.setFont(font)
        except Exception:
            pass
        try:
            self.feeds_list.setFont(font)
        except Exception:
            pass
        self.statusBar().showMessage(f"Font: {font.family()}, Size: {font.pointSize()}")

    def increase_font_size(self):
        if self.current_font_size < 30:
            self.current_font_size += 1
            self.apply_font_size()
            self.save_font_size()
            logging.info(f"Increased font size to {self.current_font_size}.")

    def decrease_font_size(self):
        if self.current_font_size > 8:
            self.current_font_size -= 1
            self.apply_font_size()
            self.save_font_size()
            logging.info(f"Decreased font size to {self.current_font_size}.")

    def reset_font_size(self):
        self.current_font_size = self.default_font_size
        self.apply_font_size()
        self.save_font_size()
        logging.info(f"Reset font size to default ({self.default_font_size}).")

    def show_notification(self, title, subtitle, message, link):
        full_message = f"{subtitle}\n\n{message}" if subtitle else message
        try:
            if self.tray_icon and QSystemTrayIcon.isSystemTrayAvailable():
                self.tray_icon.showMessage(title, full_message, QSystemTrayIcon.Information, 5000)
        except Exception:
            pass

    def send_notification(self, feed_title, entry):
        group_name = self.get_group_name_for_feed(entry.get('link', ''))
        group_settings = self.group_settings.get(group_name, {'notifications_enabled': False})
        notifications_enabled = group_settings.get('notifications_enabled', False)
        settings = QSettings('rocker', 'SmallRSSReader')
        global_notifications = settings.value('notifications_enabled', False, type=bool)

        # Log only once per feed
        if not hasattr(self, '_logged_notifications'):
            self._logged_notifications = set()

        if feed_title not in self._logged_notifications:
            logging.debug(f"Notification for feed '{feed_title}' is {'enabled' if notifications_enabled else 'disabled'}.")
            self._logged_notifications.add(feed_title)

        # Avoid sending notifications for every article in the feed
        if global_notifications and notifications_enabled:
            if not hasattr(self, '_notified_articles'):
                self._notified_articles = set()

            article_id = entry.get('id') or entry.get('link')
            if article_id in self._notified_articles:
                return  # Skip if notification for this article was already sent

            self._notified_articles.add(article_id)

            title = f"New Article in {feed_title}"
            subtitle = entry.get('title', 'No Title')
            message = entry.get('summary', 'No summary available.')
            link = entry.get('link', '')
            self.notify_signal.emit(title, subtitle, message, link)
            logging.info(f"Sent notification for new article: {entry.get('title', 'No Title')}")

    def init_ui(self):
        self.setup_central_widget()
        self.init_menu()
        self.init_toolbar()
        self.statusBar().showMessage("Ready")
    # Timer will be configured after settings load

    def setup_central_widget(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setHandleWidth(1)
        self.main_splitter.setStyleSheet("QSplitter::handle { background-color: #ccc; width: 1px; }")
        main_layout.addWidget(self.main_splitter)

        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        self.horizontal_splitter.setHandleWidth(1)
        self.horizontal_splitter.setStyleSheet("QSplitter::handle { background-color: #ccc; width: 1px; }")
        self.main_splitter.addWidget(self.horizontal_splitter)

        self.init_feeds_panel()
        self.init_articles_panel()
        self.init_content_panel()

        self.horizontal_splitter.setStretchFactor(0, 1)
        self.horizontal_splitter.setStretchFactor(1, 3)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)

    def init_feeds_panel(self):
        self.feeds_panel = QWidget()
        feeds_layout = QVBoxLayout(self.feeds_panel)
        feeds_layout.setContentsMargins(2, 2, 2, 2)
        feeds_layout.setSpacing(2)
        feeds_label = QLabel("RSS Feeds")
        feeds_label.setFont(QFont("Arial", 12))
        feeds_layout.addWidget(feeds_label)
        self.feeds_list = FeedsTreeWidget()
        self.feeds_list.setHeaderHidden(True)
        self.feeds_list.setIndentation(10)
        self.feeds_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.feeds_list.itemSelectionChanged.connect(self.on_feed_selection_changed)
        self.feeds_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.feeds_list.customContextMenuRequested.connect(self.feeds_context_menu)
        self.feeds_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.feeds_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.feeds_list.itemClicked.connect(self.on_feed_item_clicked)
        self.feeds_list.setIconSize(QSize(32, 32))
        feeds_layout.addWidget(self.feeds_list)
        self.feeds_panel.setMinimumWidth(200)
        self.feeds_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.horizontal_splitter.addWidget(self.feeds_panel)

        # Set favicons for each feed
        for feed in self.feeds:
            feed_item = QTreeWidgetItem(self.feeds_list)
            feed_item.setText(0, feed['title'])
            feed_item.setData(0, Qt.UserRole, feed['url'])
            if self.has_unread_articles(feed):
                self.set_feed_icon(feed_item, feed['url'])

    def on_feed_item_clicked(self, item, column):
        logging.debug(f"on_feed_item_clicked: text='{item.text(0)}', has_url={bool(item.data(0, Qt.UserRole))}")
        if (item.data(0, Qt.UserRole) is None):
            self.handle_group_selection(item)
        else:
            # Let debounced selection handler trigger loading to avoid double-calls
            try:
                self.feeds_list.setCurrentItem(item)
                self.selection_debounce.start()
            except Exception:
                self.handle_feed_selection(item)

    def init_articles_panel(self):
        self.articles_panel = QWidget()
        articles_layout = QVBoxLayout(self.articles_panel)
        articles_layout.setContentsMargins(2, 2, 2, 2)
        articles_layout.setSpacing(2)
        self.articles_tree = QTreeWidget()
        self.articles_tree.setHeaderLabels(['Title', 'Date'])  # Default columns
        # Simplified logic to always show all columns
        all_columns = ['Title', 'Date', 'Rating', 'Released', 'Genre', 'Director', 'Country', 'Actors', 'Poster']
        self.articles_tree.setHeaderLabels(all_columns)
        
        self.articles_tree.setColumnWidth(0, 200)
        self.articles_tree.setColumnWidth(1, 100)
        self.articles_tree.setColumnWidth(2, 80)
        self.articles_tree.setColumnWidth(3, 100)
        self.articles_tree.setColumnWidth(4, 100)
        self.articles_tree.setColumnWidth(5, 150)
        self.articles_tree.setColumnWidth(6, 100)
        self.articles_tree.setColumnWidth(7, 150)
        self.articles_tree.setColumnWidth(8, 120)
        self.articles_tree.setSortingEnabled(True)
        self.articles_tree.header().setSectionsClickable(True)
        self.articles_tree.header().setSortIndicatorShown(True)
        self.articles_tree.itemSelectionChanged.connect(self.display_content)
        self.articles_tree.itemClicked.connect(self.display_content)
        self.articles_tree.itemActivated.connect(self.display_content)
        # Modified double-click behavior: open URL in browser without switching focus away.
        self.articles_tree.itemDoubleClicked.connect(self.open_article_url)
        self.articles_tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.articles_tree.header().customContextMenuRequested.connect(self.show_header_menu)
        articles_layout.addWidget(self.articles_tree)
        self.horizontal_splitter.addWidget(self.articles_panel)
        self.articles_tree.setMouseTracking(False)
        self.articles_tree.setToolTipDuration(0)

    def init_content_panel(self):
        self.content_panel = QWidget()
        content_layout = QVBoxLayout(self.content_panel)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(2)
        if self.headless:
            # Lightweight placeholder widget in tests
            self.content_view = QWidget()
        else:
            self.content_view = QWebEngineView()
            # Safer defaults for content rendering
            self.content_view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            self.content_view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
            self.content_view.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
            self.content_view.settings().setAttribute(QWebEngineSettings.PluginsEnabled, False)
            self.content_view.setPage(WebEnginePage(self.content_view))
        content_layout.addWidget(self.content_view)
        self.main_splitter.addWidget(self.content_panel)

    def set_feed_new_icon(self, url, has_new):
        def update_icon(item):
            if item.data(0, Qt.UserRole) == url:
                if has_new:
                    self.set_feed_icon(item, url)  # Устанавливаем фавикон вместо синего кружка
                else:
                    # Не сбрасываем иконку: фавикон должен оставаться всегда
                    pass
                return True
            return False

        for i in range(self.feeds_list.topLevelItemCount()):
            top_item = self.feeds_list.topLevelItem(i)
            if top_item.data(0, Qt.UserRole):
                if update_icon(top_item):
                    self.set_feed_icon(top_item, top_item.data(0, Qt.UserRole))
                    return

    def set_feed_icon(self, item, url):
        """Set the favicon for a feed or group."""
        try:
            domain = urlparse(url).netloc
        except Exception:
            domain = url
        # In-memory cache by domain (with variants)
        for d in _domain_variants(domain):
            if d in self.favicon_cache:
                logging.debug(f"favicon cache hit: {d}")
                item.setIcon(0, self.favicon_cache[d])
                return
        # Storage cache (try variants)
        try:
            if getattr(self, 'storage', None):
                for d in _domain_variants(domain):
                    data = self.storage.get_icon(d)
                    if data:
                        pm = QPixmap()
                        if pm.loadFromData(data):
                            pm = pm.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            icon = QIcon(pm)
                            self.favicon_cache[d] = icon
                            logging.debug(f"favicon storage hit: {d}")
                            item.setIcon(0, icon)
                            return
        except Exception:
            pass
        # Set a neutral placeholder while real favicon is being fetched
        self.favicon_cache.setdefault(domain, QIcon())
        try:
            item.setIcon(0, self.favicon_cache[domain])
        except Exception:
            pass
        # In headless/test mode, do not perform any network fetch to avoid hangs
        try:
            if getattr(self, 'headless', False) or os.environ.get('PYTEST_CURRENT_TEST'):
                # Use placeholder (empty) icon; it can be updated later in real runs
                try:
                    item.setIcon(0, self.favicon_cache.get(domain, QIcon()))
                except Exception:
                    pass
                return
        except Exception:
            pass
        try:
            if domain not in self._favicon_fetching:
                self._favicon_fetching.add(domain)
                logging.debug(f"favicon fetch start: {domain}")
                self.thread_pool.start(FaviconFetchRunnable(domain, self))
            else:
                logging.debug(f"favicon in-flight, skip: {domain}")
        except Exception:
            logging.debug("Failed to start favicon fetch thread", exc_info=True)

    def init_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("File")
        self.add_file_menu_actions(file_menu)
        view_menu = menu.addMenu("View")
        self.add_view_menu_actions(view_menu)
        font_size_menu = view_menu.addMenu("Font Size")
        increase_font_action = QAction("Increase Font Size", self)
        increase_font_action.setShortcut("Cmd++" if sys.platform == 'darwin' else "Ctrl++")
        increase_font_action.triggered.connect(self.increase_font_size)
        font_size_menu.addAction(increase_font_action)
        decrease_font_action = QAction("Decrease Font Size", self)
        decrease_font_action.setShortcut("Cmd+-" if sys.platform == 'darwin' else "Ctrl+-")
        decrease_font_action.triggered.connect(self.decrease_font_size)
        font_size_menu.addAction(decrease_font_action)
        reset_font_action = QAction("Reset Font Size", self)
        reset_font_action.setShortcut("Cmd+0" if sys.platform == 'darwin' else "Ctrl+0")
        reset_font_action.triggered.connect(self.reset_font_size)
        font_size_menu.addAction(reset_font_action)
        # Help menu with app information
        help_menu = menu.addMenu("Help")
        # Visible in Help menu
        info_action = QAction("App Info…", self)
        info_action.setMenuRole(QAction.NoRole)
        info_action.triggered.connect(self.show_help_info)
        help_menu.addAction(info_action)
        # About action (moved to Application menu on macOS automatically)
        about_action = QAction("About Small RSS Reader", self)
        about_action.setMenuRole(QAction.AboutRole)
        about_action.triggered.connect(self.show_help_info)
        help_menu.addAction(about_action)

    def _git_command(self, args):
        """Run a git command in the repository directory if available."""
        try:
            # Determine probable repo root: in dev __file__ dir; in packaged, no .git
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            # Fast-exit if no .git nearby
            if not os.path.isdir(os.path.join(repo_dir, '.git')):
                return None
            result = subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            return None
        return None

    def get_version_string(self) -> str:
        """Best-effort version string based on tag and commit.
        Priority:
        1) Build-time injected APP_VERSION or TAG+COMMIT.
        2) git describe (dev only). 3) Info.plist (packaged). 4) commit only. 5) 'unknown'.
        """
        # Prefer build-time injected values
        if APP_VERSION:
            return APP_VERSION
        if APP_TAG and APP_COMMIT:
            return f"{APP_TAG} ({APP_COMMIT})"
        if APP_COMMIT:
            return APP_COMMIT
        describe = self._git_command(["describe", "--tags", "--dirty", "--always"]) or ""
        if describe:
            return describe
        # Try separate tag and commit
        tag = self._git_command(["describe", "--tags", "--abbrev=0"]) or ""
        commit = self._git_command(["rev-parse", "--short", "HEAD"]) or ""
        if tag and commit:
            return f"{tag} ({commit})"
        if commit:
            return commit
        # Try reading Info.plist if running from a macOS app bundle
        try:
            if getattr(sys, 'frozen', False) and sys.platform == 'darwin':
                app_exe = sys.executable
                contents = os.path.abspath(os.path.join(app_exe, '..', '..'))
                info_plist = os.path.join(contents, 'Info.plist')
                if os.path.exists(info_plist):
                    with open(info_plist, 'rb') as f:
                        info = plistlib.load(f)
                    ver = info.get('CFBundleShortVersionString') or info.get('CFBundleVersion')
                    if ver:
                        return str(ver)
        except Exception:
            pass
        return "unknown"

    def get_remote_repo_url(self) -> str:
        """Return remote 'origin' URL from git if available, else fallback constant."""
        # Prefer build-time injected ORIGIN
        if APP_ORIGIN:
            return APP_ORIGIN
        url = self._git_command(["remote", "get-url", "origin"]) or ""
        if url:
            return url
        return REMOTE_REPO_FALLBACK

    def show_help_info(self):
        """Show a compact dialog with version, log/db paths, and remote repo URL."""
        log_path = get_user_data_path('rss_reader.log')
        db_path = get_user_data_path('db.sqlite3')
        version = self.get_version_string()
        remote = self.get_remote_repo_url()
        msg = (
            f"Version: {version}\n\n"
            f"Log file: {log_path}\n"
            f"SQLite DB: {db_path}\n"
            f"Remote repo: {remote}"
        )
        logging.info(f"Help Info: {msg.replace(os.path.expanduser('~'), '~')}")
        if self.is_test_mode():
            # In tests, avoid modal dialogs
            try:
                self.statusBar().showMessage(f"Version: {version}", 5000)
            except Exception:
                pass
            return
        try:
            QMessageBox.information(self, "Small RSS Reader — Info", msg)
        except Exception:
            try:
                self.statusBar().showMessage(f"Version: {version}", 5000)
            except Exception:
                pass

    def open_article_url(self, item, column):
        entry = item.data(0, Qt.UserRole)
        if not entry:
            self.statusBar().showMessage("No data available for the selected article.", 5000)
            return
        url = entry.get('link', '')
        if not url:
            self.statusBar().showMessage("No URL found for the selected article.", 5000)
            return
        parsed_url = urlparse(url)
        if not parsed_url.scheme.startswith('http'):
            self.statusBar().showMessage("The URL is invalid or unsupported.", 5000)
            return
        QDesktopServices.openUrl(QUrl(url))
        QTimer.singleShot(100, self.activateWindow)

    def add_file_menu_actions(self, file_menu):
        import_action = QAction("Import Feeds", self)
        import_action.triggered.connect(self.import_feeds)
        file_menu.addAction(import_action)
        export_action = QAction("Export Feeds", self)
        export_action.triggered.connect(self.export_feeds)
        file_menu.addAction(export_action)
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)
        exit_action = QAction("Exit", self)
        exit_action.setShortcut('Ctrl+Q' if sys.platform != 'darwin' else 'Cmd+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def add_view_menu_actions(self, view_menu):
        self.toggle_toolbar_action = QAction("Show Toolbar", self)
        self.toggle_toolbar_action.setCheckable(True)
        self.toggle_toolbar_action.setChecked(True)
        self.toggle_toolbar_action.triggered.connect(self.toggle_toolbar_visibility)
        view_menu.addAction(self.toggle_toolbar_action)
        self.toggle_statusbar_action = QAction("Show Status Bar", self)
        self.toggle_statusbar_action.setCheckable(True)
        self.toggle_statusbar_action.setChecked(True)
        self.toggle_statusbar_action.triggered.connect(self.toggle_statusbar_visibility)
        view_menu.addAction(self.toggle_statusbar_action)
        self.toggle_menubar_action = QAction("Show Menu Bar", self)
        self.toggle_menubar_action.setCheckable(True)
        self.toggle_menubar_action.setChecked(True)
        self.toggle_menubar_action.triggered.connect(self.toggle_menubar_visibility)
        view_menu.addAction(self.toggle_menubar_action)
        toggle_columns_action = QAction("Select Columns", self)
        toggle_columns_action.triggered.connect(self.select_columns_dialog)
        view_menu.addAction(toggle_columns_action)

    def select_columns_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Columns")
        layout = QVBoxLayout(dialog)

        checkboxes = []
        for i, column_name in enumerate(['Title', 'Date', 'Rating', 'Released', 'Genre', 'Director', 'Country', 'Actors', 'Poster']):
            checkbox = QCheckBox(column_name, dialog)
            checkbox.setChecked(self.articles_tree.headerItem().isHidden(i) == False)
            layout.addWidget(checkbox)
            checkboxes.append((i, checkbox))

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            for i, checkbox in checkboxes:
                self.articles_tree.setColumnHidden(i, not checkbox.isChecked())

    def init_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setObjectName("MainToolbar")
        self.toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(self.toolbar)
        self.add_toolbar_buttons()
        self.toolbar.setVisible(True)

    def on_feed_selection_changed(self):
        # Ignore while signals are blocked (during list rebuild)
        if getattr(self.feeds_list, 'signalsBlocked', lambda: False)():
            logging.debug("on_feed_selection_changed: signals blocked, ignoring")
            return
        # Restart debounce timer
        logging.debug("on_feed_selection_changed: starting debounce timer")
        self.selection_debounce.start()

    def add_toolbar_buttons(self):
        self.add_new_feed_button()
        self.add_refresh_buttons()
        self.add_mark_unread_button()
        self.add_mark_feed_read_button()
        # Add unread checkbox first
        self.add_show_unread_checkbox()
        # Add a toolbar separator
        self.toolbar.addSeparator()
        # Then add search widget
        self.add_search_widget()

    def add_mark_feed_read_button(self):
        mark_read_icon = self.style().standardIcon(QStyle.SP_DialogApplyButton)
        mark_read_action = QAction(mark_read_icon, "Mark Feed as Read", self)
        mark_read_action.triggered.connect(self.mark_feed_as_read)
        self.toolbar.addAction(mark_read_action)

    def add_new_feed_button(self):
        new_feed_icon = self.style().standardIcon(QStyle.SP_FileDialogNewFolder)
        self.new_feed_button = QPushButton("New Feed")
        self.new_feed_button.setIcon(new_feed_icon)
        self.new_feed_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 5px 10px;
                text-align: center;
                font-size: 14px;
                margin: 2px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.new_feed_button.clicked.connect(self.open_add_feed_dialog)
        self.toolbar.addWidget(self.new_feed_button)

    def add_refresh_buttons(self):
        refresh_selected_icon = self.style().standardIcon(self.REFRESH_SELECTED_ICON)
        refresh_action = QAction(refresh_selected_icon, "Refresh Selected Feed", self)
        refresh_action.triggered.connect(self.refresh_feed)
        self.toolbar.addAction(refresh_action)
        force_refresh_icon = self.style().standardIcon(self.REFRESH_ALL_ICON)
        self.force_refresh_action = QAction(force_refresh_icon, "Refresh All Feeds", self)
        self.force_refresh_action.triggered.connect(self.force_refresh_all_feeds)
        self.toolbar.addAction(self.force_refresh_action)
        self.force_refresh_icon_pixmap = force_refresh_icon.pixmap(24, 24)

    def add_mark_unread_button(self):
        mark_unread_icon = self.style().standardIcon(QStyle.SP_DialogCancelButton)
        mark_unread_action = QAction(mark_unread_icon, "Mark Feed Unread", self)
        mark_unread_action.triggered.connect(self.mark_feed_unread)
        self.toolbar.addAction(mark_unread_action)

    def add_search_widget(self):
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search articles...")
        self.search_input.setFixedWidth(200)  # Reduced width
        self.search_input.setClearButtonEnabled(True)
        self.search_input.installEventFilter(self)
        self.search_input.textChanged.connect(self.filter_articles)
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addStretch()
        search_widget = QWidget()
        search_widget.setLayout(search_layout)
        self.toolbar.addWidget(search_widget)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar.addWidget(spacer)

    def add_show_unread_checkbox(self):
        # Add a checkbox to show only unread articles
        self.show_unread_checkbox = QCheckBox("Show only unread", self.toolbar)
        settings = QSettings('rocker', 'SmallRSSReader')
        checked = settings.value('show_only_unread', False, type=bool)
        self.show_unread_checkbox.setChecked(checked)
        self.show_unread_checkbox.stateChanged.connect(self.on_show_unread_changed)
        self.toolbar.addWidget(self.show_unread_checkbox)

    def on_show_unread_changed(self, state):
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('show_only_unread', bool(state))
        self.populate_articles_ui()

    def get_show_only_unread(self):
        # Helper to get the current state
        settings = QSettings('rocker', 'SmallRSSReader')
        return settings.value('show_only_unread', False, type=bool)

    def eventFilter(self, source, event):
        if source == self.search_input:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.search_input.clear()
                return True
        return super().eventFilter(source, event)

    def update_refresh_timer(self):
        if self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.stop()
        try:
            self.auto_refresh_timer.timeout.disconnect(self.force_refresh_all_feeds)
        except Exception:
            pass
        self.auto_refresh_timer.timeout.connect(self.force_refresh_all_feeds)
        self.auto_refresh_timer.start(self.refresh_interval * 60 * 1000)
        logging.info(f"Refresh timer set to {self.refresh_interval} minutes.")

    def load_settings(self):
        settings = QSettings('rocker', 'SmallRSSReader')
        self.restore_geometry_and_state(settings)
        self.load_api_key_and_refresh_interval(settings)
        self.load_ui_visibility_settings(settings)
        # Load persisted font settings before applying them
        self.load_font_settings(settings)
        self.load_movie_data_cache()
        self.load_group_settings(settings)
        self.load_read_articles()
        self.load_feeds()
        self.apply_font_size()
        self.tray_icon_enabled = settings.value('tray_icon_enabled', True, type=bool)
        if not self.headless:
            self.init_tray_icon()
            QTimer.singleShot(1000, self.force_refresh_all_feeds)
        self.select_first_feed()

    def load_font_settings(self, settings: QSettings):
        """Load and clamp font settings from QSettings."""
        try:
            font_name = settings.value('font_name', self.default_font.family())
            raw_size = settings.value('font_size', self.current_font_size)
            try:
                font_size = int(raw_size)
            except Exception:
                font_size = self.current_font_size
            if not font_name:
                font_name = self.default_font.family()
            font_size = max(8, min(48, font_size))
            self.default_font = QFont(font_name, font_size)
            self.current_font_size = font_size
            logging.info(f"Loaded font settings: {font_name} {font_size}pt")
        except Exception as e:
            logging.warning(f"Failed to load font settings, using defaults: {e}")

    def has_unread_articles(self, feed_data):
        for entry in feed_data.get('entries', []):
            article_id = self.get_article_id(entry)
            if article_id not in self.read_articles:
                return True
        return False

    def filter_articles_by_max_days(self, entries):
        # Use positional arg to avoid static parser false-positive on keyword
        max_days_ago = datetime.now() - timedelta(self.max_days)
        filtered_entries = []
        for entry in entries:
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                entry_date = datetime(*date_struct[:6])
                if entry_date >= max_days_ago:
                    filtered_entries.append(entry)
            else:
                filtered_entries.append(entry)
        return filtered_entries

    def get_entry_date(self, entry):
        date_struct = entry.get('published_parsed') or entry.get('updated_parsed')
        return datetime(*date_struct[:6]) if date_struct else datetime.min

    def restore_geometry_and_state(self, settings):
        geometry = settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
            logging.debug("Restored window geometry.")
        windowState = settings.value('windowState')
        if windowState:
            self.restoreState(windowState)
            logging.debug("Restored window state.")
        splitterState = settings.value('splitterState')
        if splitterState:
            self.main_splitter.restoreState(splitterState)
            logging.debug("Restored splitter state.")
        headerState = settings.value('articlesTreeHeaderState')
        if headerState:
            self.articles_tree.header().restoreState(headerState)
            logging.debug("Restored articlesTreeHeaderState.")
        header = self.articles_tree.header()
        for i in range(header.count()):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            logging.debug(f"Set column {i} resize mode to Interactive.")

    def load_api_key_and_refresh_interval(self, settings):
        self.api_key = settings.value('omdb_api_key', '')
        try:
            self.refresh_interval = int(settings.value('refresh_interval', 60))
        except ValueError:
            self.refresh_interval = 60
        self.update_refresh_timer()

    def load_ui_visibility_settings(self, settings):
        statusbar_visible = settings.value('statusbar_visible', True, type=bool)
        self.statusBar().setVisible(statusbar_visible)
        self.toggle_statusbar_action.setChecked(statusbar_visible)
        toolbar_visible = settings.value('toolbar_visible', True, type=bool)
        self.toolbar.setVisible(toolbar_visible)
        self.toggle_toolbar_action.setChecked(toolbar_visible)
        menubar_visible = settings.value('menubar_visible', True, type=bool)
        self.menuBar().setVisible(menubar_visible)
        self.toggle_menubar_action.setChecked(menubar_visible)

    def load_movie_data_cache(self):
        try:
            self.movie_data_cache = self.storage.load_movie_cache() if getattr(self, 'storage', None) else {}
            logging.info(f"Loaded movie data cache from SQLite with {len(self.movie_data_cache)} entries.")
        except Exception as e:
            logging.warning(f"Failed to load movie cache from SQLite: {e}")
            self.movie_data_cache = {}

    def load_group_settings(self, settings):
        try:
            self.group_settings = self.storage.load_group_settings() if getattr(self, 'storage', None) else {}
            logging.info(f"Loaded group settings from SQLite: {len(self.group_settings)} groups.")
        except Exception as e:
            logging.warning(f"Failed to load group settings from SQLite: {e}")
            self.group_settings = {}

    def load_read_articles(self):
        try:
            ids = self.storage.load_read_articles() if getattr(self, 'storage', None) else []
            self.read_articles = set(ids)
            logging.info(f"Loaded {len(self.read_articles)} read articles from SQLite.")
        except Exception as e:
            logging.warning(f"Failed to load read articles from SQLite: {e}")
            self.read_articles = set()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            selected_items = self.articles_tree.selectedItems()
            if selected_items:
                item = selected_items[0]
                entry = item.data(0, Qt.UserRole)
                if entry:
                    url = entry.get('link', '')
                    if url:
                        QDesktopServices.openUrl(QUrl(url))
                        self.statusBar().showMessage(f"Opened article: {entry.get('title', 'No Title')}", 5000)
                        QTimer.singleShot(100, self.activateWindow)  # Keep focus on the application
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.is_quitting:
            self.save_feeds()  # Save feeds on exit
            self.save_read_articles()  # Save read articles on exit
            settings = QSettings('rocker', 'SmallRSSReader')
            self.save_geometry_and_state(settings)
            self.save_ui_visibility_settings(settings)
            self.save_movie_data_cache()
            self.save_group_settings()
            self.save_font_size()
            if self.data_changed and self.icloud_backup_enabled:
                self.backup_to_icloud()
            # Centralized, robust shutdown
            self.shutdown_threads()
            # Explicitly delete QWebEngineView to ensure cleanup
            try:
                if hasattr(self, 'content_view'):
                    if not getattr(self, '_view_deleted', False):
                        self.content_view.deleteLater()
                        self._view_deleted = True
                        logging.info("Deleted QWebEngineView to ensure proper cleanup.")
            except Exception:
                pass

            logging.info("All threads and resources terminated.")
            event.accept()
        else:
            event.ignore()
            self.hide()
            logging.info("Application minimized to tray.")

    def mark_feed_as_read(self):
        current_feed = self.get_current_feed()
        if not current_feed:
            self.statusBar().showMessage("Please select a feed to mark as read.", 5000)
            return
        feed_url = current_feed['url']
        feed_entries = current_feed.get('entries', [])
        if not feed_entries:
            self.statusBar().showMessage("The selected feed has no articles.", 5000)
            return
        for entry in feed_entries:
            article_id = self.get_article_id(entry)
            self.read_articles.add(article_id)
        self.populate_articles_ui()
        self.update_feed_bold_status(feed_url)
        self.statusBar().showMessage(f"Marked all articles in '{current_feed['title']}' as read.", 5000)
        logging.info(f"Marked all articles in feed '{current_feed['title']}' as read.")

    def init_tray_icon(self):
        # Idempotent init: reuse existing tray icon if present
        if getattr(self, 'tray_icon', None) is None:
            self.tray_icon = QSystemTrayIcon(self)
        system_tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
        if getattr(self, 'tray_icon_enabled', True) and system_tray_ok:
            tray_icon_pixmap = QPixmap(resource_path('icons/rss_tray_icon.png'))
            self.tray_icon.setIcon(QIcon(tray_icon_pixmap))
            self.tray_icon.setToolTip("Small RSS Reader")
            self.tray_icon.show()
        else:
            transparent_pixmap = QPixmap(1, 1)
            transparent_pixmap.fill(Qt.transparent)
            self.tray_icon.setIcon(QIcon(transparent_pixmap))
            self.tray_icon.hide()
        # Ensure tray_menu exists
        if getattr(self, 'tray_menu', None) is None:
            self.tray_menu = QMenu()
        else:
            self.tray_menu.clear()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show_window)
        self.tray_menu.addAction(show_action)
        refresh_action = QAction("Refresh All Feeds", self)
        refresh_action.triggered.connect(self.force_refresh_all_feeds)
        self.tray_menu.addAction(refresh_action)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.quit_app)
        self.tray_menu.addAction(exit_action)
        try:
            self.tray_icon.activated.disconnect(self.on_tray_icon_activated)
        except Exception:
            pass
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

    def on_tray_icon_activated(self, reason):
        if self.tray_icon is None:
            return
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.saved_geometry = self.saveGeometry()
                self.hide()
                self.tray_icon.showMessage(
                    "Small RSS Reader",
                    "Application minimized to tray.",
                    QSystemTrayIcon.Information,
                    2000
                )
                logging.info("Application hidden to tray.")
            else:
                self.show_window()
                self.raise_()
                self.activateWindow()
                logging.info("Application shown from tray.")
        elif reason == QSystemTrayIcon.Context:
            self.tray_menu.exec_(QCursor.pos())

    def show_window(self):
        if self.isHidden() or not self.isVisible():
            self.show()
            if hasattr(self, 'saved_geometry'):
                self.restoreGeometry(self.saved_geometry)
        self.raise_()
        self.activateWindow()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)

    def save_column_widths(self, logical_index, old_size, new_size):
        current_feed = self.get_current_feed()
        if not current_feed:
            return
        feed_url = current_feed['url']
        if feed_url not in self.column_widths:
            self.column_widths[feed_url] = []
        while len(self.column_widths[feed_url]) <= logical_index:
            self.column_widths[feed_url].append(0)
        self.column_widths[feed_url][logical_index] = new_size
        group_name = self.get_group_name_for_feed(feed_url)
        for feed in self.feeds:
            if self.get_group_name_for_feed(feed['url']) == group_name:
                if feed['url'] not in self.column_widths:
                    self.column_widths[feed['url']] = [100] * self.articles_tree.header().count()
                while len(self.column_widths[feed['url']]) <= logical_index:
                    self.column_widths[feed['url']].append(0)
                self.column_widths[feed['url']][logical_index] = new_size
        self.mark_feeds_dirty()

    def save_geometry_and_state(self, settings):
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.saveState())
        settings.setValue('splitterState', self.main_splitter.saveState())
        settings.setValue('articlesTreeHeaderState', self.articles_tree.header().saveState())
        settings.setValue('refresh_interval', self.refresh_interval)
        settings.setValue('group_name_mapping', json.dumps(self.group_name_mapping))
        logging.debug("Saved geometry and state.")

    def save_ui_visibility_settings(self, settings):
        settings.setValue('statusbar_visible', self.statusBar().isVisible())
        settings.setValue('toolbar_visible', self.toolbar.isVisible())
        settings.setValue('menubar_visible', self.menuBar().isVisible())
        self.data_changed = True  # Mark data as changed

    def save_movie_data_cache(self):
        try:
            if getattr(self, 'storage', None):
                self.storage.save_movie_cache(self.movie_data_cache)
                logging.info("Movie data cache saved to SQLite.")
        except Exception as e:
            logging.warning(f"Failed to save movie cache to SQLite: {e}")

    def save_group_settings(self):
        try:
            if getattr(self, 'storage', None):
                self.storage.save_group_settings(self.group_settings)
                self.data_changed = True
                logging.info("Group settings saved successfully to SQLite.")
        except Exception as e:
            logging.warning(f"Failed to save group settings to SQLite: {e}")

    def save_read_articles(self):
        try:
            if getattr(self, 'storage', None):
                self.storage.save_read_articles(list(self.read_articles))
                self.data_changed = True
                logging.info(f"Saved {len(self.read_articles)} read articles to SQLite.")
        except Exception as e:
            logging.warning(f"Failed to save read articles to SQLite: {e}")

    def save_feeds(self):
        try:
            if getattr(self, 'storage', None):
                # Persist feeds and column widths in SQLite
                # Assuming storage has appropriate upsert/replace methods
                for feed in self.feeds:
                    self.storage.upsert_feed(feed['title'], feed['url'])
                    self.storage.replace_entries(feed['url'], feed.get('entries', []))
                self.storage.save_column_widths(self.column_widths)
                logging.info("Feeds saved successfully to SQLite.")
                self.data_changed = True
                self.statusBar().showMessage("Feeds saved successfully.", 5000)
        except Exception as e:
            logging.error(f"Failed to save feeds to SQLite: {e}")
            self.statusBar().showMessage("Error saving feeds. Check logs for details.", 5000)

    def toggle_toolbar_visibility(self):
        visible = self.toggle_toolbar_action.isChecked()
        self.toolbar.setVisible(visible)

    def toggle_statusbar_visibility(self):
        visible = self.toggle_statusbar_action.isChecked()
        self.statusBar().setVisible(visible)

    def toggle_menubar_visibility(self):
        visible = self.toggle_menubar_action.isChecked()
        self.menuBar().setVisible(visible)

    def rotate_refresh_icon(self):
        if not self.is_refreshing:
            return
        self.refresh_icon_angle = (self.refresh_icon_angle + 30) % 360
        pixmap = self.force_refresh_icon_pixmap
        transform = QTransform().rotate(self.refresh_icon_angle)
        rotated_pixmap = pixmap.transformed(transform, Qt.SmoothTransformation)
        self.force_refresh_action.setIcon(QIcon(rotated_pixmap))

    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.exec_()

    def open_add_feed_dialog(self):
        dialog = AddFeedDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            feed_name, feed_url = dialog.get_inputs()
            self.add_feed(feed_name, feed_url)

    def create_feed_data(self, feed_name, feed_url, feed):
        # New feeds start with OMDb and notifications disabled.
        feed_data = {
            'title': feed_name,
            'url': feed_url,
            'entries': [],
            'sort_column': 1,
            'sort_order': Qt.AscendingOrder,
            'visible_columns': [True] * 6
        }
        self.feeds.append(feed_data)
        parsed_url = urlparse(feed_url)
        domain = parsed_url.netloc or 'Unknown Domain'
        if domain not in self.group_settings:
            self.group_settings[domain] = {'omdb_enabled': False, 'notifications_enabled': False}

    def handle_group_selection(self, group_item):
        self.feeds_list.setCurrentItem(group_item)
        self.statusBar().showMessage(f"Selected group: {group_item.text(0)}")
        logging.info(f"Selected group: {group_item.text(0)}")
        if group_item.childCount() > 0:
            first_feed_item = group_item.child(0)
            self.feeds_list.setCurrentItem(first_feed_item)
            # Trigger debounced load instead of immediate to avoid UI spikes
            try:
                self.selection_debounce.start()
            except Exception:
                self.load_articles()
            logging.debug(f"Auto-selected first feed in group '{group_item.text(0)}'")

    def handle_feed_selection(self, feed_item):
        self.feeds_list.setCurrentItem(feed_item)
        self.load_articles()
        logging.info(f"Selected feed: {feed_item.text(0)}")

    def find_or_create_group(self, group_name, domain):
        for i in range(self.feeds_list.topLevelItemCount()):
            group = self.feeds_list.topLevelItem(i)
            if group.data(0, Qt.UserRole) is None and group.text(0) == group_name:
                return group
        group = QTreeWidgetItem(self.feeds_list)
        group.setText(0, group_name)
        group.setExpanded(False)
        group.setFlags(group.flags() & ~Qt.ItemIsSelectable)
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)
        group_settings = self.group_settings.get(group_name, {'omdb_enabled': False})
        if group_settings.get('omdb_enabled', False):
            group.setIcon(0, self.movie_icon)
        else:
            group.setIcon(0, QIcon())
        return group

    def feeds_context_menu(self, position):
        item = self.feeds_list.itemAt(position)
        if not item:
            return
        if item.data(0, Qt.UserRole) is None:
            self.show_group_context_menu(item, position)
        else:
            self.show_feed_context_menu(item, position)

    def show_group_context_menu(self, group_item, position):
        menu = QMenu()
        rename_group_action = QAction("Rename Group", self)
        rename_group_action.triggered.connect(lambda: self.rename_group(group_item))
        menu.addAction(rename_group_action)
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(lambda: self.group_settings_dialog(group_item))
        menu.addAction(settings_action)
        menu.exec_(self.feeds_list.viewport().mapToGlobal(position))

    def group_settings_dialog(self, group_item):
        group_name = group_item.text(0)
        settings = self.group_settings.get(group_name, {'omdb_enabled': False, 'notifications_enabled': False})
        omdb_enabled = settings.get('omdb_enabled', False)
        notifications_enabled = settings.get('notifications_enabled', False)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Settings for {group_name}")
        layout = QVBoxLayout(dialog)

        omdb_checkbox = QCheckBox("Enable OMDb Feature", dialog)
        omdb_checkbox.setChecked(omdb_enabled)
        layout.addWidget(omdb_checkbox)

        notifications_checkbox = QCheckBox("Enable Notifications", dialog)
        notifications_checkbox.setChecked(notifications_enabled)
        layout.addWidget(notifications_checkbox)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            self.save_group_setting(
                group_name,
                omdb_checkbox.isChecked(),
                notifications_checkbox.isChecked()
            )

    def save_group_setting(self, group_name, omdb_enabled, notifications_enabled):
        self.group_settings[group_name] = {
            'omdb_enabled': omdb_enabled,
            'notifications_enabled': notifications_enabled,
        }
        self.save_group_settings()
        self.statusBar().showMessage(f"Updated settings for group: {group_name}", 5000)
        logging.info(f"Updated settings for group '{group_name}': OMDb {'enabled' if omdb_enabled else 'disabled'}, Notifications {'enabled' if notifications_enabled else 'disabled'}.")
        current_feed = self.get_current_feed()
        if current_feed:
            current_group_name = self.get_group_name_for_feed(current_feed['url'])
            if current_group_name == group_name:
                self.populate_articles_ui()
        for i in range(self.feeds_list.topLevelItemCount()):
            group_item = self.feeds_list.topLevelItem(i)
            if group_item.text(0) == group_name:
                group_item.setIcon(0, self.movie_icon if omdb_enabled else QIcon())
                break

    def get_group_name_for_feed(self, feed_url):
        for i in range(self.feeds_list.topLevelItemCount()):
            top_item = self.feeds_list.topLevelItem(i)
            if top_item.data(0, Qt.UserRole):
                if top_item.data(0, Qt.UserRole) == feed_url:
                    return None
            else:
                for j in range(top_item.childCount()):
                    feed_item = top_item.child(j)
                    if feed_item.data(0, Qt.UserRole) == feed_url:
                        return top_item.text(0)
        return None

    def rename_group(self, group_item):
        current_group_name = group_item.text(0)
        new_group_name, ok = QInputDialog.getText(
            self, "Rename Group", "Enter new group name:", QLineEdit.Normal, current_group_name)
        if ok and new_group_name:
            self.update_group_name(group_item, current_group_name, new_group_name)

    def update_group_name(self, group_item, current_group_name, new_group_name):
        domain = self.get_domain_for_group(current_group_name)
        self.group_name_mapping[domain] = new_group_name
        if current_group_name in self.group_settings:
            self.group_settings[new_group_name] = self.group_settings.pop(current_group_name)
        self.save_group_names()
        self.save_group_settings()
        group_item.setText(0, new_group_name)
        self.statusBar().showMessage(f"Renamed group to: {new_group_name}", 5000)
        logging.info(f"Renamed group '{current_group_name}' to '{new_group_name}'.")

    def get_domain_for_group(self, group_name):
        for domain_key, group_name_value in self.group_name_mapping.items():
            if group_name_value == group_name:
                return domain_key
        return group_name

    def rename_feed(self):
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            self.statusBar().showMessage("Please select a feed to rename.", 5000)
            return
        item = selected_items[0]
        if item.data(0, Qt.UserRole) is None:
            self.statusBar().showMessage("Please select a feed, not a group.", 5000)
            return
        current_name = item.text(0)
        new_name, ok = QInputDialog.getText(
            self, "Rename Feed", "Enter new name:", QLineEdit.Normal, current_name)
        if ok and new_name:
            if new_name in [feed['title'] for feed in self.feeds]:
                self.statusBar().showMessage("A feed with this name already exists.", 5000)
                return
            url = item.data(0, Qt.UserRole)
            feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
            if feed_data:
                feed_data['title'] = new_name
                item.setText(0, new_name)
                self.mark_feeds_dirty()
                self.save_feeds()
                self.statusBar().showMessage(f"Renamed feed to: {new_name}", 5000)
                logging.info(f"Renamed feed '{current_name}' to '{new_name}'.")

    def load_group_names(self):
        settings = QSettings('rocker', 'SmallRSSReader')
        group_mapping = settings.value('group_name_mapping', {})
        if isinstance(group_mapping, str):
            try:
                self.group_name_mapping = json.loads(group_mapping)
            except json.JSONDecodeError:
                self.group_name_mapping = {}
        elif isinstance(group_mapping, dict):
            self.group_name_mapping = group_mapping
        else:
            self.group_name_mapping = {}

    def save_group_names(self):
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('group_name_mapping', json.dumps(self.group_name_mapping))

    def load_feeds(self):
        """Loads feeds from SQLite and sets favicons efficiently. No JSON fallbacks."""
        self.feeds = []
        self.column_widths = {}
        if getattr(self, 'storage', None):
            try:
                self.feeds = self.storage.get_all_feeds()
                try:
                    self.column_widths = self.storage.load_column_widths()
                except Exception:
                    self.column_widths = {}
                logging.info(f"Loaded {len(self.feeds)} feeds from SQLite.")
            except Exception as e:
                logging.error(f"Failed to load feeds from SQLite: {e}")

        # If DB is empty, seed with a couple of defaults and persist to SQLite
        if not self.feeds:
            self.column_widths = {}
            defaults = [
                {
                    'title': 'BBC News',
                    'url': 'http://feeds.bbci.co.uk/news/rss.xml',
                    'entries': [],
                    'sort_column': 1,
                    'sort_order': Qt.AscendingOrder,
                    'visible_columns': [True] * 6
                },
                {
                    'title': 'CNN Top Stories',
                    'url': 'http://rss.cnn.com/rss/edition.rss',
                    'entries': [],
                    'sort_column': 1,
                    'sort_order': Qt.AscendingOrder,
                    'visible_columns': [True] * 6
                }
            ]
            self.feeds = defaults
            try:
                if getattr(self, 'storage', None):
                    for feed in defaults:
                        self.storage.upsert_feed(feed['title'], feed['url'], feed.get('sort_column', 1), feed.get('sort_order', 0))
                    self.storage.save_column_widths(self.column_widths)
                logging.info("Seeded default feeds into SQLite.")
            except Exception as e:
                logging.warning(f"Failed to seed defaults into SQLite: {e}")

        self._rebuild_feeds_tree()

    def _rebuild_feeds_tree(self):
        # Avoid selection change signals while rebuilding the list
        prev_block = self.feeds_list.signalsBlocked()
        self.feeds_list.blockSignals(True)
        self.feeds_list.clear()

        # Group feeds by domain
        domain_feeds = {}
        for feed in self.feeds:
            parsed_url = urlparse(feed['url'])
            domain = parsed_url.netloc or 'Unknown Domain'
            domain_feeds.setdefault(domain, []).append(feed)

        for domain, feeds in domain_feeds.items():
            if len(feeds) == 1:
                # Single feed for this domain — show at root without a group wrapper
                feed_data = feeds[0]
                feed_item = QTreeWidgetItem(self.feeds_list)
                feed_item.setText(0, feed_data['title'])
                feed_item.setData(0, Qt.UserRole, feed_data['url'])
                if self.has_unread_articles(feed_data):
                    font = feed_item.font(0)
                    font.setBold(True)
                    feed_item.setFont(0, font)
                self.set_feed_icon(feed_item, feed_data['url'])
            else:
                # Multiple feeds — create a group node
                group_name = self.group_name_mapping.get(domain, domain)
                group_item = QTreeWidgetItem(self.feeds_list)
                group_item.setText(0, group_name)
                font = group_item.font(0)
                font.setBold(True)
                group_item.setFont(0, font)
                if feeds:
                    self.set_feed_icon(group_item, feeds[0]['url'])
                for feed_data in feeds:
                    feed_item = QTreeWidgetItem(group_item)
                    feed_item.setText(0, feed_data['title'])
                    feed_item.setData(0, Qt.UserRole, feed_data['url'])
                    if self.has_unread_articles(feed_data):
                        font = feed_item.font(0)
                        font.setBold(True)
                        feed_item.setFont(0, font)
                    # Ensure each child feed node also gets an icon
                    self.set_feed_icon(feed_item, feed_data['url'])

        self.feeds_list.expandAll()
        self.feeds_list.blockSignals(prev_block)

    def backup_to_icloud(self):
        backup_folder = os.path.join(Path.home(), "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup")
        os.makedirs(backup_folder, exist_ok=True)
        filename = 'db.sqlite3'
        source = get_user_data_path(filename)
        dest = os.path.join(backup_folder, filename)
        if os.path.exists(source):
            try:
                shutil.copy2(source, dest)
                logging.info("Backed up db.sqlite3 to iCloud.")
            except Exception as e:
                logging.error(f"Failed to backup db.sqlite3: {e}")
        self.statusBar().showMessage("Backup to iCloud completed successfully.", 5000)

    def restore_from_icloud(self):
        backup_folder = os.path.join(Path.home(), "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup")
        filename = 'db.sqlite3'
        backup_file = os.path.join(backup_folder, filename)
        if os.path.exists(backup_file):
            dest = get_user_data_path(filename)
            try:
                shutil.copy2(backup_file, dest)
                logging.info("Restored db.sqlite3 from iCloud.")
            except Exception as e:
                logging.error(f"Failed to restore db.sqlite3: {e}")
        self.load_group_settings(QSettings('rocker', 'SmallRSSReader'))
        self.load_read_articles()
        self.load_feeds()
        self.statusBar().showMessage("Restore from iCloud completed successfully.", 5000)

    def on_icon_fetched(self, domain: str, data: bytes):
        """Handle favicon fetched in the background: cache, persist, and update tree icons for this domain."""
        try:
            # Clear in-flight marker
            try:
                self._favicon_fetching.discard(domain)
            except Exception:
                pass
            if getattr(self, 'storage', None):
                try:
                    # Persist only under the original domain to keep storage canonical
                    self.storage.save_icon(domain, data)
                except Exception:
                    pass
            pm = QPixmap()
            if not pm.loadFromData(data):
                return
            # Scale to 16x16 for consistency
            pm = pm.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon = QIcon(pm)
            for d in _domain_variants(domain):
                self.favicon_cache[d] = icon
            # Update all items for this domain
            for i in range(self.feeds_list.topLevelItemCount()):
                top_item = self.feeds_list.topLevelItem(i)
                # Group node case
                try:
                    if top_item.childCount() > 0:
                        # Group name maps to domain via mapping, so compare icons by first child URL
                        for j in range(top_item.childCount()):
                            child = top_item.child(j)
                            url = child.data(0, Qt.UserRole) or ''
                            if urlparse(url).netloc in _domain_variants(domain):
                                top_item.setIcon(0, icon)
                                child.setIcon(0, icon)
                        continue
                except Exception:
                    pass
                # Single feed node
                url = top_item.data(0, Qt.UserRole) or ''
                try:
                    if url and urlparse(url).netloc in _domain_variants(domain):
                        top_item.setIcon(0, icon)
                except Exception:
                    pass
        except Exception:
            pass

    def save_feeds(self):
        try:
            if getattr(self, 'storage', None):
                # Upsert feeds and replace entries
                for feed in self.feeds or []:
                    title = feed.get('title') or feed.get('url')
                    url = feed.get('url')
                    sort_column = int(feed.get('sort_column', 1))
                    sort_order = int(feed.get('sort_order', 0))
                    self.storage.upsert_feed(title, url, sort_column, sort_order)
                    self.storage.replace_entries(url, feed.get('entries', []))
                # Save column widths
                try:
                    self.storage.save_column_widths(self.column_widths)
                except Exception:
                    pass
                logging.info("Feeds saved successfully to SQLite.")
                self.data_changed = True
                self.statusBar().showMessage("Feeds saved successfully.", 5000)
        except Exception as e:
            logging.error(f"Failed to save feeds to SQLite: {e}")
            self.statusBar().showMessage("Error saving feeds. Check logs for details.", 5000)

    def update_feed_titles(self):
        for feed in self.feeds:
            if feed['title'] == feed['url']:
                try:
                    parsed_feed = feedparser.parse(feed['url'])
                    if parsed_feed.bozo and parsed_feed.bozo_exception:
                        raise parsed_feed.bozo_exception
                    feed_title = parsed_feed.feed.get('title', feed['url'])
                    feed['title'] = feed_title
                    parsed_url = urlparse(feed['url'])
                    domain = parsed_url.netloc or 'Unknown Domain'
                    group_name = self.group_name_mapping.get(domain, domain)
                    group = self.find_or_create_group(group_name, domain)
                    for j in range(group.childCount()):
                        child = group.child(j)
                        if child.data(0, Qt.UserRole) == feed['url']:
                            child.setText(0, feed_title)
                            break
                except Exception as e:
                    logging.error(f"Error updating feed title for {feed['url']}: {e}")
        self.mark_feeds_dirty()

    def load_articles(self):
        logging.debug("load_articles: invoked")
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            logging.debug("load_articles: no selection, enabling UI and exit")
            # Nothing selected; ensure UI is interactive
            try:
                self.is_populating_articles = False
            except Exception:
                pass
            return
        item = selected_items[0]
        logging.debug(f"load_articles: selected item '{item.text(0)}'")
        if item.data(0, Qt.UserRole) is None:
            self.handle_group_selection(item)
            # Group selected; no direct population yet
            try:
                self.is_populating_articles = False
            except Exception:
                pass
            return
        url = item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
        # Begin guarded population for a concrete feed
        try:
            self.is_populating_articles = True
        except Exception:
            pass
        logging.debug(f"load_articles: starting population for url={url}, has_cached_entries={bool(feed_data and feed_data.get('entries'))}")
        # Non-blocking: show a lightweight placeholder instead of disabling UI
        try:
            self.show_articles_loading(f"Loading articles from {item.text(0)}…")
        except Exception:
            pass
        if feed_data and feed_data.get('entries'):
            self.statusBar().showMessage(f"Loading articles from {item.text(0)}", 5000)
            self.populate_articles_in_background(feed_data['entries'])
        else:
            self.statusBar().showMessage(f"Loading articles from {item.text(0)}", 5000)
            worker = Worker()
            worker.feed_fetched.connect(self.on_feed_fetched)
            runnable = FetchFeedRunnable(url, worker)
            self.thread_pool.start(runnable)
            logging.debug(f"Started thread for feed: {url}")

    def populate_articles_in_background(self, entries):
        # Stop and clean up any existing thread
        if hasattr(self, 'populate_thread') and self.populate_thread.isRunning():
            try:
                # Ask it to stop cooperatively
                if hasattr(self.populate_thread, 'stop'):
                    self.populate_thread.stop()
                # Give it a short time to finish
                if not self.populate_thread.wait(500):
                    # Keep reference until finished to avoid destruction while running
                    self._stale_threads.append(self.populate_thread)
                    self.populate_thread.finished.connect(lambda thr=self.populate_thread: self._cleanup_stale_thread(thr))
                logging.info("Previous PopulateArticlesThread termination requested.")
            except Exception:
                pass

        # Start a new thread
        self.populate_thread = PopulateArticlesThread(entries, self.read_articles, self.max_days)
        try:
            self.populate_thread.setObjectName("PopulateArticlesThread")
        except Exception:
            pass
        self.populate_thread.articles_ready.connect(self.on_articles_ready)
        self.populate_thread.start()
        # Register for lifecycle management and logging
        try:
            self.register_thread(self.populate_thread, "PopulateArticlesThread")
        except Exception:
            pass

    def on_articles_ready(self, filtered_entries, article_id_to_item):
        logging.debug(f"on_articles_ready: got {len(filtered_entries)} entries")
        self.current_entries = filtered_entries
        # article_id_to_item from PopulateArticlesThread contains dict entries, not QTreeWidgetItem
        # The correct article_id_to_item mapping will be created in populate_articles_ui()
        self.populate_articles_ui()
        # Done populating from background
        self.is_populating_articles = False

    def show_articles_loading(self, message: str):
        """Show a lightweight placeholder in the articles list without disabling the widget."""
        try:
            prev_block = self.articles_tree.signalsBlocked()
            self.articles_tree.blockSignals(True)
            self.articles_tree.clear()
            placeholder = QTreeWidgetItem(self.articles_tree)
            placeholder.setText(0, message)
            try:
                fnt = placeholder.font(0)
                fnt.setItalic(True)
                placeholder.setFont(0, fnt)
            except Exception:
                pass
            # Mark as placeholder to avoid accidental handling
            placeholder.setData(0, Qt.UserRole + 99, "loading_placeholder")
            # Non-selectable to keep focus behavior natural
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsSelectable)
            self.articles_tree.blockSignals(prev_block)
        except Exception:
            pass

    def populate_articles_ui(self):
        """Populate the articles UI with the current feed's articles."""
        # Start guarded population to avoid signal storms and click races
        self.is_populating_articles = True
        prev_block = self.articles_tree.signalsBlocked()
        logging.debug("populate_articles_ui: start, blocking signals")
        try:
            self.articles_tree.blockSignals(True)
        except Exception:
            pass
        self.articles_tree.clear()
        self.article_id_to_item.clear()  # Clear the mapping to prevent old entries
        current_feed = self.get_current_feed()
        if not current_feed:
            logging.debug("populate_articles_ui: no current feed, restoring UI")
            # Restore state even on early return
            try:
                self.articles_tree.blockSignals(prev_block)
            except Exception:
                pass
            self.is_populating_articles = False
            return

        # Определяем, включен ли OMDb для текущей группы
        group_name = self.get_group_name_for_feed(current_feed['url'])
        group_settings = self.group_settings.get(group_name, {'omdb_enabled': False})
        omdb_enabled = group_settings.get('omdb_enabled', False)

        # Определяем нужные столбцы
        base_columns = ['Title', 'Date']
        omdb_columns = ['Rating', 'Released', 'Genre', 'Director', 'Country', 'Actors', 'Poster']
        if omdb_enabled:
            all_columns = base_columns + omdb_columns
        else:
            all_columns = base_columns
        self.articles_tree.setHeaderLabels(base_columns + omdb_columns)  # всегда полный набор для совместимости
        # Скрываем OMDb-столбцы если не нужно
        for i, col in enumerate(base_columns + omdb_columns):
            self.articles_tree.setColumnHidden(i, (col in omdb_columns and not omdb_enabled))

        show_only_unread = self.get_show_only_unread()
        displayed_entries = []
        for entry in current_feed.get('entries', []):
            article_id = self.get_article_id(entry)
            is_unread = article_id not in self.read_articles
            if show_only_unread and not is_unread:
                continue
            item = QTreeWidgetItem(self.articles_tree)
            item.setText(0, entry.get('title', 'No Title'))
            item.setData(0, Qt.UserRole, entry)
            if is_unread:
                item.setIcon(0, self.blue_dot_icon)
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                date_obj = datetime(*date_struct[:6])
                date_formatted = date_obj.strftime('%Y-%m-%d')
                item.setText(1, date_formatted)
                item.setData(1, Qt.UserRole, date_obj)
            # OMDb поля если есть и если omdb_enabled
            movie_data = entry.get('movie_data', {})
            if omdb_enabled:
                item.setText(2, movie_data.get('imdbrating', ''))
                item.setText(3, movie_data.get('released', ''))
                item.setText(4, movie_data.get('genre', ''))
                item.setText(5, movie_data.get('director', ''))
                item.setText(6, movie_data.get('country', ''))
                item.setText(7, movie_data.get('actors', ''))
                item.setText(8, movie_data.get('poster', ''))
            # Ensure no hover tooltip is shown
            try:
                item.setToolTip(0, "")
            except Exception:
                pass
            # Гарантированно сохраняем QTreeWidgetItem
            self.article_id_to_item[article_id] = item
            displayed_entries.append(entry)
        self.articles_tree.sortItems(1, Qt.DescendingOrder)

        # Restore signals and interactivity
        try:
            self.articles_tree.blockSignals(prev_block)
        except Exception:
            pass
        self.is_populating_articles = False
        logging.debug("populate_articles_ui: done, UI restored")

        # --- OMDb: запуск потока для подгрузки рейтингов ---
        if omdb_enabled and self.api_key:
            # Stop previous movie thread if any
            if hasattr(self, 'movie_thread') and self.movie_thread.isRunning():
                try:
                    try:
                        self.movie_thread.movie_data_fetched.disconnect(self.update_movie_info)
                    except Exception:
                        pass
                    # Request cooperative stop instead of quit() to avoid running thread destruction
                    if hasattr(self.movie_thread, 'request_stop'):
                        self.movie_thread.request_stop()
                    # Wait briefly, then retain reference if still running
                    if not self.movie_thread.wait(500):
                        self._stale_threads.append(self.movie_thread)
                        self.movie_thread.finished.connect(lambda thr=self.movie_thread: self._cleanup_stale_thread(thr))
                except Exception:
                    pass
            if displayed_entries:
                # Ensure current_entries matches displayed items order
                self.current_entries = list(displayed_entries)
                self.movie_thread = FetchMovieDataThread(self.current_entries, self.api_key, self.movie_data_cache, self.quit_flag)
                self.movie_thread.movie_data_fetched.connect(self.update_movie_info)
                self.movie_thread.start()

    def _cleanup_stale_thread(self, thr: QThread):
        """Remove finished thread from stale list and delete it later safely."""
        try:
            if thr in self._stale_threads:
                self._stale_threads.remove(thr)
            thr.deleteLater()
        except Exception:
            pass

    def mark_selected_article_as_read(self):
        """Mark the currently selected article as read."""
        selected_items = self.articles_tree.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        entry = item.data(0, Qt.UserRole)
        if not entry:
            return

        article_id = self.get_article_id(entry)
        if article_id not in self.read_articles:
            self.read_articles.add(article_id)
            item.setIcon(0, QIcon())  # Remove the unread icon

    def display_content(self):
        try:
            if getattr(self, 'is_shutting_down', False) or getattr(self, '_shutdown_in_progress', False):
                logging.debug("display_content: skipped due to shutdown in progress")
                return
            # Ignore clicks while we're refreshing or repopulating the UI
            if self.is_refreshing or getattr(self, 'is_populating_articles', False):
                try:
                    self.statusBar().showMessage("Loading… please wait for refresh to complete", 2000)
                except Exception:
                    pass
                logging.debug(f"display_content: ignored due to is_refreshing={self.is_refreshing}, is_populating={self.is_populating_articles}")
                return
            selected_items = self.articles_tree.selectedItems()
            if not selected_items:
                logging.debug("display_content: no selected item")
                return

            item = selected_items[0]
            entry = item.data(0, Qt.UserRole)
            if not entry:
                logging.debug("display_content: selected item has no entry data")
                return
            
            # Mark article as read when displaying content
            article_id = self.get_article_id(entry)
            if article_id not in self.read_articles:
                self.read_articles.add(article_id)
                item.setIcon(0, QIcon())  # Remove the blue dot icon

            # Helpers to coerce various feedparser field shapes to plain text safely
            def _text(v):
                try:
                    if isinstance(v, str):
                        return v
                    if isinstance(v, dict):
                        val = v.get('value')
                        return val if isinstance(val, str) else ''
                    if isinstance(v, list) and v:
                        # Common case: list of dicts with 'value'
                        first = v[0]
                        if isinstance(first, dict):
                            val = first.get('value')
                            return val if isinstance(val, str) else ''
                        return first if isinstance(first, str) else ''
                    return str(v) if v is not None else ''
                except Exception:
                    return ''

            # Check if preview text is available in the feed (robust against non-strings)
            preview_text = _text(entry.get('summary')).strip()
            description = _text(entry.get('description')).strip()
            content = _text(entry.get('content')).strip()
            
            # Add debug logging to see what content is available
            logging.debug(f"Article content - Title: {entry.get('title', 'No Title')}")
            logging.debug(f"Content available: {bool(content)}, length: {len(content)}")
            logging.debug(f"Description available: {bool(description)}, length: {len(description)}")
            logging.debug(f"Summary available: {bool(preview_text)}, length: {len(preview_text)}")
            
            # Use the best available content from the feed
            if content:
                html_content = content
                logging.debug("Using 'content' for article")
                self.display_formatted_content(entry, html_content)
            elif description:
                html_content = description
                logging.debug("Using 'description' for article")
                self.display_formatted_content(entry, html_content)
            elif preview_text:
                html_content = preview_text
                logging.debug("Using 'summary' for article")
                self.display_formatted_content(entry, html_content)
            else:
                # No content available in the feed, try to fetch from URL
                logging.debug("No content available, attempting to fetch from URL")
                article_url = entry.get('link', '')
                if article_url:
                    # Show a loading message while we fetch the content
                    loading_html = """
                <html>
                <head>
                    <style>
                        body {{ 
                            font-family: Arial, sans-serif; 
                            text-align: center; 
                            margin-top: 50px; 
                            color: #555; 
                        }}
                        .loader {{
                            border: 5px solid #f3f3f3;
                            border-radius: 50%;
                            border-top: 5px solid #3498db;
                            width: 50px;
                            height: 50px;
                            animation: spin 2s linear infinite;
                            margin: 20px auto;
                        }}
                        @keyframes spin {{
                            0% {{ transform: rotate(0deg); }}
                            100% {{ transform: rotate(360deg); }}
                        }}
                    </style>
                </head>
                <body>
                    <h3>Fetching content...</h3>
                    <div class="loader"></div>
                    <p>Loading article from: {0}</p>
                </body>
                </html>
                """.format(article_url)
                    self.content_view.setHtml(loading_html)
                    
                    # Start a background thread to fetch content
                    self.fetch_article_content(entry)
                else:
                    # No URL available, show placeholder
                    logging.debug("No URL available for article")
                    placeholder_html = """
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; color: #555; }}
                    </style>
                </head>
                <body>
                    <h3>No preview available.</h3>
                    <p>No URL found for this article.</p>
                </body>
                </html>
                """
                    self.content_view.setHtml(placeholder_html)
        except Exception:
            logging.exception("Error in display_content")
            try:
                self.statusBar().showMessage("Error opening article. See log for details.", 5000)
            except Exception:
                pass

    def display_formatted_content(self, entry, html_content):
        """Display formatted content with consistent styling."""
        if getattr(self, 'is_shutting_down', False) or getattr(self, '_shutdown_in_progress', False):
            logging.debug("display_formatted_content: skipped due to shutdown")
            return
        formatted_html = """
        <html>
        <head>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    margin: 20px; 
                    color: #333; 
                    line-height: 1.6;
                    max-width: 800px;
                    margin: 0 auto;
                }}
                h1, h2, h3 {{ color: #444; }}
                img {{ max-width: 100%; height: auto; }}
                a {{ color: #0066cc; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
                pre, code {{ 
                    background-color: #f5f5f5; 
                    padding: 10px; 
                    border-radius: 5px; 
                    font-family: monospace; 
                    overflow-x: auto;
                }}
                blockquote {{
                    border-left: 4px solid #ccc;
                    margin-left: 0;
                    padding-left: 15px;
                    color: #666;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 15px 0;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                }}
                th {{
                    background-color: #f2f2f2;
                    text-align: left;
                }}
            </style>
        </head>
        <body>
            <h2>{0}</h2>
            {1}
            <p><a href="{2}">Read full article in browser</a></p>
        </body>
        </html>
        """.format(entry.get('title', 'No Title'), html_content, entry.get('link', '#'))
        
        # Display the content directly (guard if view already deleted)
        try:
            self.content_view.setHtml(formatted_html)
        except Exception:
            logging.debug("content_view is not available to set HTML (probably during shutdown)")
        logging.info(f"Displayed content for article: {entry.get('title', 'No Title')}")

    def fetch_article_content(self, entry):
        """Fetch article content from the article URL."""
        if getattr(self, 'is_shutting_down', False) or getattr(self, '_shutdown_in_progress', False):
            logging.debug("fetch_article_content: skipped due to shutdown")
            return
        class ContentFetchWorker(QObject):
            content_fetched = pyqtSignal(object, str)

            def __init__(self, entry):
                super().__init__()
                self.entry = entry

            def run(self):
                try:
                    url = self.entry.get('link', '')
                    if not url:
                        raise ValueError("No URL available")
                    
                    logging.debug(f"Fetching content from URL: {url}")
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    response = requests.get(url, headers=headers, timeout=10)
                    response.raise_for_status()
                    
                    # Try to extract main content
                    html_content = self.extract_main_content(response.text)
                    
                    # Send the content back to the main thread
                    self.content_fetched.emit(self.entry, html_content)
                    logging.debug(f"Content fetched successfully from {url}")
                    
                except Exception as e:
                    logging.error(f"Error fetching article content: {e}")
                    error_html = f"""
                    <div>
                        <h3>Failed to load content</h3>
                        <p>Error: {str(e)}</p>
                        <p>Please try opening the article in your browser.</p>
                    </div>
                    """
                    self.content_fetched.emit(self.entry, error_html)

            def extract_main_content(self, html):
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.extract()
                    
                    # Try different approaches to find the main content
                    # 1. Try article tag
                    content = soup.find('article')
                    if content:
                        logging.debug("Found content in <article> tag")
                        return content.decode_contents()
                    
                    # 2. Try main tag
                    content = soup.find('main')
                    if content:
                        logging.debug("Found content in <main> tag")
                        return content.decode_contents()
                    
                    # 3. Try div with content-related class/id
                    for id_value in ['content', 'main-content', 'article-content', 'post-content']:
                        content = soup.find('div', id=id_value)
                        if content:
                            logging.debug(f"Found content in div with id={id_value}")
                            return content.decode_contents()
                    
                    for class_value in ['content', 'article', 'post', 'entry', 'main-content']:
                        content = soup.find('div', class_=class_value)
                        if content:
                            logging.debug(f"Found content in div with class={class_value}")
                            return content.decode_contents()
                    
                    # 4. If nothing else works, get the body content
                    if soup.body:
                        logging.debug("Using body content as fallback")
                        # Try to filter out headers, footers, sidebars
                        for tag in soup.find_all(['header', 'footer', 'aside', 'nav']):
                            tag.extract()
                        
                        return str(soup.body)
                    
                    logging.debug("No specific content container found, returning whole HTML")
                    return html  # Return the original HTML if all else fails
                except ImportError:
                    logging.error("BeautifulSoup is not installed. Please install it with: pip install beautifulsoup4")
                    return f"""
                    <div>
                        <h3>Missing Dependency</h3>
                        <p>BeautifulSoup is required to extract article content.</p>
                        <p>Please install it with: pip install beautifulsoup4</p>
                    </div>
                    """
                except Exception as e:
                    logging.error(f"Error extracting content: {e}")
                    return html  # Return the original HTML on error

        # Create worker and thread
        # Avoid duplicate fetch for the same article if one is already active
        try:
            current_id = self.get_article_id(entry)
            if current_id in self.active_content_loads:
                logging.debug(f"Content fetch already active for article_id={current_id}; skipping duplicate start.")
                return
        except Exception:
            current_id = None

        worker = ContentFetchWorker(entry)
        thread = QThread()
        try:
            title = entry.get('title', 'No Title')
            safe_name = f"ContentFetchThread:{hashlib.md5(title.encode('utf-8')).hexdigest()[:8]}"
            thread.setObjectName(safe_name)
        except Exception:
            pass
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.content_fetched.connect(self.on_article_content_fetched)
        # Ensure thread stops and cleanup happens when content is fetched
        try:
            article_id = self.get_article_id(entry)
        except Exception:
            article_id = None
        if article_id:
            worker.content_fetched.connect(lambda _e, _html, aid=article_id: self._complete_content_load(aid))
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        # Remove from self.threads when finished
        thread.finished.connect(lambda t=thread: self.threads.remove(t) if t in self.threads else None)
        
        # Register active load with watchdog timer
        if article_id and not getattr(self, 'is_shutting_down', False):
            self._register_content_load(article_id, thread, worker)

        # Start thread
        thread.start()
        try:
            self.register_thread(thread, thread.objectName() or "ContentFetchThread")
        except Exception:
            self.threads.append(thread)
        logging.debug(f"Started thread to fetch content for article: {entry.get('title', 'No Title')}")

    def on_article_content_fetched(self, entry, html_content):
        """Handle fetched article content."""
        if getattr(self, 'is_shutting_down', False) or getattr(self, '_shutdown_in_progress', False) or getattr(self, '_shutdown_done', False):
            logging.debug("on_article_content_fetched: ignored due to shutdown")
            return
        logging.debug(f"Received fetched content for article: {entry.get('title', 'No Title')}")
        
        # Make sure this article is still selected
        selected_items = self.articles_tree.selectedItems()
        if not selected_items:
            logging.debug("No article selected when content was fetched")
            return
            
        item = selected_items[0]
        current_entry = item.data(0, Qt.UserRole)
        
        # Check if the fetched content is for the currently selected article
        if self.get_article_id(current_entry) == self.get_article_id(entry):
            logging.debug("Displaying fetched content")
            self.display_formatted_content(entry, html_content)
        else:
            logging.debug("Ignoring fetched content for non-selected article")

    def _register_content_load(self, article_id: str, thread: QThread, worker: QObject):
        """Track an active content load and start a watchdog timer to avoid hangs."""
        if getattr(self, 'is_shutting_down', False) or getattr(self, '_shutdown_in_progress', False):
            logging.debug("_register_content_load: skipped due to shutdown")
            return
        try:
            # Stop previous timer if exists for same article_id
            self._complete_content_load(article_id)
        except Exception:
            pass
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(15000)  # 15s watchdog
        timer.timeout.connect(lambda aid=article_id: self._on_content_fetch_timeout(aid))
        self.active_content_loads[article_id] = {"thread": thread, "worker": worker, "timer": timer}
        timer.start()

    def _complete_content_load(self, article_id: str):
        """Cleanup tracking and stop the background thread for a finished/aborted load."""
        info = self.active_content_loads.pop(article_id, None)
        if not info:
            return
        try:
            timer = info.get("timer")
            if timer:
                timer.stop()
                try:
                    timer.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass
        thread = info.get("thread")
        try:
            if thread:
                # Ask the thread to stop its event loop if it's still running
                if thread.isRunning():
                    thread.quit()
                    if not thread.wait(500):
                        # Keep a reference and clean up later on finish to avoid premature destruction
                        logging.warning(f"Content fetch thread didn't stop in time; deferring cleanup: {thread.objectName() or thread}")
                        try:
                            self._stale_threads.append(thread)
                            thread.finished.connect(lambda thr=thread: self._cleanup_stale_thread(thr))
                        except Exception:
                            pass
                        return
                # Only remove from registry after it has fully stopped
                try:
                    if thread in self.threads:
                        self.threads.remove(thread)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_content_fetch_timeout(self, article_id: str):
        """Handle content fetch timeout: show a message if the article is still selected and cleanup."""
        info = self.active_content_loads.get(article_id)
        if not info:
            return
        # If this article is still selected, show timeout message
        try:
            selected_items = self.articles_tree.selectedItems()
            if selected_items:
                current_entry = selected_items[0].data(0, Qt.UserRole)
                if self.get_article_id(current_entry) == article_id:
                    timeout_html = f"""
                    <div>
                        <h3>Failed to load content</h3>
                        <p>Error: timed out while fetching the article content.</p>
                        <p>Please try opening the article in your browser.</p>
                    </div>
                    """
                    self.display_formatted_content(current_entry, timeout_html)
        except Exception:
            pass
        # Try to stop the background thread
        thread = info.get("thread")
        try:
            if thread and thread.isRunning():
                thread.quit()
                if not thread.wait(300):
                    # Forcefully terminate as a last resort
                    try:
                        thread.terminate()
                    except Exception:
                        pass
        except Exception:
            pass
        # Final cleanup
        self._complete_content_load(article_id)

    pass

    def update_content_view(self, content):
        """Update the content view with the fetched HTML content."""
        logging.info(f"update_content_view called. Content length: {len(content)}")
        if not content.strip():
            logging.warning("Received empty content to display.")
        self.content_view.setHtml(content)

    # HTTP auth has been removed from the application.

    def extract_article_content(self, html):
        """Extract the main content of the article from its HTML."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # Attempt to find the main content block
            main_content = soup.find('article') or soup.find('div', class_='content') or soup.find('div', id='main')
            if (main_content):
                return main_content.decode_contents()

            # Fallback: return the entire body if no specific block is found
            return soup.body.decode_contents() if soup.body else 'No content available.'
        except Exception as e:
            return 'No content available.'

    def highlight_text(self, text, search_text):
        if not search_text:
            return text
        highlighted = f'<span style="background-color: yellow;">{search_text}</span>'
        return re.sub(re.escape(search_text), highlighted, text, flags=re.IGNORECASE)

    def add_article_to_tree(self, entry):
        """Add an article to the articles tree."""
        title = entry.get('title', 'No Title')
        item = ArticleTreeWidgetItem([title, '', '', '', '', '', '', '', ''])
        date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
        if date_struct:
            date_obj = datetime(*date_struct[:6])
            date_formatted = date_obj.strftime('%d-%m-%Y')
        else:
            date_obj = datetime.min
            date_formatted = 'No Date'
        item.setText(1, date_formatted)
        item.setData(1, Qt.UserRole, date_obj)
        item.setText(2, 'N/A')
        item.setText(3, '')
        item.setText(4, '')
        item.setText(5, '')
        item.setText(6, '')
        item.setText(7, '')
        item.setText(8, '')
        article_id = self.get_article_id(entry)
        item.setData(0, Qt.UserRole + 1, article_id)
        item.setData(0, Qt.UserRole, entry)

        # Определяем фид для этой статьи
        feed_url = None
        for feed in self.feeds:
            if entry in feed.get('entries', []):
                feed_url = feed['url']
                break

        # Mark unread articles with bold font and an icon
        if article_id not in self.read_articles:
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setIcon(0, self.blue_dot_icon)
        else:
            item.setIcon(0, QIcon())  # No icon for read articles

        # Устанавливаем иконку фида, если есть (ищем по доменным вариантам)
        try:
            if feed_url:
                domain = urlparse(feed_url).netloc or feed_url
                for d in _domain_variants(domain):
                    icon = self.favicon_cache.get(d)
                    if icon:
                        item.setIcon(0, icon)
                        break
        except Exception:
            pass

        self.articles_tree.addTopLevelItem(item)
        self.article_id_to_item[article_id] = item

    def update_article_in_tree(self, item, entry):
        title = entry.get('title', 'No Title')
        item.setText(0, title)
        date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
        if date_struct:
            date_obj = datetime(*date_struct[:6])
            date_formatted = date_obj.strftime('%d-%m-%Y')
        else:
            date_obj = datetime.min
            date_formatted = 'No Date'
        item.setText(1, date_formatted)
        item.setData(1, Qt.UserRole, date_obj)

    def get_all_tree_items(self, tree_widget):
        items = []
        for index in range(tree_widget.topLevelItemCount()):
            items.append(tree_widget.topLevelItem(index))
        return items

    def get_current_feed(self):
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            return None
        item = selected_items[0]
        if item.data(0, Qt.UserRole) is None:
            return None
        url = item.data(0, Qt.UserRole)
        return next((feed for feed in self.feeds if feed['url'] == url), None)

    def remove_thread(self, thread):
        if thread in self.threads:
            self.threads.remove(thread)
            logging.debug("Removed a thread.")

    def update_movie_info(self, index, article_id, movie_data):
        # Guard if called too early
        if not hasattr(self, 'current_entries'):
            logging.debug("update_movie_info called before current_entries initialized; skipping.")
            return
        # Ignore signals from stale/old threads
        try:
            sender_thread = self.sender()
            if hasattr(self, 'movie_thread') and sender_thread is not None and sender_thread is not self.movie_thread:
                logging.debug("Ignoring movie_data_fetched from stale thread.")
                return
        except Exception:
            pass
        # If article_id not present, fallback to index bounds check
        if not article_id:
            if index < 0 or index >= len(self.current_entries):
                logging.error(f"update_movie_info: index {index} out of range.")
                return
            entry = self.current_entries[index]
            article_id = self.get_article_id(entry)
        if article_id not in self.article_id_to_item:
            logging.warning(f"Skipped update: Article ID {article_id} not found.")
            return
        item = self.article_id_to_item.get(article_id)
        if not item:
            logging.debug(f"No QTreeWidgetItem found for article ID: {article_id}")
            return
        try:
            imdb_rating = movie_data.get('imdbrating', 'N/A')
            rating_value = self.parse_rating(imdb_rating)
            item.setData(2, Qt.UserRole, rating_value)
            item.setText(2, imdb_rating)
            released = movie_data.get('released', '')
            release_date = self.parse_release_date(released)
            item.setData(3, Qt.UserRole, release_date)
            item.setText(3, release_date.strftime('%d %b %Y') if release_date != datetime.min else '')
            item.setText(4, movie_data.get('genre', ''))
            item.setText(5, movie_data.get('director', ''))
            item.setText(6, movie_data.get('country', ''))
            item.setText(7, movie_data.get('actors', ''))
            item.setText(8, movie_data.get('poster', ''))
            # Update the entry stored in the item, if present
            entry = item.data(0, Qt.UserRole)
            if isinstance(entry, dict):
                entry['movie_data'] = movie_data
            if getattr(self, 'tooltips_enabled', False):
                tooltip = f"Year: {movie_data.get('year', '')}\n" \
                          f"Country: {movie_data.get('country', '')}\n" \
                          f"Actors: {movie_data.get('actors', '')}\n" \
                          f"Writer: {movie_data.get('writer', '')}\n" \
                          f"Awards: {movie_data.get('awards', '')}\n" \
                          f"Plot: {movie_data.get('plot', '')}\n" \
                          f"IMDB Votes: {movie_data.get('imdbvotes', '')}\n" \
                          f"Type: {movie_data.get('type', '')}\n" \
                          f"Poster: {movie_data.get('poster', '')}"
                item.setToolTip(0, tooltip)
        except RuntimeError:
            # Item was deleted due to UI refresh; ignore
            logging.debug("Skipped movie info update: item was deleted")

    def parse_rating(self, rating_str):
        try:
            return float(rating_str.split('/')[0])
        except (ValueError, IndexError):
            return 0.0

    def parse_release_date(self, released_str):
        try:
            return datetime.strptime(released_str, '%d %b %Y')
        except (ValueError, TypeError):
            return datetime.min

    def get_article_id(self, entry):
        unique_string = entry.get('id') or entry.get('guid') or entry.get('link') or (entry.get('title', '') + entry.get('published', ''))
        return hashlib.md5(unique_string.encode('utf-8')).hexdigest()

    def mark_feed_unread(self):
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            self.statusBar().showMessage("Please select a feed to mark as unread.", 5000)
            return
        item = selected_items[0]
        if item.data(0, Qt.UserRole) is None:
            self.statusBar().showMessage("Please select a feed, not a group.", 5000)
            return
        feed_url = item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == feed_url), None)
        if not feed_data or 'entries' not in feed_data:
            self.statusBar().showMessage("The selected feed has no articles.", 5000)
            return
        for entry in feed_data['entries']:
            article_id = self.get_article_id(entry)
            if article_id in self.read_articles:
                self.read_articles.remove(article_id)
        self.populate_articles_ui()
        self.update_feed_bold_status(feed_url)
        self.statusBar().showMessage(f"Marked all articles in '{feed_data['title']}' as unread.", 5000)
        logging.info(f"Marked all articles in feed '{feed_data['title']}' as unread.")

    def filter_articles(self, search_text):
        search_text = search_text.lower().strip()
        self.articles_tree.clear()
        for feed in self.feeds:
            for entry in feed.get('entries', []):
                title = entry.get("title", "").lower()
                summary = entry.get("summary", "").lower()
                content = entry.get("content", [{}])[0].get("value", "").lower()
                if (search_text in title) or (search_text in summary) or (search_text in content):
                    self.add_article_to_tree(entry)

    def refresh_feed(self):
        self.load_articles()
        logging.info("Refreshed selected feed.")

    def force_refresh_all_feeds(self):
        if self.is_refreshing:
            logging.debug("Refresh already in progress.")
            return
        if not self.feeds:
            logging.warning("No feeds to refresh.")
            return
        self.is_refreshing = True
        self.refresh_icon_angle = 0
        self.icon_rotation_timer.start(50)
        self.active_feed_threads = len(self.feeds)
        logging.info("Starting force refresh of all feeds.")
        worker = Worker()
        worker.feed_fetched.connect(self.on_feed_fetched_force_refresh)
        for feed_data in self.feeds:
            url = feed_data['url']
            runnable = FetchFeedRunnable(url, worker)
            self.thread_pool.start(runnable)
            logging.debug(f"Started thread for feed: {url}")
        QApplication.processEvents()

    def on_feed_fetched(self, url, feed):
        new_entries = []
        if feed is not None:
            for feed_data in self.feeds:
                if feed_data['url'] == url:
                    new_entries = []
                    existing_ids = {self.get_article_id(e) for e in feed_data.get('entries', [])}
                    for entry in feed.entries:
                        article_id = self.get_article_id(entry)
                        if article_id not in existing_ids:
                            feed_data['entries'].append(entry)
                            new_entries.append(entry)
                            self.send_notification(feed_data['title'], entry)
                    self.prune_old_entries()
                    self.mark_feeds_dirty()
                    break
            current_feed_item = self.feeds_list.currentItem()
            if (current_feed_item and current_feed_item.data(0, Qt.UserRole) == url):
                self.populate_articles_ui()  # Corrected method call
                # Done populating for current feed via network
                self.is_populating_articles = False
            logging.info(f"Fetched feed: {url} with {len(new_entries)} new articles.")
            self.update_feed_bold_status(url)
        else:
            logging.warning(f"Failed to fetch feed: {url}")

    def on_feed_fetched_force_refresh(self, url, feed):
        logging.debug(f"Force refresh for feed: {url}")
        if feed is not None:
            for feed_data in self.feeds:
                if feed_data['url'] == url:
                    new_entries = []
                    existing_ids = {self.get_article_id(e) for e in feed_data.get('entries', [])}
                    for entry in feed.entries:
                        article_id = self.get_article_id(entry)
                        if article_id not in existing_ids:
                            feed_data['entries'].append(entry)
                            new_entries.append(entry)
                            self.send_notification(feed_data['title'], entry)
                    if new_entries:
                        self.set_feed_new_icon(url, True)
                    self.prune_old_entries()
                    self.mark_feeds_dirty()
                    break
        else:
            logging.warning(f"Failed to refresh feed: {url}")
        self.active_feed_threads -= 1
        logging.debug(f"Remaining refresh threads: {self.active_feed_threads}")
        if self.active_feed_threads == 0:
            self.is_refreshing = False
            self.icon_rotation_timer.stop()
            self.force_refresh_action.setIcon(QIcon(self.force_refresh_icon_pixmap))
            logging.info("Completed force refresh of all feeds.")
            current_feed = self.get_current_feed()
            if current_feed:
                self.populate_articles_ui()  # Corrected method call
        self.update_feed_bold_status(url)

    def update_feed_bold_status(self, feed_url):
        for i in range(self.feeds_list.topLevelItemCount()):
            top_item = self.feeds_list.topLevelItem(i)
            if top_item.data(0, Qt.UserRole) == feed_url:
                feed_data = next((feed for feed in self.feeds if feed['url'] == feed_url), None)
                if feed_data:
                    font = top_item.font(0)
                    font.setBold(self.has_unread_articles(feed_data))
                    top_item.setFont(0, font)
                break
            else:
                for j in range(top_item.childCount()):
                    feed_item = top_item.child(j)
                    if feed_item.data(0, Qt.UserRole) == feed_url:
                        feed_data = next((feed for feed in self.feeds if feed['url'] == feed_url), None)
                        if feed_data:
                            font = feed_item.font(0)
                            font.setBold(self.has_unread_articles(feed_data))
                            feed_item.setFont(0, font)
                        break

    def show_feed_context_menu(self, feed_item, position):
        menu = QMenu()
        rename_feed_action = QAction("Rename Feed", self)
        rename_feed_action.triggered.connect(self.rename_feed)
        menu.addAction(rename_feed_action)
        remove_feed_action = QAction("Remove Feed", self)
        remove_feed_action.triggered.connect(lambda: self.remove_feed(feed_item))
        menu.addAction(remove_feed_action)
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(lambda: self.feed_settings_dialog(feed_item))
        menu.addAction(settings_action)
        menu.exec_(self.feeds_list.viewport().mapToGlobal(position))

    def import_feeds(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Import Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as f:
                    feeds = json.load(f)
                    for feed in feeds:
                        if feed['url'] not in [f['url'] for f in self.feeds]:
                            feed.setdefault('sort_column', 1)
                            feed.setdefault('sort_order', Qt.AscendingOrder)
                            feed.setdefault('visible_columns', [True] * 6)
                            self.feeds.append(feed)
                self.prune_old_entries()
                self.mark_feeds_dirty()
                self.save_feeds()
                self.statusBar().showMessage("Feeds imported", 5000)
                logging.info("Feeds imported successfully.")
            except Exception as e:
                self.statusBar().showMessage(f"Failed to import feeds: {e}", 5000)
                logging.error(f"Failed to import feeds: {e}")

    def export_feeds(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    json.dump(self.feeds, f, indent=4)
                self.statusBar().showMessage("Feeds exported", 5000)
                logging.info("Feeds exported successfully.")
            except Exception as e:
                self.statusBar().showMessage(f"Failed to export feeds: {e}", 5000)
                logging.error(f"Failed to export feeds: {e}")

    def show_header_menu(self, position):
        menu = QMenu()
        header = self.articles_tree.header()
        current_feed = self.get_current_feed()
        if not current_feed:
            return
        group_name = self.get_group_name_for_feed(current_feed['url'])
        group_settings = self.group_settings.get(group_name, {'omdb_enabled': False})
        omdb_enabled = group_settings.get('omdb_enabled', False)
        for i in range(header.count()):
            column_name = header.model().headerData(i, Qt.Horizontal)
            action = QAction(column_name, menu)
            action.setCheckable(True)
            visible = current_feed['visible_columns'][i] if 'visible_columns' in current_feed and i < len(current_feed['visible_columns']) else True
            action.setChecked(visible)
            action.setData(i)
            if not omdb_enabled and i > 1:
                action.setEnabled(False)
            action.toggled.connect(self.toggle_column_visibility)
            menu.addAction(action)
        menu.exec_(header.mapToGlobal(position))

    def toggle_column_visibility(self, checked):
        action = self.sender()
        index = action.data()
        if checked:
            self.articles_tree.showColumn(index)
        else:
            self.articles_tree.hideColumn(index)
        current_feed = self.get_current_feed()
        if current_feed and 'visible_columns' in current_feed and index < len(current_feed['visible_columns']):
            current_feed['visible_columns'][index] = checked
            self.mark_feeds_dirty()
            logging.debug(f"Column {index} visibility set to {checked} for feed '{current_feed['title']}'.")

    def on_sort_changed(self, column, order):
        current_feed = self.get_current_feed()
        if current_feed:
            current_feed['sort_column'] = column
            current_feed['sort_order'] = order
            self.mark_feeds_dirty()
            logging.debug(f"Sort settings updated for feed '{current_feed['title']}': column={column}, order={order}.")

    def select_first_feed(self):
        if self.feeds_list.topLevelItemCount() > 0:
            first_item = self.feeds_list.topLevelItem(0)
            if first_item.data(0, Qt.UserRole) is not None:
                self.feeds_list.setCurrentItem(first_item)
            elif first_item.childCount() > 0:
                first_feed = first_item.child(0)
                self.feeds_list.setCurrentItem(first_feed)

    def initialize_periodic_cleanup(self):
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.perform_periodic_cleanup)
        self.cleanup_timer.start(86400000)
        logging.info("Periodic cleanup timer initialized (daily).")

    def perform_periodic_cleanup(self):
        logging.info("Performing periodic cleanup of old articles.")
        self.prune_old_entries()
        self.statusBar().showMessage("Periodic cleanup completed.")

    def feed_settings_dialog(self, feed_item):
        feed_url = feed_item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == feed_url), None)
        if not feed_data:
            self.warn("Error", "Feed data not found.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Settings for {feed_data['title']}")
        layout = QVBoxLayout(dialog)

        url_label = QLabel("Feed URL:", dialog)
        layout.addWidget(url_label)
        url_input = QLineEdit(dialog)
        url_input.setText(feed_data.get('url', ''))
        layout.addWidget(url_input)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            new_url = url_input.text().strip()
            self.update_feed_url(feed_item, new_url)

    def update_feed_url(self, feed_item, new_url):
        if not new_url:
            self.warn("Input Error", "Feed URL is required.")
            return False
        if not new_url.startswith(('http://', 'https://')):
            new_url = 'http://' + new_url
        old_url = feed_item.data(0, Qt.UserRole)
        if new_url == old_url:
            return True
        # Check duplicates excluding current feed
        if any(f['url'] == new_url for f in self.feeds if f['url'] != old_url):
            self.warn("Input Error", "This feed URL is already added.")
            return False
        feed_data = next((f for f in self.feeds if f['url'] == old_url), None)
        if not feed_data:
            self.warn("Error", "Feed data not found.")
            return False
        # Migrate URL in related mappings
        if old_url in self.column_widths:
            self.column_widths[new_url] = self.column_widths.pop(old_url)
        # Update favicon cache mapping (optional: clear to refetch)
        if old_url in self.favicon_cache:
            self.favicon_cache[new_url] = self.favicon_cache.pop(old_url)
        # Update feed data and UI item
        feed_data['url'] = new_url
        feed_item.setData(0, Qt.UserRole, new_url)
        # Update icon based on new domain (guard for non-UI test dummies)
        if hasattr(feed_item, 'setIcon'):
            self.set_feed_icon(feed_item, new_url)
        self.mark_feeds_dirty()
        self.save_feeds()
        self.statusBar().showMessage("Feed URL updated.", 5000)
        logging.info(f"Updated feed URL: {old_url} -> {new_url}")
        return True

    

    def update_content_view(self, content):
        """Update the content view with the fetched HTML content."""
        logging.info("update_content_view called wit" \
        "h content length: %d" % len(content))
        self.content_view.setHtml(content)

    def cleanup_orphaned_data(self):
        # Собираем все актуальные article_id
        all_article_ids = set()
        for feed in self.feeds:
            for entry in feed.get('entries', []):
                all_article_ids.add(self.get_article_id(entry))

        # Очищаем прочитанные статьи
        before_count = len(self.read_articles)
        self.read_articles = {aid for aid in self.read_articles if aid in all_article_ids}
        after_count = len(self.read_articles)
        if after_count < before_count:
            logging.info(f"Removed {before_count - after_count} orphaned read_articles entries.")
            self.save_read_articles()

        # Очищаем кеш фильмов
        # Собираем все movie_title, которые реально используются
        used_titles = set()
        for feed in self.feeds:
            for entry in feed.get('entries', []):
                movie_data = entry.get('movie_data')
                if movie_data and 'title' in movie_data:
                    used_titles.add(movie_data['title'])
        before_cache = len(self.movie_data_cache)
        self.movie_data_cache = {k: v for k, v in self.movie_data_cache.items() if k in used_titles}
        after_cache = len(self.movie_data_cache)
        if after_cache < before_cache:
            logging.info(f"Removed {before_cache - after_cache} orphaned movie_data_cache entries.")
            self.save_movie_data_cache()

# =========================
# 4. RSS operations: fetching and caching
# =========================

# ...методы RSSReader, связанные с fetch_feed_with_cache, force_refresh_all_feeds, on_feed_fetched, on_feed_fetched_force_refresh, fetch_article_content, load_article_content_async ...

# =========================
# 5. File operations (I/O)
# =========================

# ...методы RSSReader, связанные с load_feeds, save_feeds, load_read_articles, save_read_articles, load_group_settings, save_group_settings, load_movie_data_cache, save_movie_data_cache ...

# =========================
# 6. Main entrypoint
# =========================

def main():
    parser = argparse.ArgumentParser(description="Small RSS Reader")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(application_path)
    # Determine logging level: --debug has priority, otherwise from Settings
    if args.debug:
        logging_level = logging.DEBUG
    else:
        try:
            level_name = QSettings('rocker', 'SmallRSSReader').value('log_level', 'INFO')
            level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
            logging_level = level_map.get(str(level_name).upper(), logging.INFO)
        except Exception:
            logging_level = logging.INFO
    log_path = get_user_data_path('rss_reader.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(
        level=logging_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            file_handler,
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Install global exception hook
    def excepthook(exc_type, exc_value, exc_traceback):
        logging.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.instance() and QApplication.instance().quit()
        except Exception:
            pass
    sys.excepthook = excepthook

    # Install Qt message handler for warnings/errors from Qt
    def qt_message_handler(mode, context, message):
        try:
            level = {
                QtMsgType.QtDebugMsg: logging.DEBUG,
                QtMsgType.QtInfoMsg: logging.INFO,
                QtMsgType.QtWarningMsg: logging.WARNING,
                QtMsgType.QtCriticalMsg: logging.ERROR,
                QtMsgType.QtFatalMsg: logging.CRITICAL,
            }.get(mode, logging.INFO)
            logging.log(level, f"Qt: {message}")
        except Exception:
            pass
    try:
        qInstallMessageHandler(qt_message_handler)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setOrganizationName("rocker")
    app.setApplicationName("SmallRSSReader")
    app.setApplicationDisplayName("Small RSS Reader")
    try:
        if APP_VERSION:
            app.setApplicationVersion(APP_VERSION)
    except Exception:
        pass
    app.setWindowIcon(QIcon(resource_path('icons/rss_icon.png')))
    app.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app.setQuitOnLastWindowClosed(True)
    splash_pix = QPixmap(resource_path('icons/splash.png'))
    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.setMask(splash_pix.mask())
    splash.showMessage("Initializing...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    splash.show()
    QApplication.processEvents()
    reader = RSSReader()
    reader.show()
    reader.raise_()
    reader.activateWindow()
    # Settings and feeds are loaded inside RSSReader.__init__ via load_settings()
    splash.showMessage("Refreshing feeds...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    QApplication.processEvents()
    splash.showMessage("Finalizing...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    QApplication.processEvents()
    splash.finish(reader)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
