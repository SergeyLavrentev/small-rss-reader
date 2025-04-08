#!/usr/bin/env python3
import sys
import os
import json
import logging
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
from datetime import datetime, timedelta
from urllib.parse import urlparse
from omdbapi.movie_search import GetMovie
from PyQt5.QtWidgets import QFontComboBox
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
    Qt, QTimer, QThread, pyqtSignal, QUrl, QSettings, QSize, QEvent, QObject, QRunnable, QThreadPool, pyqtSlot
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from pathlib import Path

### Helper Functions ###

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

### Helper Classes ###

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
    movie_data_fetched = pyqtSignal(int, dict)

    def __init__(self, entries, api_key, cache, quit_flag):
        super().__init__()
        self.entries = entries
        self.api_key = api_key
        self.movie_data_cache = cache
        self.quit_flag = quit_flag  # threading.Event for graceful shutdown

    def run(self):
        if not self.api_key:
            logging.warning("OMDb API key not provided. Skipping movie data fetching.")
            return
        for index, entry in enumerate(self.entries):
            if self.quit_flag.is_set():
                break
            title = entry.get('title', 'No Title')
            movie_title = self.extract_movie_title(title)
            if movie_title in self.movie_data_cache:
                movie_data = self.movie_data_cache[movie_title]
                logging.debug(f"Retrieved cached movie data for '{movie_title}'.")
            else:
                movie_data = self.fetch_movie_data(movie_title)
                if movie_data:
                    self.movie_data_cache[movie_title] = movie_data
                    logging.debug(f"Fetched and cached movie data for '{movie_title}'.")
            self.movie_data_fetched.emit(index, movie_data)

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
                logging.warning(f"No data returned from OMDb for '{movie_title}'.")
            return movie_data
        except Exception as e:
            logging.error(f"Failed to fetch movie data for '{movie_title}': {e}")
            return {}

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

        if target_item and target_item.parent() != source_item.parent():
            QMessageBox.warning(self, "Invalid Move", "Feeds can only be moved within their own groups.")
            event.ignore()
            return
        super().dropEvent(event)

class WebEnginePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if _type == QWebEnginePage.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)  # Open the link in the default browser
            return False  # Prevent the WebEngineView from handling the link
        return super().acceptNavigationRequest(url, _type, isMainFrame)

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
            QMessageBox.warning(self, "Input Error", "Feed URL is required.")
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

### Main Application Class ###

class PopulateArticlesThread(QThread):
    articles_ready = pyqtSignal(list, dict)  # Emits (entries, article_id_to_item)

    def __init__(self, entries, read_articles, max_days):
        super().__init__()
        self.entries = entries
        self.read_articles = read_articles
        self.max_days = max_days

    def run(self):
        filtered_entries = []
        article_id_to_item = {}
        max_days_ago = datetime.now() - timedelta(days=self.max_days)

        for entry in self.entries:
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                entry_date = datetime(*date_struct[:6])
                entry['formatted_date'] = format_date_column(entry_date)
                if entry_date >= max_days_ago:
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

    def __init__(self):
        super().__init__()
        self.data_changed = False  # Track if data has been modified
        self.feed_cache = {}  # Cache for feed data with timestamps
        self.cache_expiry = timedelta(minutes=5)
        self.setWindowTitle("Small RSS Reader")
        self.resize(1200, 800)
        self.initialize_variables()
        self.init_ui()
        self.load_group_names()
        self.load_settings()
        self.load_read_articles()
        self.load_feeds()
        QTimer.singleShot(0, self.force_refresh_all_feeds)
        self.select_first_feed()
        self.active_feed_threads = 0
        self.init_tray_icon()
        self.notify_signal.connect(self.show_notification)

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

    def perform_periodic_cleanup(self):
        logging.info("Performing periodic cleanup of old articles.")
        self.prune_old_entries()
        self.statusBar().showMessage("Periodic cleanup completed.")

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

    def remove_feed(self):
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            self.statusBar().showMessage("Please select a feed to remove.", 5000)
            return
        item = selected_items[0]
        if item.data(0, Qt.UserRole) is None:
            self.statusBar().showMessage("Please select a feed, not a group.", 5000)
            return
        feed_name = item.text(0)
        reply = QMessageBox.question(self, 'Remove Feed',
                                     f"Are you sure you want to remove the feed '{feed_name}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            url = item.data(0, Qt.UserRole)
            self.feeds = [feed for feed in self.feeds if feed['url'] != url]
            parent_group = item.parent()
            if parent_group:
                parent_group.removeChild(item)
                if parent_group.childCount() == 0:
                    self.feeds_list.takeTopLevelItem(self.feeds_list.indexOfTopLevelItem(parent_group))
            else:
                index = self.feeds_list.indexOfTopLevelItem(item)
                self.feeds_list.takeTopLevelItem(index)
            self.mark_feeds_dirty()
            self.save_feeds()
            self.statusBar().showMessage(f"Removed feed: {feed_name}", 5000)
            logging.info(f"Removed feed: {feed_name}")

    def fetch_feed_with_cache(self, url):
        try:
            if url in self.feed_cache:
                cached_data, timestamp = self.feed_cache[url]
                if datetime.now() - timestamp < self.cache_expiry:
                    return cached_data
            feed = feedparser.parse(url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            self.feed_cache[url] = (feed, datetime.now())
            return feed
        except Exception as e:
            logging.error(f"Failed to fetch feed {url}: {e}")
            self.statusBar().showMessage(f"Failed to fetch feed from {url}. Error: {str(e)}", 5000)
            return None

    def clear_expired_cache(self):
        now = datetime.now()
        expired_urls = [url for url, (_, timestamp) in self.feed_cache.items() if now - timestamp >= self.cache_expiry]
        for url in expired_urls:
            del self.feed_cache[url]
        logging.info(f"Cleared {len(expired_urls)} expired cache entries.")

    def initialize_periodic_cleanup(self):
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.perform_periodic_cleanup)
        self.cleanup_timer.start(300000)
        logging.info("Periodic cleanup timer initialized.")

    def initialize_variables(self):
        self.feeds = []
        self.current_entries = []
        self.api_key = ''
        self.refresh_interval = 60
        self.movie_data_cache = {}
        self.read_articles = set()
        self.threads = []
        self.article_id_to_item = {}
        self.group_name_mapping = {}
        self.group_settings = {}  # Default group settings now default to False for OMDb and notifications
        self.is_refreshing = False
        self.is_quitting = False
        self.refresh_icon_angle = 0
        self.icon_rotation_timer = QTimer()
        self.icon_rotation_timer.timeout.connect(self.rotate_refresh_icon)
        self.auto_refresh_timer = QTimer()
        self.force_refresh_icon_pixmap = None
        self.column_widths = {}
        self.default_font_size = 14
        self.default_font = QFont("Arial", self.default_font_size)
        settings = QSettings('rocker', 'SmallRSSReader')
        self.max_days = settings.value('max_days', 30, type=int)
        self.current_font_size = settings.value('font_size', self.default_font_size, type=int)
        font_name = settings.value('font_name', self.default_font.family(), type=str)
        self.default_font = QFont(font_name, self.current_font_size)
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(8)
        movie_icon_path = resource_path('icons/movie_icon.png')
        if not os.path.exists(movie_icon_path):
            logging.error(f"Movie icon not found at: {movie_icon_path}")
            self.movie_icon = QIcon()
        else:
            pixmap = QPixmap(movie_icon_path)
            if pixmap.isNull():
                logging.error(f"Failed to load movie icon from: {movie_icon_path}")
                self.movie_icon = QIcon()
            else:
                scaled_pixmap = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.movie_icon = QIcon(scaled_pixmap)
        self.initialize_periodic_cleanup()
        self.quit_flag = threading.Event()
        # Initialize iCloud backup setting:
        self.icloud_backup_enabled = settings.value('icloud_backup_enabled', False, type=bool)
        self.feeds_dirty = False  # Flag to track if feeds need saving
        self.favicon_cache = {}  # Cache for favicons

    def quit_app(self):
        self.is_quitting = True
        self.quit_flag.set()
        self.statusBar().showMessage("Saving your data before exiting...", 5000)

        # Ensure all threads are terminated
        for thread in self.threads:
            if isinstance(thread, QThread):
                thread.quit()
                thread.wait()
                logging.info(f"Thread {thread} terminated.")

        # Stop and clean up PopulateArticlesThread if running
        if hasattr(self, 'populate_thread') and self.populate_thread.isRunning():
            self.populate_thread.quit()
            self.populate_thread.wait()
            logging.info("PopulateArticlesThread terminated.")

        # Ensure QThreadPool tasks are completed
        self.thread_pool.waitForDone()
        logging.info("All QThreadPool tasks completed.")

        # Explicitly delete QWebEngineView to ensure cleanup
        if hasattr(self, 'content_view'):
            self.content_view.deleteLater()
            logging.info("Deleted QWebEngineView to ensure proper cleanup.")

        self.close()

    def save_font_size(self):
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('font_size', self.current_font_size)

    def apply_font_size(self):
        font = QFont(self.default_font.family(), self.current_font_size)
        self.articles_tree.setFont(font)
        self.content_view.setFont(font)
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
        self.tray_icon.showMessage(title, full_message, QSystemTrayIcon.Information, 5000)

    def send_notification(self, feed_title, entry):
        group_name = self.get_group_name_for_feed(entry.get('link', ''))
        group_settings = self.group_settings.get(group_name, {'notifications_enabled': False})
        notifications_enabled = group_settings.get('notifications_enabled', False)
        settings = QSettings('rocker', 'SmallRSSReader')
        global_notifications = settings.value('notifications_enabled', False, type=bool)
        if global_notifications and notifications_enabled:
            title = f"New Article in {feed_title}"
            subtitle = entry.get('title', 'No Title')
            message = entry.get('summary', 'No summary available.')
            link = entry.get('link', '')
            self.notify_signal.emit(title, subtitle, message, link)
            logging.info(f"Sent notification for new article: {entry.get('title', 'No Title')}")
        else:
            logging.debug(f"Notification for feed '{feed_title}' is disabled.")

    def init_ui(self):
        self.setup_central_widget()
        self.init_menu()
        self.init_toolbar()
        self.statusBar().showMessage("Ready")
        self.update_refresh_timer()

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
        self.feeds_list.itemSelectionChanged.connect(self.load_articles)
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
        if item.data(0, Qt.UserRole) is None:
            self.handle_group_selection(item)
        else:
            self.handle_feed_selection(item)

    def init_articles_panel(self):
        self.articles_panel = QWidget()
        articles_layout = QVBoxLayout(self.articles_panel)
        articles_layout.setContentsMargins(2, 2, 2, 2)
        articles_layout.setSpacing(2)
        self.articles_tree = QTreeWidget()
        self.articles_tree.setHeaderLabels(['Title', 'Date'])  # Default columns
        # Simplified logic to always show all columns
        all_columns = ['Title', 'Date', 'Rating', 'Released', 'Genre', 'Director']
        self.articles_tree.setHeaderLabels(all_columns)

        articles_layout.addWidget(self.articles_tree)
        self.horizontal_splitter.addWidget(self.articles_panel)
        self.articles_tree.setColumnWidth(0, 200)
        self.articles_tree.setColumnWidth(1, 100)
        self.articles_tree.setColumnWidth(2, 80)
        self.articles_tree.setColumnWidth(3, 100)
        self.articles_tree.setColumnWidth(4, 100)
        self.articles_tree.setColumnWidth(5, 150)
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
        self.content_view = QWebEngineView()
        self.content_view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.content_view.setPage(WebEnginePage(self.content_view))
        content_layout.addWidget(self.content_view)
        self.main_splitter.addWidget(self.content_panel)

    def set_feed_new_icon(self, url, has_new):
        def update_icon(item):
            if item.data(0, Qt.UserRole) == url:
                if has_new:
                    self.set_feed_icon(item, url)  # Устанавливаем фавикон вместо синего кружка
                else:
                    item.setIcon(0, QIcon())
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
        if url in self.favicon_cache:
            item.setIcon(0, self.favicon_cache[url])
            return

        pixmap = fetch_favicon(url)
        if pixmap:
            icon = QIcon(pixmap)
            self.favicon_cache[url] = icon
            item.setIcon(0, icon)
        else:
            logging.info(f"No favicon found for {url}, using default icon.")
            self.favicon_cache[url] = QIcon()  # Cache default icon

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
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Cmd+Q" if sys.platform == 'darwin' else "Ctrl+Q")
        quit_action.triggered.connect(self.quit_app)
        file_menu.addAction(quit_action)

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
        toggle_columns_action.triggered.connect(self.toggle_column_visibility)
        view_menu.addAction(toggle_columns_action)

    def toggle_column_visibility(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Columns")
        layout = QVBoxLayout(dialog)

        checkboxes = []
        for i, column_name in enumerate(['Title', 'Date', 'Rating', 'Released', 'Genre', 'Director']):
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
        self.toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(self.toolbar)
        self.add_toolbar_buttons()
        self.toolbar.setVisible(True)

    def add_toolbar_buttons(self):
        self.add_new_feed_button()
        self.add_refresh_buttons()
        self.add_mark_unread_button()
        self.add_mark_feed_read_button()
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
        self.search_input.setFixedWidth(350)
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

    def eventFilter(self, source, event):
        if source == self.search_input:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.search_input.clear()
                return True
        return super().eventFilter(source, event)

    def update_refresh_timer(self):
        if self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.stop()
        self.auto_refresh_timer.timeout.connect(self.force_refresh_all_feeds)
        self.auto_refresh_timer.start(self.refresh_interval * 60 * 1000)
        logging.info(f"Refresh timer set to {self.refresh_interval} minutes.")

    def load_settings(self):
        settings = QSettings('rocker', 'SmallRSSReader')
        self.restore_geometry_and_state(settings)
        self.load_api_key_and_refresh_interval(settings)
        self.load_ui_visibility_settings(settings)
        self.load_movie_data_cache()
        self.load_group_settings(settings)
        self.load_read_articles()
        self.load_feeds()
        self.apply_font_size()
        self.tray_icon_enabled = settings.value('tray_icon_enabled', True, type=bool)
        self.init_tray_icon()
        QTimer.singleShot(1000, self.force_refresh_all_feeds)
        self.select_first_feed()

    def has_unread_articles(self, feed_data):
        for entry in feed_data.get('entries', []):
            article_id = self.get_article_id(entry)
            if article_id not in self.read_articles:
                return True
        return False

    def filter_articles_by_max_days(self, entries):
        max_days_ago = datetime.now() - timedelta(days=self.max_days)
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
        cache_path = get_user_data_path('movie_data_cache.json')
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    self.movie_data_cache = json.load(f)
                    logging.info(f"Loaded movie data cache with {len(self.movie_data_cache)} entries.")
            except json.JSONDecodeError:
                self.statusBar().showMessage("Failed to parse movie_data_cache.json.", 5000)
                logging.error("Failed to parse movie_data_cache.json.")
                self.movie_data_cache = {}
            except Exception as e:
                self.statusBar().showMessage(f"Unexpected error: {e}", 5000)
                logging.error(f"Unexpected error while loading movie data cache: {e}")
                self.movie_data_cache = {}
        else:
            self.movie_data_cache = {}
            self.save_movie_data_cache()
            logging.info("Created empty movie_data_cache.json.")

    def load_group_settings(self, settings):
        group_settings_path = get_user_data_path('group_settings.json')
        if os.path.exists(group_settings_path):
            try:
                with open(group_settings_path, 'r') as f:
                    self.group_settings = json.load(f)
                    logging.info(f"Loaded group settings with {len(self.group_settings)} groups.")
            except json.JSONDecodeError:
                self.statusBar().showMessage("Failed to parse group_settings.json.", 5000)
                logging.error("Failed to parse group_settings.json.")
                self.group_settings = {}
            except Exception as e:
                self.statusBar().showMessage(f"Unexpected error: {e}", 5000)
                logging.error(f"Unexpected error while loading group settings: {e}")
                self.group_settings = {}
        else:
            self.group_settings = {}
            self.save_group_settings()
            logging.info("Created empty group_settings.json.")

    def load_read_articles(self):
        try:
            read_articles_path = get_user_data_path('read_articles.json')
            if os.path.exists(read_articles_path):
                with open(read_articles_path, 'r') as f:
                    self.read_articles = set(json.load(f))
                    logging.info(f"Loaded {len(self.read_articles)} read articles.")
            else:
                self.read_articles = set()
                logging.info("Created empty read_articles.json.")
        except json.JSONDecodeError:
            self.statusBar().showMessage("Failed to parse read_articles.json.", 5000)
            logging.error("Failed to parse read_articles.json.")
            self.read_articles = set()
        except Exception as e:
            self.statusBar().showMessage(f"Unexpected error: {e}", 5000)
            logging.error(f"Unexpected error while loading read articles: {e}")
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

            # Ensure all threads are terminated and deleted
            if hasattr(self, 'threads'):
                for thread in self.threads:
                    if thread.isRunning():
                        logging.warning(f"Thread {thread} is still running. Attempting to stop.")
                        thread.quit()
                        thread.wait()
                        thread.deleteLater()
                        logging.info(f"Thread {thread} stopped and deleted.")

            if hasattr(self, 'populate_thread') and self.populate_thread.isRunning():
                self.populate_thread.quit()
                self.populate_thread.wait()
                self.populate_thread.deleteLater()
                logging.info("Terminated and deleted populate_thread during close event.")

            # Explicitly delete QWebEngineView to ensure cleanup
            if hasattr(self, 'content_view'):
                self.content_view.deleteLater()
                logging.info("Deleted QWebEngineView to ensure proper cleanup.")

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
        self.tray_icon = QSystemTrayIcon(self)
        if getattr(self, 'tray_icon_enabled', True):
            tray_icon_pixmap = QPixmap(resource_path('icons/rss_tray_icon.png'))
            self.tray_icon.setIcon(QIcon(tray_icon_pixmap))
            self.tray_icon.setToolTip("Small RSS Reader")
            self.tray_icon.show()
        else:
            transparent_pixmap = QPixmap(1, 1)
            transparent_pixmap.fill(Qt.transparent)
            self.tray_icon.setIcon(QIcon(transparent_pixmap))
            self.tray_icon.hide()
        self.tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show_window)
        self.tray_menu.addAction(show_action)
        refresh_action = QAction("Refresh All Feeds", self)
        refresh_action.triggered.connect(self.force_refresh_all_feeds)
        self.tray_menu.addAction(refresh_action)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.quit_app)
        self.tray_menu.addAction(exit_action)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
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
            cache_path = get_user_data_path('movie_data_cache.json')
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'w') as f:
                json.dump(self.movie_data_cache, f, indent=4)
            logging.info("Movie data cache saved successfully.")
        except Exception as e:
            logging.error(f"Failed to save movie data cache: {e}")

    def save_group_settings(self):
        try:
            group_settings_path = get_user_data_path('group_settings.json')
            os.makedirs(os.path.dirname(group_settings_path), exist_ok=True)
            with open(group_settings_path, 'w') as f:
                json.dump(self.group_settings, f, indent=4)
            logging.info("Group settings saved successfully.")
            self.data_changed = True  # Mark data as changed
        except Exception as e:
            logging.error(f"Failed to save group settings: {e}")

    def save_read_articles(self):
        try:
            read_articles_path = get_user_data_path('read_articles.json')
            os.makedirs(os.path.dirname(read_articles_path), exist_ok=True)
            with open(read_articles_path, 'w') as f:
                json.dump(list(self.read_articles), f, indent=4)
            logging.info(f"Saved {len(self.read_articles)} read articles.")
            self.data_changed = True  # Mark data as changed
        except Exception as e:
            logging.error(f"Failed to save read articles: {e}")

    def save_feeds(self):
        try:
            feeds_data = {
                'feeds': self.feeds,
                'column_widths': self.column_widths,
            }
            feeds_path = get_user_data_path('feeds.json')
            os.makedirs(os.path.dirname(feeds_path), exist_ok=True)
            with open(feeds_path, 'w') as f:
                json.dump(feeds_data, f, indent=4)
            logging.info("Feeds saved successfully.")
            self.data_changed = True  # Mark data as changed
            self.statusBar().showMessage("Feeds saved successfully.", 5000)
        except Exception as e:
            logging.error(f"Failed to save feeds: {e}")
            self.statusBar().showMessage("Error saving feeds. Check logs for details.", 5000)

    def toggle_toolbar_visibility(self):
        visible = self.toggle_toolbar_action.isChecked()
        self.toolbar.setVisible(visible)

    def toggle_statusbar_visibility(self):
        visible = self.toggle_statusbar_action.setChecked()
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
            self.save_group_setting(group_name, omdb_checkbox.isChecked(), notifications_checkbox.isChecked())

    def save_group_setting(self, group_name, omdb_enabled, notifications_enabled):
        self.group_settings[group_name] = {
            'omdb_enabled': omdb_enabled,
            'notifications_enabled': notifications_enabled
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
        """Loads feeds and sets favicons efficiently."""
        feeds_path = get_user_data_path('feeds.json')
        if os.path.exists(feeds_path):
            try:
                with open(feeds_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.feeds = data.get('feeds', [])
                        self.column_widths = data.get('column_widths', {})
                        logging.info(f"Loaded {len(self.feeds)} feeds.")
                    elif isinstance(data, list):
                        self.feeds = data
                        self.column_widths = {}
                    else:
                        self.feeds = []
                        self.column_widths = {}
                self.prune_old_entries()
            except json.JSONDecodeError:
                self.statusBar().showMessage("Failed to parse feeds.json.", 5000)
                logging.error("Failed to parse feeds.json.")
                self.feeds = []
                self.column_widths = {}
            except Exception as e:
                self.statusBar().showMessage(f"Unexpected error: {e}", 5000)
                logging.error(f"Unexpected error while loading feeds: {e}")
                self.feeds = []
                self.column_widths = {}
        else:
            self.column_widths = {}
            self.feeds = [
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
            self.mark_feeds_dirty()
            self.save_feeds()
            logging.info("Created default feeds.json with initial feeds.")
        self.feeds_list.clear()
        # Group feeds by domain
        domain_feeds = {}
        for feed in self.feeds:
            parsed_url = urlparse(feed['url'])
            domain = parsed_url.netloc or 'Unknown Domain'
            domain_feeds.setdefault(domain, []).append(feed)
        for domain, feeds in domain_feeds.items():
            if len(feeds) == 1:
                feed_data = feeds[0]
                feed_item = QTreeWidgetItem(self.feeds_list)
                feed_item.setText(0, feed_data['title'])
                feed_item.setData(0, Qt.UserRole, feed_data['url'])
                if self.has_unread_articles(feed_data):
                    font = feed_item.font(0)
                    font.setBold(True)
                    feed_item.setFont(0, font)
                self.set_feed_icon(feed_item, feed_data['url'])  # Set favicon for standalone feed
            else:
                group_name = self.group_name_mapping.get(domain, domain)
                group_item = QTreeWidgetItem(self.feeds_list)
                group_item.setText(0, group_name)
                font = group_item.font(0)
                font.setBold(True)
                group_item.setFont(0, font)
                self.set_feed_icon(group_item, feeds[0]['url'])  # Set favicon for the group
                for feed_data in feeds:
                    feed_item = QTreeWidgetItem(group_item)
                    feed_item.setText(0, feed_data['title'])
                    feed_item.setData(0, Qt.UserRole, feed_data['url'])
                    if self.has_unread_articles(feed_data):
                        font = feed_item.font(0)
                        font.setBold(True)
                        feed_item.setFont(0, font)
        self.feeds_list.expandAll()

    def backup_to_icloud(self):
        backup_folder = os.path.join(Path.home(), "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup")
        os.makedirs(backup_folder, exist_ok=True)
        files_to_backup = ['feeds.json', 'read_articles.json', 'group_settings.json', 'movie_data_cache.json']
        for filename in files_to_backup:
            source = get_user_data_path(filename)
            dest = os.path.join(backup_folder, filename)
            if os.path.exists(source):
                try:
                    shutil.copy2(source, dest)
                    logging.info(f"Backed up {filename} to iCloud.")
                except Exception as e:
                    logging.error(f"Failed to backup {filename}: {e}")
        self.statusBar().showMessage("Backup to iCloud completed successfully.", 5000)

    def restore_from_icloud(self):
        backup_folder = os.path.join(Path.home(), "Library", "Mobile Documents", "com~apple~CloudDocs", "SmallRSSReaderBackup")
        files_to_restore = ['feeds.json', 'read_articles.json', 'group_settings.json', 'movie_data_cache.json']
        for filename in files_to_restore:
            backup_file = os.path.join(backup_folder, filename)
            if os.path.exists(backup_file):
                dest = get_user_data_path(filename)
                try:
                    shutil.copy2(backup_file, dest)
                    logging.info(f"Restored {filename} from iCloud.")
                except Exception as e:
                    logging.error(f"Failed to restore {filename}: {e}")
        self.load_group_settings(QSettings('rocker', 'SmallRSSReader'))
        self.load_read_articles()
        self.load_feeds()
        self.statusBar().showMessage("Restore from iCloud completed successfully.", 5000)

    def save_feeds(self):
        try:
            feeds_data = {
                'feeds': self.feeds,
                'column_widths': self.column_widths,
            }
            feeds_path = get_user_data_path('feeds.json')
            os.makedirs(os.path.dirname(feeds_path), exist_ok=True)
            with open(feeds_path, 'w') as f:
                json.dump(feeds_data, f, indent=4)
            logging.info("Feeds saved successfully.")
            self.data_changed = True  # Mark data as changed
            self.statusBar().showMessage("Feeds saved successfully.", 5000)
        except Exception as e:
            logging.error(f"Failed to save feeds: {e}")
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
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        if item.data(0, Qt.UserRole) is None:
            self.handle_group_selection(item)
            return
        url = item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
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
            self.populate_thread.quit()
            self.populate_thread.wait()
            logging.info("Previous PopulateArticlesThread terminated.")

        # Start a new thread
        self.populate_thread = PopulateArticlesThread(entries, self.read_articles, self.max_days)
        self.populate_thread.articles_ready.connect(self.on_articles_ready)
        self.populate_thread.start()

    def on_articles_ready(self, filtered_entries, article_id_to_item):
        self.current_entries = filtered_entries
        self.article_id_to_item = article_id_to_item
        self.populate_articles_ui()

    def populate_articles_ui(self):
        """Populate the articles UI with the current feed's articles."""
        self.articles_tree.clear()
        current_feed = self.get_current_feed()
        if not current_feed:
            return

        visible_columns = current_feed.get('visible_columns', [True] * 6)
        for i, visible in enumerate(visible_columns):
            self.articles_tree.setColumnHidden(i, not visible)

        for entry in current_feed.get('entries', []):
            article_id = self.get_article_id(entry)
            is_unread = article_id not in self.read_articles

            item = QTreeWidgetItem(self.articles_tree)
            item.setText(0, entry.get('title', 'No Title'))
            item.setData(0, Qt.UserRole, entry)

            if is_unread:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)

            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                date_obj = datetime(*date_struct[:6])
                item.setText(1, date_obj.strftime('%Y-%m-%d'))

            # Populate OMDB-related columns if data exists
            movie_data = entry.get('movie_data', {})
            if movie_data:
                item.setText(2, movie_data.get('imdbrating', 'N/A'))
                item.setText(5, movie_data.get('director', ''))

        self.articles_tree.sortItems(1, Qt.DescendingOrder)

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
        selected_items = self.articles_tree.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        entry = item.data(0, Qt.UserRole)
        if not entry:
            return
        title = entry.get('title', 'No Title')
        date_formatted = item.text(1)
        if 'content' in entry and entry['content']:
            content = entry['content'][0].get('value', '')
        elif 'summary' in entry:
            content = entry.get('summary', 'No content available.')
        else:
            content = ''
        images_html = ''
        search_text = self.search_input.text().lower().strip()
        if search_text:
            title = self.highlight_text(title, search_text)
            content = self.highlight_text(content, search_text)
        if 'media_content' in entry:
            for media in entry.get('media_content', []):
                img_url = media.get('url')
                if img_url:
                    images_html += f'<img src="{img_url}" alt="" /><br/>'
        elif 'media_thumbnail' in entry:
            for media in entry.get('media_thumbnail', []):
                img_url = media.get('url')
                if img_url:
                    images_html += f'<img src="{img_url}" alt="" /><br/>'
        elif 'links' in entry:
            for link in entry.get('links', []):
                if link.get('rel') == 'enclosure' and 'image' in link.get('type', ''):
                    img_url = link.get('href')
                    if img_url:
                        images_html += f'<img src="{img_url}" alt="" /><br/>'
        link = entry.get('link', '')
        movie_data = entry.get('movie_data', {})
        movie_info_html = ''
        if movie_data:
            poster_url = movie_data.get('poster', '')
            if poster_url and poster_url != 'N/A':
                movie_info_html += f'<img src="{poster_url}" alt="Poster" style="max-width:200px;" /><br/>'
            details = [
                ('Released', movie_data.get('released', '')),
                ('Plot', movie_data.get('plot', '')),
                ('Writer', movie_data.get('writer', '')),
                ('Actors', movie_data.get('actors', '')),
                ('Language', movie_data.get('language', '')),
                ('Country', movie_data.get('country', '')),
                ('Awards', movie_data.get('awards', '')),
                ('DVD Release', movie_data.get('dvd', '')),
                ('Box Office', movie_data.get('boxoffice', '')),
            ]
            for label, value in details:
                if value and value != 'N/A':
                    movie_info_html += f'<p><strong>{label}:</strong> {value}</p>'
            ratings = movie_data.get('ratings', [])
            if ratings:
                ratings_html = '<ul>'
                for rating in ratings:
                    ratings_html += f"<li>{rating.get('Source')}: {rating.get('Value')}</li>"
                ratings_html += '</ul>'
                movie_info_html += f'<p><strong>Ratings:</strong>{ratings_html}</p>'
        styles = """
        <style>
        body { max-width: 800px; margin: auto; padding: 5px; font-family: Helvetica, Arial, sans-serif; font-size: 16px; line-height: 1.6; color: #333; background-color: #f9f9f9; }
        h3 { font-size: 18px; }
        p { margin: 0 0 5px; }
        img { max-width: 100%; height: auto; display: block; margin: 5px 0; }
        a { color: #1e90ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        blockquote { margin: 5px 0; padding: 5px 20px; background-color: #f0f0f0; border-left: 5px solid #ccc; }
        code { font-family: monospace; background-color: #f0f0f0; padding: 2px 4px; border-radius: 4px; }
        pre { background-color: #f0f0f0; padding: 10px; overflow: auto; border-radius: 4px; }
        </style>
        """
        read_more = f'<p><a href="{link}" target="_self" rel="noopener noreferrer">Read more</a></p>' if link else ''
        html_content = f"{styles}<h3>{title}</h3>{images_html}{content}{movie_info_html}{read_more}"
        current_feed_item = self.feeds_list.currentItem()
        feed_url = current_feed_item.data(0, Qt.UserRole) if current_feed_item else ''  # Ensure feed_url is defined
        self.content_view.setHtml(html_content, baseUrl=QUrl(feed_url))
        self.statusBar().showMessage(f"Displaying article: {title}", 5000)
        article_id = item.data(0, Qt.UserRole + 1)
        if article_id not in self.read_articles:
            self.read_articles.add(article_id)
            font = item.font(0)
            font.setBold(False)  # Remove bold font for read articles
            item.setFont(0, font)
            item.setIcon(0, QIcon())  # Remove unread icon
            logging.debug(f"Marked article as read: {title}")

    def highlight_text(self, text, search_text):
        if not search_text:
            return text
        highlighted = f'<span style="background-color: yellow;">{search_text}</span>'
        return re.sub(re.escape(search_text), highlighted, text, flags=re.IGNORECASE)

    def add_article_to_tree(self, entry):
        """Add an article to the articles tree."""
        title = entry.get('title', 'No Title')
        item = ArticleTreeWidgetItem([title, '', '', '', '', ''])
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
        article_id = self.get_article_id(entry)
        item.setData(0, Qt.UserRole + 1, article_id)
        item.setData(0, Qt.UserRole, entry)

        # Mark unread articles with bold font and an icon
        if article_id not in self.read_articles:
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            unread_icon = QIcon(resource_path('icons/unread_icon.png'))  # Ensure this icon exists
            item.setIcon(0, unread_icon)
        else:
            item.setIcon(0, QIcon())  # No icon for read articles

        # Use cached favicon for the feed
        current_feed_item = self.feeds_list.currentItem()
        if current_feed_item:
            feed_url = current_feed_item.data(0, Qt.UserRole)
            if feed_url in self.favicon_cache:
                item.setIcon(0, self.favicon_cache[feed_url])

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

    def update_movie_info(self, index, movie_data):
        if index < 0 or index >= len(self.current_entries):
            logging.error(f"update_movie_info: index {index} out of range.")
            return
        entry = self.current_entries[index]
        article_id = self.get_article_id(entry)
        if article_id not in self.article_id_to_item:
            logging.warning(f"Skipped update: Article ID {article_id} not found.")
            return
        item = self.article_id_to_item.get(article_id)
        if item:
            imdb_rating = movie_data.get('imdbrating', 'N/A')
            rating_value = self.parse_rating(imdb_rating)
            item.setData(2, Qt.UserRole, rating_value)
            item.setText(2, imdb_rating)
            released = movie_data.get('released', '')
            release_date = self.parse_release_date(released)
            item.setData(3, Qt.UserRole, release_date)
            item.setText(3, release_date.strftime('%d %b %Y') if release_date != datetime.min else '')
            genre = movie_data.get('genre', '')
            director = movie_data.get('director', '')
            item.setText(4, genre)
            item.setText(5, director)
            entry['movie_data'] = movie_data
        else:
            logging.warning(f"No QTreeWidgetItem found for article ID: {article_id}")

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
        url = item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
        if not feed_data or 'entries' not in feed_data:
            self.statusBar().showMessage("No articles found for the selected feed.", 5000)
            return
        reply = QMessageBox.question(self, 'Mark Feed Unread',
                                     'Are you sure you want to mark all articles in this feed as unread?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for entry in feed_data['entries']:
                article_id = self.get_article_id(entry)
                if article_id in self.read_articles:
                    self.read_articles.remove(article_id)
            self.load_articles()
            self.populate_articles_ui()
            logging.info(f"Marked feed '{feed_data['title']}' as unread.")

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
            if current_feed_item and current_feed_item.data(0, Qt.UserRole) == url:
                self.populate_articles_ui()  # Corrected method call
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
        remove_feed_action.triggered.connect(self.remove_feed)
        menu.addAction(remove_feed_action)
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

### Main Function ###

def main():
    parser = argparse.ArgumentParser(description="Small RSS Reader")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(application_path)
    logging_level = logging.DEBUG if args.debug else logging.INFO
    log_path = get_user_data_path('rss_reader.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        level=logging_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout)
        ]
    )
    app = QApplication(sys.argv)
    app.setOrganizationName("rocker")
    app.setApplicationName("SmallRSSReader")
    app.setApplicationDisplayName("Small RSS Reader")
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
    splash.showMessage("Loading settings...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    QApplication.processEvents()
    reader.load_settings()
    splash.showMessage("Loading feeds...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    QApplication.processEvents()
    reader.load_feeds()
    splash.showMessage("Refreshing feeds...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    QApplication.processEvents()
    splash.showMessage("Finalizing...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    QApplication.processEvents()
    splash.finish(reader)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
