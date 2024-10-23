import sys
import os
import json
import logging
import feedparser
import datetime
import signal
import re
import unicodedata
import hashlib
import argparse
import ctypes
import webbrowser

from urllib.parse import urlparse
from omdbapi.movie_search import GetMovie
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QSplitter, QMessageBox, QAction, QFileDialog, QMenu, QToolBar,
    QHeaderView, QDialog, QFormLayout, QSizePolicy, QStyle, QSpinBox,
    QAbstractItemView, QInputDialog, QDialogButtonBox, QCheckBox,
    QSplashScreen
)
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QFontComboBox

from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from PyQt5.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QUrl, QSettings, QSize, QEvent, QObject, QRunnable, QThreadPool, pyqtSlot
)
from PyQt5.QtGui import (
    QDesktopServices, QFont, QIcon, QPixmap, QPainter, QBrush, QColor, QTransform
)
from pathlib import Path

### Helper Functions ###

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # When not frozen, use the directory of the script
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
        # Running in a bundle
        if sys.platform == "darwin":
            return os.path.join(Path.home(), "Library", "Application Support", "SmallRSSReader", filename)
        elif sys.platform == "win32":
            return os.path.join(os.getenv('APPDATA'), "SmallRSSReader", filename)
        else:
            return os.path.join(Path.home(), ".smallrssreader", filename)
    else:
        # Running in development
        return os.path.join(os.path.abspath("."), filename)

### Helper Classes ###

class FetchFeedThread(QThread):
    """Thread for fetching RSS feed data asynchronously."""
    feed_fetched = pyqtSignal(object, object)  # Emits (url, feed)

    def __init__(self, url):
        super().__init__()
        self.url = url  # Ensure self.url is defined

    def run(self):
        logging.debug(f"Fetching feed: {self.url}")
        try:
            feed = feedparser.parse(self.url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            self.feed_fetched.emit(self.url, feed)
            logging.debug(f"Successfully fetched feed: {self.url}")
        except Exception as e:
            logging.error(f"Failed to fetch feed {self.url}: {e}")
            self.feed_fetched.emit(self.url, None)

class FetchMovieDataThread(QThread):
    """Thread for fetching movie data from OMDb API asynchronously."""
    movie_data_fetched = pyqtSignal(int, dict)

    def __init__(self, entries, api_key, cache):
        super().__init__()
        self.entries = entries
        self.api_key = api_key
        self.movie_data_cache = cache

    def run(self):
        if not self.api_key:
            logging.warning("OMDb API key not provided. Skipping movie data fetching.")
            return
        for index, entry in enumerate(self.entries):
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
        """Extracts the movie title from the RSS entry title."""
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
        """Fetches movie data from OMDb API."""
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
    """Custom QTreeWidgetItem to handle sorting of different data types."""

    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        data1 = self.data(column, Qt.UserRole)
        data2 = other.data(column, Qt.UserRole)

        if data1 is None or data1 == '':
            data1 = self.text(column)
        if data2 is None or data2 == '':
            data2 = other.text(column)

        if isinstance(data1, datetime.datetime) and isinstance(data2, datetime.datetime):
            return data1 < data2
        elif isinstance(data1, float) and isinstance(data2, float):
            return data1 < data2
        else:
            return str(data1) < str(data2)

class FeedsTreeWidget(QTreeWidget):
    """Custom QTreeWidget to handle drag-and-drop within groups only."""

    def dropEvent(self, event):
        source_item = self.currentItem()
        target_item = self.itemAt(event.pos())

        # Prevent dropping a feed into a different group
        if target_item and target_item.parent() != source_item.parent():
            QMessageBox.warning(self, "Invalid Move", "Feeds can only be moved within their own groups.")
            event.ignore()
            return
        super().dropEvent(event)

class WebEnginePage(QWebEnginePage):
    """Custom QWebEnginePage to handle link clicks in the content view."""

    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if _type == QWebEnginePage.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return True

class AddFeedDialog(QDialog):
    """Dialog to add a new feed with a custom name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Feed")
        self.setModal(True)
        self.setFixedSize(400, 150)
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)

        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("Enter custom feed name")
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
        """Override accept to save settings before closing the dialog."""
        super().accept()

class SettingsDialog(QDialog):
    """Dialog for application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)

        # OMDb API Key Input
        self.api_key_input = QLineEdit(self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setText(self.parent.api_key)
        layout.addRow("OMDb API Key:", self.api_key_input)

        self.api_key_notice = QLabel()
        self.api_key_notice.setStyleSheet("color: red;")
        self.update_api_key_notice()
        layout.addRow("", self.api_key_notice)

        # Refresh Interval Input
        self.refresh_interval_input = QSpinBox(self)
        self.refresh_interval_input.setRange(1, 1440)
        self.refresh_interval_input.setValue(self.parent.refresh_interval)
        layout.addRow("Refresh Interval (minutes):", self.refresh_interval_input)

        # **Font Selection Widgets**
        self.font_name_combo = QFontComboBox(self)
        self.font_name_combo.setCurrentFont(self.parent.default_font)
        layout.addRow("Font Name:", self.font_name_combo)

        self.font_size_spin = QSpinBox(self)
        self.font_size_spin.setRange(8, 48)
        self.font_size_spin.setValue(self.parent.current_font_size)
        layout.addRow("Font Size:", self.font_size_spin)

        # **Add Global Notifications Checkbox**
        self.global_notifications_checkbox = QCheckBox("Enable Notifications", self)
        settings = QSettings('rocker', 'SmallRSSReader')
        global_notifications = settings.value('notifications_enabled', True, type=bool)
        self.global_notifications_checkbox.setChecked(global_notifications)
        layout.addRow("Global Notifications:", self.global_notifications_checkbox)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def update_api_key_notice(self):
        if not self.parent.api_key:
            self.api_key_notice.setText("Ratings feature is disabled without an API key.")
        else:
            self.api_key_notice.setText("")

    def save_settings(self):
        """Saves the settings when the user clicks 'Save'."""
        # Save existing settings
        api_key = self.api_key_input.text().strip()
        refresh_interval = self.refresh_interval_input.value()
        font_name = self.font_name_combo.currentFont().family()
        font_size = self.font_size_spin.value()
        self.parent.api_key = api_key
        self.parent.refresh_interval = refresh_interval
        self.parent.current_font_size = font_size
        self.parent.default_font = QFont(font_name, font_size)

        # Save Global Notifications Setting
        notifications_enabled = self.global_notifications_checkbox.isChecked()

        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('omdb_api_key', api_key)
        settings.setValue('refresh_interval', refresh_interval)
        settings.setValue('font_name', font_name)
        settings.setValue('font_size', font_size)
        settings.setValue('notifications_enabled', notifications_enabled)

        self.parent.update_refresh_timer()
        self.parent.apply_font_size()
        self.update_api_key_notice()

    def accept(self):
        """Override accept to save settings before closing the dialog."""
        self.save_settings()
        super().accept()

### Worker Classes for QThreadPool ###

class Worker(QObject):
    feed_fetched = pyqtSignal(str, object)  # Emits (url, feed)

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

### Main Application Class ###

class RSSReader(QMainWindow):
    """Main application class for the RSS Reader."""

    # Define icon constants
    REFRESH_SELECTED_ICON = QStyle.SP_BrowserReload
    REFRESH_ALL_ICON = QStyle.SP_DialogResetButton  # Use a different standard icon

    # Define a new signal for notifications
    notify_signal = pyqtSignal(str, str, str, str)  # title, subtitle, message, link

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Small RSS Reader")
        self.resize(1200, 800)
        self.initialize_variables()
        self.init_ui()
        self.load_group_names()
        self.load_settings()
        self.load_read_articles()
        self.load_feeds()
        # Start refresh after event loop starts to prevent blocking UI
        QTimer.singleShot(0, self.force_refresh_all_feeds)
        self.select_first_feed()
        self.active_feed_threads = 0 

        # Initialize QSystemTrayIcon for native notifications
        self.init_tray_icon()
        # Connect the notification signal to the slot
        self.notify_signal.connect(self.show_notification)

    def initialize_variables(self):
        """Initializes all variables."""
        self.feeds = []
        self.current_entries = []
        self.api_key = ''
        self.refresh_interval = 60  # Default refresh interval in minutes
        self.movie_data_cache = {}
        self.read_articles = set()
        self.threads = []
        self.article_id_to_item = {}  # Mapping from article_id to QTreeWidgetItem
        self.group_name_mapping = {}  # Mapping from domain to custom group name
        self.group_settings = {}  # Group-specific settings
        self.is_refreshing = False
        self.is_quitting = False  # Flag to indicate if the app is quitting
        self.refresh_icon_angle = 0
        self.icon_rotation_timer = QTimer()
        self.icon_rotation_timer.timeout.connect(self.rotate_refresh_icon)
        self.auto_refresh_timer = QTimer()
        self.force_refresh_icon_pixmap = None  # To store the icon pixmap

        # **Font Variables**
        self.default_font_size = 14  # Default font size
        self.default_font = QFont("Arial", self.default_font_size)
        settings = QSettings('rocker', 'SmallRSSReader')
        self.current_font_size = settings.value('font_size', self.default_font_size, type=int)
        font_name = settings.value('font_name', self.default_font.family(), type=str)
        self.default_font = QFont(font_name, self.current_font_size)

        # **Initialize Thread Pool**
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(8)  # Limit to 8 concurrent threads

    def quit_app(self):
        """Handles the quitting of the application."""
        self.is_quitting = True
        self.close()

    def save_font_size(self):
        """Saves the current font size to settings."""
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('font_size', self.current_font_size)

    def apply_font_size(self):
        """Applies the current font name and size to relevant widgets."""
        font = QFont(self.default_font.family(), self.current_font_size)
        self.articles_tree.setFont(font)
        self.content_view.setFont(font)

        # Optionally, apply to other widgets like feed list, toolbar, etc.
        # self.feeds_list.setFont(font)
        # self.toolbar.setFont(font)

        # **Update Status Bar with Current Font Information**
        self.statusBar().showMessage(f"Font: {font.family()}, Size: {font.pointSize()}")


    def increase_font_size(self):
        """Increases the font size."""
        if self.current_font_size < 30:  # Maximum font size limit
            self.current_font_size += 1
            self.apply_font_size()
            self.save_font_size()
            logging.info(f"Increased font size to {self.current_font_size}.")

    def decrease_font_size(self):
        """Decreases the font size."""
        if self.current_font_size > 8:  # Minimum font size limit
            self.current_font_size -= 1
            self.apply_font_size()
            self.save_font_size()
            logging.info(f"Decreased font size to {self.current_font_size}.")

    def reset_font_size(self):
        """Resets the font size to default."""
        self.current_font_size = self.default_font_size
        self.apply_font_size()
        self.save_font_size()
        logging.info(f"Reset font size to default ({self.default_font_size}).")

    def show_notification(self, title, subtitle, message, link):
        """
        Slot to display native macOS notifications using QSystemTrayIcon.

        Parameters:
        - title (str): The title of the notification.
        - subtitle (str): The subtitle of the notification (not directly supported, included in the message).
        - message (str): The body of the notification.
        - link (str): The URL to open when the notification is clicked.
        """
        logging.debug(
            f"Displaying notification: Title='{title}', Subtitle='{subtitle}', Message='{message}', Link='{link}'"
        )

        # Combine subtitle and message since QSystemTrayIcon.showMessage doesn't support subtitles
        full_message = f"{subtitle}\n\n{message}" if subtitle else message

        # Display the notification
        self.tray_icon.showMessage(
            title,
            full_message,
            QSystemTrayIcon.Information,
            5000  # Duration in milliseconds (e.g., 5000ms = 5 seconds)
        )

        # Store the link to handle tray icon clicks
        self.last_notification_link = link

        # Connect the activated signal to handle tray icon clicks
        # Disconnect previous connections to prevent multiple connections
        try:
            self.tray_icon.activated.disconnect()
        except TypeError:
            # If no previous connections, pass
            pass
        self.tray_icon.activated.connect(self.handle_tray_icon_click)

    def handle_tray_icon_click(self, reason):
        """
        Handles clicks on the tray icon to open the associated link.

        Parameters:
        - reason (QSystemTrayIcon.ActivationReason): The reason for activation.
        """
        if reason == QSystemTrayIcon.Trigger:
            if hasattr(self, 'last_notification_link') and self.last_notification_link:
                webbrowser.open(self.last_notification_link)
                logging.debug(f"Opened link from notification: {self.last_notification_link}")
                # Clear the link after opening
                self.last_notification_link = None
            else:
                # Optionally, open the main window if no link is associated
                self.show_window()
                logging.debug("No link associated with the notification. Restoring main window.")

    def send_notification(self, feed_title, entry):
        """Emit a signal to show a macOS notification for a new article."""
        group_name = self.get_group_name_for_feed(entry.get('link', ''))
        group_settings = self.group_settings.get(group_name, {'notifications_enabled': True})
        notifications_enabled = group_settings.get('notifications_enabled', True)

        # Check global notification setting
        settings = QSettings('rocker', 'SmallRSSReader')
        global_notifications = settings.value('notifications_enabled', True, type=bool)

        if global_notifications and notifications_enabled:
            title = f"New Article in {feed_title}"
            subtitle = entry.get('title', 'No Title')
            message = entry.get('summary', 'No summary available.')
            link = entry.get('link', '')
            # Emit the notification signal
            self.notify_signal.emit(title, subtitle, message, link)
            logging.info(f"Sent notification for new article: {entry.get('title', 'No Title')}")

    def init_ui(self):
        """Initializes the main UI components."""
        self.setup_central_widget()
        self.init_menu()
        self.init_toolbar()
        self.statusBar().showMessage("Ready")
        self.update_refresh_timer()

    def setup_central_widget(self):
        """Sets up the central widget and layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setHandleWidth(1)
        self.main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #ccc;
                width: 1px;
            }
        """)
        main_layout.addWidget(self.main_splitter)

        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        self.horizontal_splitter.setHandleWidth(1)
        self.horizontal_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #ccc;
                width: 1px;
            }
        """)
        self.main_splitter.addWidget(self.horizontal_splitter)

        self.init_feeds_panel()
        self.init_articles_panel()
        self.init_content_panel()

        # Set stretch factors for splitters
        self.horizontal_splitter.setStretchFactor(0, 1)
        self.horizontal_splitter.setStretchFactor(1, 3)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)

    def init_feeds_panel(self):
        """Initializes the feeds panel."""
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
        feeds_layout.addWidget(self.feeds_list)

        self.feeds_panel.setMinimumWidth(200)
        self.feeds_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.horizontal_splitter.addWidget(self.feeds_panel)

    def init_articles_panel(self):
        """Initializes the articles panel."""
        self.articles_panel = QWidget()
        articles_layout = QVBoxLayout(self.articles_panel)
        articles_layout.setContentsMargins(2, 2, 2, 2)
        articles_layout.setSpacing(2)

        self.articles_tree = QTreeWidget()
        self.articles_tree.setHeaderLabels(['Title', 'Date', 'Rating', 'Released', 'Genre', 'Director'])

        # Set all columns to Interactive to allow manual resizing
        header = self.articles_tree.header()
        header.setSectionResizeMode(QHeaderView.Interactive)

        # **Set Default Column Widths**
        self.articles_tree.setColumnWidth(0, 200)  # Title column
        self.articles_tree.setColumnWidth(1, 100)  # Date column
        self.articles_tree.setColumnWidth(2, 80)   # Rating column
        self.articles_tree.setColumnWidth(3, 100)  # Released column
        self.articles_tree.setColumnWidth(4, 100)  # Genre column
        self.articles_tree.setColumnWidth(5, 150)  # Director column

        self.articles_tree.setSortingEnabled(True)
        self.articles_tree.header().setSectionsClickable(True)
        self.articles_tree.header().setSortIndicatorShown(True)
        self.articles_tree.itemSelectionChanged.connect(self.display_content)
        self.articles_tree.header().sortIndicatorChanged.connect(self.on_sort_changed)

        # **New Connection Added Below**
        self.articles_tree.itemDoubleClicked.connect(self.open_article_url)

        articles_layout.addWidget(self.articles_tree)

        self.articles_tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.articles_tree.header().customContextMenuRequested.connect(self.show_header_menu)

        self.horizontal_splitter.addWidget(self.articles_panel)


    def init_content_panel(self):
        """Initializes the content panel."""
        self.content_panel = QWidget()
        content_layout = QVBoxLayout(self.content_panel)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(2)

        self.content_view = QWebEngineView()
        self.content_view.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.content_view.setPage(WebEnginePage(self.content_view))
        content_layout.addWidget(self.content_view)

        self.main_splitter.addWidget(self.content_panel)

    def init_menu(self):
        """Initializes the menu bar."""
        menu = self.menuBar()

        # File menu
        file_menu = menu.addMenu("File")
        self.add_file_menu_actions(file_menu)

        # View menu
        view_menu = menu.addMenu("View")
        self.add_view_menu_actions(view_menu)

        # Add Font Size Submenu
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

        # **Add Quit Action with Cmd+Q Shortcut**
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Cmd+Q" if sys.platform == 'darwin' else "Ctrl+Q")
        quit_action.triggered.connect(self.quit_app)
        file_menu.addAction(quit_action)


    def open_article_url(self, item, column):
        """
        Opens the article's URL in the default web browser when an article is double-clicked.

        Parameters:
            item (QTreeWidgetItem): The article item that was double-clicked.
            column (int): The column that was double-clicked.
        """
        # Retrieve the entry associated with the item
        entry = item.data(0, Qt.UserRole)
        if not entry:
            QMessageBox.warning(self, "No Entry Data", "No data available for the selected article.")
            return

        # Get the link from the entry
        url = entry.get('link', '')
        if not url:
            QMessageBox.warning(self, "No URL", "No URL found for the selected article.")
            return

        # Validate the URL
        parsed_url = urlparse(url)
        if not parsed_url.scheme.startswith('http'):
            QMessageBox.warning(self, "Invalid URL", "The URL is invalid or unsupported.")
            return

        # Open the URL in the default web browser
        QDesktopServices.openUrl(QUrl(url))

    def add_file_menu_actions(self, file_menu):
        """Adds actions to the File menu."""
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
        """Adds actions to the View menu."""
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

    def init_toolbar(self):
        """Initializes the toolbar."""
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(self.toolbar)

        self.add_toolbar_buttons()

        self.toolbar.setVisible(True)

    def add_toolbar_buttons(self):
        """Adds buttons to the toolbar."""
        self.add_new_feed_button()
        self.add_refresh_buttons()
        self.add_mark_unread_button()
        self.add_search_widget()

    def add_new_feed_button(self):
        """Adds the 'New Feed' button to the toolbar."""
        new_feed_icon = self.style().standardIcon(QStyle.SP_FileDialogNewFolder)
        self.new_feed_button = QPushButton("New Feed")
        self.new_feed_button.setIcon(new_feed_icon)
        self.new_feed_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; /* Green */
                color: white;
                border: none;
                padding: 5px 10px;
                text-align: center;
                text-decoration: none;
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
        """Adds the refresh buttons to the toolbar."""
        # Refresh Selected Feed Button
        refresh_selected_icon = self.style().standardIcon(self.REFRESH_SELECTED_ICON)
        refresh_action = QAction(refresh_selected_icon, "Refresh Selected Feed", self)
        refresh_action.triggered.connect(self.refresh_feed)
        self.toolbar.addAction(refresh_action)

        # Refresh All Feeds Button
        force_refresh_icon = self.style().standardIcon(self.REFRESH_ALL_ICON)
        self.force_refresh_action = QAction(force_refresh_icon, "Refresh All Feeds", self)
        self.force_refresh_action.triggered.connect(self.force_refresh_all_feeds)
        self.toolbar.addAction(self.force_refresh_action)
        self.force_refresh_icon_pixmap = force_refresh_icon.pixmap(24, 24)

    def add_mark_unread_button(self):
        """Adds the 'Mark Feed Unread' button to the toolbar."""
        mark_unread_icon = self.style().standardIcon(QStyle.SP_DialogCancelButton)
        mark_unread_action = QAction(mark_unread_icon, "Mark Feed Unread", self)
        mark_unread_action.triggered.connect(self.mark_feed_unread)
        self.toolbar.addAction(mark_unread_action)

    def add_search_widget(self):
        """Adds the search widget to the toolbar."""
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search articles...")
        self.search_input.setFixedWidth(300)  # Set the width of the search input
        self.search_input.textChanged.connect(self.filter_articles)
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)  # Remove spacing
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addStretch()  # Add stretch to align to the left
        search_widget = QWidget()
        search_widget.setLayout(search_layout)
        self.toolbar.addWidget(search_widget)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar.addWidget(spacer)

    def update_refresh_timer(self):
        """Updates the refresh timer based on the refresh interval."""
        if self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.stop()
        self.auto_refresh_timer.timeout.connect(self.force_refresh_all_feeds)
        self.auto_refresh_timer.start(self.refresh_interval * 60 * 1000)
        logging.info(f"Refresh timer set to {self.refresh_interval} minutes.")

    def load_settings(self):
        """Loads application settings."""
        settings = QSettings('rocker', 'SmallRSSReader')
        self.restore_geometry_and_state(settings)
        self.load_api_key_and_refresh_interval(settings)
        self.load_ui_visibility_settings(settings)
        self.load_movie_data_cache()
        self.load_group_settings(settings)
        self.load_read_articles()
        self.load_feeds()
        self.apply_font_size()  # Apply font settings after loading settings

        # Start refresh after event loop starts to prevent blocking UI
        QTimer.singleShot(0, self.force_refresh_all_feeds)

        self.select_first_feed()

    def restore_geometry_and_state(self, settings):
        """Restores the window geometry and state."""
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
        
        # Re-apply Interactive Resize Mode After Restoring Header State
        header = self.articles_tree.header()
        for i in range(header.count()):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            logging.debug(f"Set column {i} resize mode to Interactive.")


    def load_api_key_and_refresh_interval(self, settings):
        """Loads the API key and refresh interval."""
        self.api_key = settings.value('omdb_api_key', '')
        refresh_interval = settings.value('refresh_interval', 60)
        try:
            self.refresh_interval = int(refresh_interval)
        except ValueError:
            self.refresh_interval = 60
        self.update_refresh_timer()

    def load_ui_visibility_settings(self, settings):
        """Loads UI element visibility settings."""
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
        """Loads the movie data cache."""
        cache_path = get_user_data_path('movie_data_cache.json')
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    self.movie_data_cache = json.load(f)
                    logging.info(f"Loaded movie data cache with {len(self.movie_data_cache)} entries.")
            except json.JSONDecodeError:
                QMessageBox.critical(self, "Load Error", "Failed to parse movie_data_cache.json. The file may be corrupted.")
                logging.error("Failed to parse movie_data_cache.json.")
                self.movie_data_cache = {}
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"An unexpected error occurred while loading movie data cache: {e}")
                logging.error(f"Unexpected error while loading movie data cache: {e}")
                self.movie_data_cache = {}
        else:
            # Initialize with an empty cache
            self.movie_data_cache = {}
            self.save_movie_data_cache()
            logging.info("Created empty movie_data_cache.json.")

    def load_group_settings(self, settings):
        """Loads group-specific settings from group_settings.json."""
        group_settings_path = get_user_data_path('group_settings.json')
        if os.path.exists(group_settings_path):
            try:
                with open(group_settings_path, 'r') as f:
                    group_settings = json.load(f)
                    self.group_settings = group_settings
                    logging.info(f"Loaded group settings with {len(self.group_settings)} groups.")
            except json.JSONDecodeError:
                QMessageBox.critical(self, "Load Error", "Failed to parse group_settings.json. The file may be corrupted.")
                logging.error("Failed to parse group_settings.json.")
                self.group_settings = {}
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"An unexpected error occurred while loading group settings: {e}")
                logging.error(f"Unexpected error while loading group settings: {e}")
                self.group_settings = {}
        else:
            # Initialize with an empty dictionary
            self.group_settings = {}
            self.save_group_settings(settings)
            logging.info("Created empty group_settings.json.")

    def load_read_articles(self):
        """Loads the set of read articles from read_articles.json."""
        try:
            read_articles_path = get_user_data_path('read_articles.json')
            if os.path.exists(read_articles_path):
                with open(read_articles_path, 'r') as f:
                    read_articles = json.load(f)
                    self.read_articles = set(read_articles)
                    logging.info(f"Loaded {len(self.read_articles)} read articles.")
            else:
                # Initialize with an empty set
                self.read_articles = set()
                self.save_read_articles()
                logging.info("Created empty read_articles.json.")
        except json.JSONDecodeError:
            QMessageBox.critical(self, "Load Error", "Failed to parse read_articles.json. The file may be corrupted.")
            logging.error("Failed to parse read_articles.json.")
            self.read_articles = set()
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"An unexpected error occurred while loading read articles: {e}")
            logging.error(f"Unexpected error while loading read articles: {e}")
            self.read_articles = set()

    def keyPressEvent(self, event):
        """Handles key press events."""
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Q:
            self.quit_app()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Handles the window close event."""
        if self.is_quitting:
            # Perform cleanup before quitting
            self.save_feeds()
            settings = QSettings('rocker', 'SmallRSSReader')
            self.save_geometry_and_state(settings)
            self.save_ui_visibility_settings(settings)
            self.save_movie_data_cache()
            self.save_group_settings(settings)
            self.save_read_articles()
            self.save_font_size()
        
            # Gracefully terminate all threads
            for thread in self.threads:
                thread.terminate()
                thread.wait()
            logging.info("All threads terminated.")
        
            # Accept the event to allow the application to quit
            event.accept()
        else:
            # Minimize to tray instead of closing
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Small RSS Reader",
                "Application minimized to tray. Double-click the tray icon to restore.",
                QSystemTrayIcon.Information,
                2000
            )

    def init_tray_icon(self):
        """Initializes the system tray icon."""
        self.tray_icon = QSystemTrayIcon(self)
        tray_icon_pixmap = QPixmap(resource_path('icons/rss_tray_icon.png'))  # Ensure you have this icon
        self.tray_icon.setIcon(QIcon(tray_icon_pixmap))
        self.tray_icon.setToolTip("Small RSS Reader")

        # Create tray menu
        tray_menu = QMenu()

        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show_window)  # Connect to show_window method
        tray_menu.addAction(show_action)

        refresh_action = QAction("Refresh All Feeds", self)
        refresh_action.triggered.connect(self.force_refresh_all_feeds)
        tray_menu.addAction(refresh_action)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.quit_app)  # Connect to quit_app instead of self.close
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        # Restore window on single left-click, differentiate between left and right-click
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

    def on_tray_icon_activated(self, reason):
        """Handles tray icon activation (e.g., single or double-click)."""
        if reason == QSystemTrayIcon.Trigger:
             # Left-click: Show or raise the application window, but do not show the context menu
            if not self.tray_icon.isVisible():
                self.show_window()
        elif reason == QSystemTrayIcon.Context:
            # Right-click: Show the context menu
            #self.tray_icon.contextMenu().popup(QCursor.pos())
            pass

    def show_window(self):
        """Shows and raises the application window."""
        if self.isHidden() or not self.isVisible():
            self.showNormal()  # Show the window normally if it's hidden
        self.raise_()  # Bring the window to the front
        self.activateWindow()  # Ensure it gets focus
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)  # Unminimize if minimized

    def save_geometry_and_state(self, settings):
        """Saves the window geometry and state."""
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.saveState())
        settings.setValue('splitterState', self.main_splitter.saveState())
        settings.setValue('articlesTreeHeaderState', self.articles_tree.header().saveState())
        settings.setValue('refresh_interval', self.refresh_interval)
        settings.setValue('group_name_mapping', json.dumps(self.group_name_mapping))
        logging.debug("Saved geometry and state, including articlesTreeHeaderState.")

    def save_ui_visibility_settings(self, settings):
        """Saves UI element visibility settings."""
        settings.setValue('statusbar_visible', self.statusBar().isVisible())
        settings.setValue('toolbar_visible', self.toolbar.isVisible())
        settings.setValue('menubar_visible', self.menuBar().isVisible())

    def save_movie_data_cache(self):
        """Saves the movie data cache."""
        try:
            cache_path = get_user_data_path('movie_data_cache.json')
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'w') as f:
                json.dump(self.movie_data_cache, f, indent=4)
            logging.info("Movie data cache saved successfully.")
        except Exception as e:
            logging.error(f"Failed to save movie data cache: {e}")

    def save_group_settings(self, settings):
        """Saves group-specific settings to group_settings.json."""
        try:
            group_settings_path = get_user_data_path('group_settings.json')
            os.makedirs(os.path.dirname(group_settings_path), exist_ok=True)
            with open(group_settings_path, 'w') as f:
                json.dump(self.group_settings, f, indent=4)
            logging.info("Group settings saved successfully.")
        except Exception as e:
            logging.error(f"Failed to save group settings: {e}")

    def save_read_articles(self):
        """Saves the set of read articles to read_articles.json."""
        try:
            read_articles_path = get_user_data_path('read_articles.json')
            os.makedirs(os.path.dirname(read_articles_path), exist_ok=True)
            with open(read_articles_path, 'w') as f:
                json.dump(list(self.read_articles), f, indent=4)
            logging.info(f"Saved {len(self.read_articles)} read articles.")
        except Exception as e:
            logging.error(f"Failed to save read articles: {e}")

    def toggle_toolbar_visibility(self):
        """Toggles the visibility of the toolbar."""
        visible = self.toggle_toolbar_action.isChecked()
        self.toolbar.setVisible(visible)

    def toggle_statusbar_visibility(self):
        """Toggles the visibility of the status bar."""
        visible = self.toggle_statusbar_action.isChecked()
        self.statusBar().setVisible(visible)

    def toggle_menubar_visibility(self):
        """Toggles the visibility of the menu bar."""
        visible = self.toggle_menubar_action.isChecked()
        self.menuBar().setVisible(visible)

    def rotate_refresh_icon(self):
        """Rotates the refresh icon during feed refresh."""
        if not self.is_refreshing:
            return
        self.refresh_icon_angle = (self.refresh_icon_angle + 30) % 360
        pixmap = self.force_refresh_icon_pixmap
        transform = QTransform().rotate(self.refresh_icon_angle)
        rotated_pixmap = pixmap.transformed(transform, Qt.SmoothTransformation)
        self.force_refresh_action.setIcon(QIcon(rotated_pixmap))

    def open_settings_dialog(self):
        """Opens the settings dialog."""
        dialog = SettingsDialog(self)
        dialog.exec_()

    def open_add_feed_dialog(self):
        """Opens the Add Feed dialog."""
        dialog = AddFeedDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            feed_name, feed_url = dialog.get_inputs()
            self.add_feed(feed_name, feed_url)

    def add_feed(self, feed_name, feed_url):
        """Adds a new feed to the feeds list."""
        if not feed_name or not feed_url:
            QMessageBox.warning(self, "Input Error", "Both Feed Name and Feed URL are required.")
            return
        if not feed_url.startswith(('http://', 'https://')):
            feed_url = 'http://' + feed_url
        if feed_url in [feed['url'] for feed in self.feeds]:
            QMessageBox.information(self, "Duplicate Feed", "This feed URL is already added.")
            return
        if feed_name in [feed['title'] for feed in self.feeds]:
            QMessageBox.warning(self, "Duplicate Name", "A feed with this name already exists.")
            return
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
        except Exception as e:
            QMessageBox.critical(self, "Feed Error", f"Failed to load feed: {e}")
            logging.error(f"Failed to load feed {feed_url}: {e}")
            return
        self.create_feed_data(feed_name, feed_url, feed)
        self.statusBar().showMessage(f"Added feed: {feed_name}")
        logging.info(f"Added new feed: {feed_name} ({feed_url})")
        self.save_feeds()

    def create_feed_data(self, feed_name, feed_url, feed):
        """Creates feed data and adds it to the feeds list and UI."""
        feed_data = {
            'title': feed_name,
            'url': feed_url,
            'entries': [],
            'sort_column': 1,
            'sort_order': Qt.AscendingOrder,
            'visible_columns': [True] * 6
        }
        self.feeds.append(feed_data)
        self.add_feed_to_ui(feed_data)

    def add_feed_to_ui(self, feed_data):
        """Adds a feed to the UI under the appropriate group with a new updates icon."""
        parsed_url = urlparse(feed_data['url'])
        domain = parsed_url.netloc or 'Unknown Domain'
        group_name = self.group_name_mapping.get(domain, domain)
        existing_group = self.find_or_create_group(group_name, domain)
        feed_item = QTreeWidgetItem(existing_group)
        feed_item.setText(0, feed_data['title'])
        feed_item.setData(0, Qt.UserRole, feed_data['url'])
        feed_item.setFlags(feed_item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled)

        # **Set New Updates Icon Initially if there are new articles**
        if feed_data.get('entries'):
            # Assuming you have an icon named 'new_icon.png' in your resources
            new_icon = QIcon(resource_path('icons/new_icon.png'))
            feed_item.setIcon(0, new_icon)

        self.feeds_list.expandItem(existing_group)


    def find_or_create_group(self, group_name, domain):
        """Finds or creates a group in the feeds list with bold font."""
        for i in range(self.feeds_list.topLevelItemCount()):
            group = self.feeds_list.topLevelItem(i)
            if group.text(0) == group_name:
                return group
        group = QTreeWidgetItem(self.feeds_list)
        group.setText(0, group_name)
        group.setExpanded(False)
        group.setFlags(group.flags() & ~Qt.ItemIsSelectable)

        # **Set Bold Font for Group Name**
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)

        return group


    def feeds_context_menu(self, position):
        """Context menu for the feeds list."""
        item = self.feeds_list.itemAt(position)
        if not item:
            return
        if item.parent() is None:
            self.show_group_context_menu(item, position)
        else:
            self.show_feed_context_menu(item, position)

    def show_group_context_menu(self, group_item, position):
        """Shows the context menu for a group."""
        menu = QMenu()
        rename_group_action = QAction("Rename Group", self)
        rename_group_action.triggered.connect(lambda: self.rename_group(group_item))
        menu.addAction(rename_group_action)
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(lambda: self.group_settings_dialog(group_item))
        menu.addAction(settings_action)
        menu.exec_(self.feeds_list.viewport().mapToGlobal(position))

    def group_settings_dialog(self, group_item):
        """Opens the settings dialog for a group."""
        group_name = group_item.text(0)
        settings = self.group_settings.get(group_name, {'omdb_enabled': True, 'notifications_enabled': True})
        omdb_enabled = settings.get('omdb_enabled', True)
        notifications_enabled = settings.get('notifications_enabled', True)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Settings for {group_name}")
        layout = QVBoxLayout(dialog)

        # OMDb Feature Checkbox
        omdb_checkbox = QCheckBox("Enable OMDb Feature", dialog)
        omdb_checkbox.setChecked(omdb_enabled)
        layout.addWidget(omdb_checkbox)

        # **Add Group Notifications Checkbox**
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
        """Saves the OMDb and Notification settings for a group."""
        self.group_settings[group_name] = {
            'omdb_enabled': omdb_enabled,
            'notifications_enabled': notifications_enabled
        }
        self.save_group_settings(QSettings('rocker', 'SmallRSSReader'))
        self.statusBar().showMessage(f"Updated settings for group: {group_name}")
        logging.info(f"Updated settings for group '{group_name}': OMDb {'enabled' if omdb_enabled else 'disabled'}, Notifications {'enabled' if notifications_enabled else 'disabled'}.")
        current_feed = self.get_current_feed()
        if current_feed:
            current_group_name = self.get_group_name_for_feed(current_feed['url'])
            if current_group_name == group_name:
                self.populate_articles()

    def get_group_name_for_feed(self, feed_url):
        """Returns the group name for a given feed URL."""
        for i in range(self.feeds_list.topLevelItemCount()):
            group_item = self.feeds_list.topLevelItem(i)
            for j in range(group_item.childCount()):
                feed_item = group_item.child(j)
                if feed_item.data(0, Qt.UserRole) == feed_url:
                    return group_item.text(0)
        return None

    def rename_group(self, group_item):
        """Renames the selected group."""
        current_group_name = group_item.text(0)
        new_group_name, ok = QInputDialog.getText(
            self, "Rename Group", "Enter new group name:", QLineEdit.Normal, current_group_name)
        if ok and new_group_name:
            self.update_group_name(group_item, current_group_name, new_group_name)

    def update_group_name(self, group_item, current_group_name, new_group_name):
        """Updates the group name and related settings."""
        domain = self.get_domain_for_group(current_group_name)
        self.group_name_mapping[domain] = new_group_name
        if current_group_name in self.group_settings:
            self.group_settings[new_group_name] = self.group_settings.pop(current_group_name)
        self.save_group_names()
        self.save_group_settings(QSettings('rocker', 'SmallRSSReader'))
        group_item.setText(0, new_group_name)
        self.statusBar().showMessage(f"Renamed group to: {new_group_name}")
        logging.info(f"Renamed group '{current_group_name}' to '{new_group_name}'.")

    def get_domain_for_group(self, group_name):
        """Finds the domain associated with a group name."""
        for domain_key, group_name_value in self.group_name_mapping.items():
            if group_name_value == group_name:
                return domain_key
        return group_name

    def rename_feed(self):
        """Renames the selected feed."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Feed Selected", "Please select a feed to rename.")
            return
        item = selected_items[0]
        if item.parent() is None:
            QMessageBox.information(self, "Invalid Selection", "Please select a feed, not a group.")
            return
        current_name = item.text(0)
        new_name, ok = QInputDialog.getText(
            self, "Rename Feed", "Enter new name:", QLineEdit.Normal, current_name)
        if ok and new_name:
            if new_name in [feed['title'] for feed in self.feeds]:
                QMessageBox.warning(self, "Duplicate Name", "A feed with this name already exists.")
                return
            url = item.data(0, Qt.UserRole)
            feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
            if feed_data:
                feed_data['title'] = new_name
                item.setText(0, new_name)
                self.save_feeds()
                self.statusBar().showMessage(f"Renamed feed to: {new_name}")
                logging.info(f"Renamed feed '{current_name}' to '{new_name}'.")

    def remove_feed(self):
        """Removes the selected feed."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Feed Selected", "Please select a feed to remove.")
            return
        item = selected_items[0]
        if item.parent() is None:
            QMessageBox.information(self, "Invalid Selection", "Please select a feed, not a group.")
            return
        feed_name = item.text()
        reply = QMessageBox.question(self, 'Remove Feed',
                                     f"Are you sure you want to remove the feed '{feed_name}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            url = item.data(0, Qt.UserRole)
            self.feeds = [feed for feed in self.feeds if feed['url'] != url]
            parent_group = item.parent()
            parent_group.removeChild(item)
            remaining_children = parent_group.childCount()
            if remaining_children == 0:
                self.feeds_list.takeTopLevelItem(self.feeds_list.indexOfTopLevelItem(parent_group))
            self.save_feeds()
            self.statusBar().showMessage(f"Removed feed: {feed_name}")
            logging.info(f"Removed feed: {feed_name}")

    def load_group_names(self):
        """Loads the group name mapping from settings."""
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
        """Saves the group name mapping to settings."""
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('group_name_mapping', json.dumps(self.group_name_mapping))

    def load_feeds(self):
        """Loads the feeds from the saved feeds.json file."""
        feeds_path = get_user_data_path('feeds.json')
        if os.path.exists(feeds_path):
            try:
                with open(feeds_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.feeds = []
                        for feed in data.get('feeds', []):
                            self.feeds.append(feed)
                    elif isinstance(data, list):
                        self.feeds = data
                    else:
                        self.feeds = []
                # Populate feeds in the UI
                self.feeds_list.clear()
                for feed in self.feeds:
                    parsed_url = urlparse(feed['url'])
                    domain = parsed_url.netloc or 'Unknown Domain'
                    group_name = self.group_name_mapping.get(domain, domain)
                    existing_group = self.find_or_create_group(group_name, domain)
                    feed_item = QTreeWidgetItem(existing_group)
                    feed_item.setText(0, feed['title'])
                    feed_item.setData(0, Qt.UserRole, feed['url'])
                    feed_item.setFlags(feed_item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled)
                logging.info(f"Loaded {len(self.feeds)} feeds.")
                # **Add this line to expand all feed groups**
                self.feeds_list.expandAll()
            except json.JSONDecodeError:
                QMessageBox.critical(self, "Load Error", "Failed to parse feeds.json. The file may be corrupted.")
                logging.error("Failed to parse feeds.json.")
                self.feeds = []
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"An unexpected error occurred while loading feeds: {e}")
                logging.error(f"Unexpected error while loading feeds: {e}")
                self.feeds = []
        else:
            # Create default feeds.json with default or empty feeds
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
                # Add more default feeds as desired
            ]
            self.save_feeds()
            logging.info("Created default feeds.json with initial feeds.")

    def save_feeds(self):
        """Saves the feeds to feeds.json file."""
        try:
            feeds_path = get_user_data_path('feeds.json')
            os.makedirs(os.path.dirname(feeds_path), exist_ok=True)
            with open(feeds_path, 'w') as f:
                json.dump(self.feeds, f, indent=4)
            logging.info("Feeds saved successfully.")
        except Exception as e:
            logging.error(f"Failed to save feeds: {e}")

    def update_feed_titles(self):
        """Updates the feed titles in case they were not set properly."""
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
        self.save_feeds()

    def load_articles(self):
        """Loads the articles for the selected feed."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        if item.parent() is None:
            return  # Do not load articles if a group is selected
        url = item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
        if feed_data and 'entries' in feed_data and feed_data['entries']:
            self.current_entries = feed_data['entries']
            self.populate_articles()
        else:
            self.statusBar().showMessage(f"Loading articles from {item.text(0)}")
            thread = FetchFeedThread(url)
            thread.feed_fetched.connect(self.on_feed_fetched)
            self.threads.append(thread)
            thread.finished.connect(lambda t=thread: self.remove_thread(t))
            thread.start()

    def display_content(self):
        """Displays the content of the selected article."""
        selected_items = self.articles_tree.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]

        # Retrieve the entry directly from the item's data
        entry = item.data(0, Qt.UserRole)
        if not entry:
            return
        title = entry.get('title', 'No Title')
        date_formatted = item.text(1)

        if 'content' in entry and entry['content']:
            content = entry['content'][0].get('value', '')
        elif 'summary' in entry:
            content = entry.get('summary', 'No Content')
        else:
            #content = 'No Content Available.'
            content = ''

        images_html = ''
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
        body {
            max-width: 800px;
            margin: auto;
            padding: 5px;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 16px;
            line-height: 1.6;
            color: #333;
            background-color: #f9f9f9;
        }
        h3 {
            font-size: 18px;
        }
        p {
            margin: 0 0 5px;
        }
        img {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 5px 0;
        }
        a {
            color: #1e90ff;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        blockquote {
            margin: 5px 0;
            padding: 5px 20px;
            background-color: #f0f0f0;
            border-left: 5px solid #ccc;
        }
        code {
            font-family: monospace;
            background-color: #f0f0f0;
            padding: 2px 4px;
            border-radius: 4px;
        }
        pre {
            background-color: #f0f0f0;
            padding: 10px;
            overflow: auto;
            border-radius: 4px;
        }
        </style>
        """

        if link:
            read_more = f'<p><a href="{link}">Read more</a></p>'
        else:
            read_more = ''

        html_content = f"""
        {styles}
        <h3>{title}</h3>
        {images_html}
        {content}
        {movie_info_html}
        {read_more}
        """

        current_feed_item = self.feeds_list.currentItem()
        if current_feed_item:
            feed_url = current_feed_item.data(0, Qt.UserRole)
        else:
            feed_url = QUrl()
        self.content_view.setHtml(html_content, baseUrl=QUrl(feed_url))
        self.statusBar().showMessage(f"Displaying article: {title}")

        article_id = item.data(0, Qt.UserRole + 1)
        if article_id not in self.read_articles:
            self.read_articles.add(article_id)
            item.setIcon(0, self.get_unread_icon())
            self.save_read_articles()

    def populate_articles(self):
        """Populates the articles tree with the current entries."""
        self.articles_tree.setSortingEnabled(False)
        self.articles_tree.clear()
        self.article_id_to_item = {}  # Reset the mapping

        current_feed = self.get_current_feed()

        if current_feed:
            group_name = self.get_group_name_for_feed(current_feed['url'])
            group_settings = self.group_settings.get(group_name, {'omdb_enabled': True})
            omdb_enabled = group_settings.get('omdb_enabled', True)

            # **Update Column Visibility Based on OMDb Setting**
            if not omdb_enabled:
                # Show only Title and Date
                current_feed['visible_columns'] = [True, True, False, False, False, False]
                self.save_feeds()
            elif 'visible_columns' not in current_feed:
                # If visible_columns not set, default to all columns visible
                current_feed['visible_columns'] = [True] * 6
                self.save_feeds()
        else:
            omdb_enabled = True  # Default to True if no feed is selected

        for index, entry in enumerate(self.current_entries):
            title = entry.get('title', 'No Title')

            # **Create the Article Item with Full Title**
            item = ArticleTreeWidgetItem([title, '', '', '', '', ''])  # Temporarily set empty strings
            item.setToolTip(0, title)  # Set full title as tooltip

            # **Set Date**
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                date_obj = datetime.datetime(*date_struct[:6])
                date_formatted = date_obj.strftime('%d-%m-%Y')
            else:
                date_obj = datetime.datetime.min
                date_formatted = 'No Date'
            item.setText(1, date_formatted)
            item.setData(1, Qt.UserRole, date_obj)

            # **Set Default Values for Other Columns**
            if not omdb_enabled or not self.api_key:
                rating_str = 'N/A'
                released_str = ''
                genre_str = ''
                director_str = ''
            else:
                rating_str = 'Loading...'
                released_str = ''
                genre_str = ''
                director_str = ''

            item.setText(2, rating_str)
            item.setText(3, released_str)
            item.setText(4, genre_str)
            item.setText(5, director_str)

            # **Store Article Data**
            article_id = self.get_article_id(entry)
            item.setData(0, Qt.UserRole + 1, article_id)
            item.setData(0, Qt.UserRole, entry)

            self.article_id_to_item[article_id] = item

            # **Set Unread Icon if Applicable**
            if article_id not in self.read_articles:
                item.setIcon(0, self.get_unread_icon())
            else:
                item.setIcon(0, QIcon())

            self.articles_tree.addTopLevelItem(item)

        self.articles_tree.setSortingEnabled(True)
        self.statusBar().showMessage(f"Loaded {len(self.current_entries)} articles")

        if omdb_enabled and self.api_key:
            movie_thread = FetchMovieDataThread(self.current_entries, self.api_key, self.movie_data_cache)
            movie_thread.movie_data_fetched.connect(self.update_movie_info)
            self.threads.append(movie_thread)
            movie_thread.finished.connect(lambda t=movie_thread: self.remove_thread(t))
            movie_thread.start()
        else:
            logging.info(f"OMDb feature disabled for group '{group_name}' or API key not provided; skipping movie data fetching.")

        # **Apply the Feed's Sort Preference**
        if current_feed:
            sort_column = current_feed.get('sort_column', 1)
            sort_order = current_feed.get('sort_order', Qt.AscendingOrder)
            self.articles_tree.sortItems(sort_column, sort_order)

        # **Apply Column Visibility Based on the Current Feed's Settings**
        if current_feed and 'visible_columns' in current_feed:
            for i, visible in enumerate(current_feed['visible_columns']):
                self.articles_tree.setColumnHidden(i, not visible)

        # **Automatically Select the First Article if Available**
        if self.articles_tree.topLevelItemCount() > 0:
            first_item = self.articles_tree.topLevelItem(0)
            self.articles_tree.setCurrentItem(first_item)

        self.apply_font_size()
        # Automatically Select the First Article if Available
        if self.articles_tree.topLevelItemCount() > 0:
            first_item = self.articles_tree.topLevelItem(0)
            self.articles_tree.setCurrentItem(first_item)

    def get_current_feed(self):
        """Returns the currently selected feed data."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            return None
        item = selected_items[0]
        if item.parent() is None:
            return None  # A group is selected, not a feed
        url = item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
        return feed_data

    def remove_thread(self, thread):
        """Removes a finished thread from the threads list."""
        if thread in self.threads:
            self.threads.remove(thread)
            if hasattr(thread, 'url'):
                logging.debug(f"Removed thread for feed: {thread.url}")
            else:
                logging.debug("Removed a thread without a URL attribute.")

    def update_movie_info(self, index, movie_data):
        """Updates the article item with movie data."""
        if index < 0 or index >= len(self.current_entries):
            logging.error(f"update_movie_info called with out-of-range index: {index}. Current entries count: {len(self.current_entries)}.")
            return  # Safely exit the function to prevent the crash
        entry = self.current_entries[index]
        article_id = self.get_article_id(entry)
        item = self.article_id_to_item.get(article_id)
        if item:
            imdb_rating = movie_data.get('imdbrating', 'N/A')  # Corrected key
            rating_value = self.parse_rating(imdb_rating)
            item.setData(2, Qt.UserRole, rating_value)
            item.setText(2, imdb_rating)

            released = movie_data.get('released', '')
            release_date = self.parse_release_date(released)
            item.setData(3, Qt.UserRole, release_date)
            item.setText(3, release_date.strftime('%d %b %Y') if release_date != datetime.datetime.min else '')

            genre = movie_data.get('genre', '')
            director = movie_data.get('director', '')
            item.setText(4, genre)
            item.setText(5, director)

            # Update the entry with the fetched movie data
            entry['movie_data'] = movie_data
        else:
            logging.warning(f"No QTreeWidgetItem found for article ID: {article_id}")

    def parse_rating(self, rating_str):
        """Parses the IMDb rating string to a float value."""
        try:
            return float(rating_str.split('/')[0])
        except (ValueError, IndexError):
            return 0.0

    def parse_release_date(self, released_str):
        """Parses the release date string to a datetime object."""
        try:
            return datetime.datetime.strptime(released_str, '%d %b %Y')
        except (ValueError, TypeError):
            return datetime.datetime.min

    def get_unread_icon(self):
        """Returns the icon used for unread articles."""
        pixmap = QPixmap(10, 10)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QBrush(QColor(0, 122, 204)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 10, 10)
        painter.end()
        return QIcon(pixmap)

    def get_article_id(self, entry):
        """Generates a unique ID for an article."""
        unique_string = entry.get('id') or entry.get('guid') or entry.get('link') or (entry.get('title', '') + entry.get('published', ''))
        return hashlib.md5(unique_string.encode('utf-8')).hexdigest()

    def mark_feed_unread(self):
        """Marks all articles in the selected feed as unread."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Feed Selected", "Please select a feed to mark as unread.")
            return
        item = selected_items[0]
        if item.parent() is None:
            QMessageBox.information(self, "Invalid Selection", "Please select a feed, not a group.")
            return
        url = item.data(0, Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
        if not feed_data or 'entries' not in feed_data:
            QMessageBox.warning(self, "No Entries", "No articles found for the selected feed.")
            return
        reply = QMessageBox.question(self, 'Mark Feed Unread',
                                     'Are you sure you want to mark all articles in this feed as unread?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for entry in feed_data['entries']:
                article_id = self.get_article_id(entry)
                if article_id in self.read_articles:
                    self.read_articles.remove(article_id)
            self.save_read_articles()
            self.load_articles()
            logging.info(f"Marked all articles in feed '{feed_data['title']}' as unread.")

    def filter_articles(self, text):
        """Filters the articles based on the search input."""
        for i in range(self.articles_tree.topLevelItemCount()):
            item = self.articles_tree.topLevelItem(i)
            if text.lower() in item.text(0).lower():
                item.setHidden(False)
            else:
                item.setHidden(True)

    def refresh_feed(self):
        """Refreshes the selected feed."""
        self.load_articles()
        logging.info("Refreshed selected feed.")

    def force_refresh_all_feeds(self):
        """Forces a refresh of all feeds without showing any warnings."""
        if self.is_refreshing:
            # Silently ignore the refresh request since one is already in progress
            logging.debug("Refresh attempt ignored: already in progress.")
            return  # Prevent multiple refreshes at the same time

        if not self.feeds:
            logging.warning("No feeds to refresh.")
            return

        self.is_refreshing = True
        self.refresh_icon_angle = 0
        self.icon_rotation_timer.start(50)  # Rotate every 50ms
        self.active_feed_threads = len(self.feeds)
        logging.info("Starting force refresh of all feeds.")

        for feed_data in self.feeds:
            url = feed_data['url']
            thread = FetchFeedThread(url)
            thread.feed_fetched.connect(self.on_feed_fetched_force_refresh)
            self.threads.append(thread)
            thread.finished.connect(lambda t=thread: self.remove_thread(t))
            thread.start()
            logging.debug(f"Started thread for feed: {url}")

    def on_feed_fetched(self, url, feed):
        """Handles the feed fetched signal, updating the feed with new data and sending notifications."""
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
                    break
            current_feed_item = self.feeds_list.currentItem()
            if current_feed_item and current_feed_item.data(0, Qt.UserRole) == url:
                self.populate_articles()
            self.save_read_articles()
            logging.info(f"Feed fetched: {url} with {len(new_entries)} new articles.")
        else:
            logging.warning(f"Failed to fetch feed: {url}")

    def on_feed_fetched_force_refresh(self, url, feed):
        """Callback when a feed is forcefully refreshed and updates the new icon."""
        logging.debug(f"on_feed_fetched_force_refresh called for feed: {url}")
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
                    # **Update Feed Icon if New Entries are Added**
                    if new_entries:
                        self.set_feed_new_icon(url, True)
                    break
        else:
            logging.warning(f"Failed to fetch feed during force refresh: {url}")
        
        # Decrement active_feed_threads
        self.active_feed_threads -= 1
        logging.debug(f"Feed thread finished. Remaining threads: {self.active_feed_threads}")
        
        # Check if all feeds have been refreshed
        if self.active_feed_threads == 0:
            self.is_refreshing = False  # Reset the flag
            self.icon_rotation_timer.stop()
            self.force_refresh_action.setIcon(QIcon(self.force_refresh_icon_pixmap))
            logging.info("Completed force refresh of all feeds.")
        
    def set_feed_new_icon(self, url, has_new):
        """Sets or removes the new updates icon for a specific feed."""
        for i in range(self.feeds_list.topLevelItemCount()):
            group = self.feeds_list.topLevelItem(i)
            for j in range(group.childCount()):
                feed_item = group.child(j)
                if feed_item.data(0, Qt.UserRole) == url:
                    if has_new:
                        new_icon = QIcon(resource_path('icons/new_icon.png'))  # Ensure this icon exists
                        feed_item.setIcon(0, new_icon)
                    else:
                        feed_item.setIcon(0, QIcon())  # Remove the icon
                    return

    def import_feeds(self):
        """Imports feeds from a JSON file."""
        file_name, _ = QFileDialog.getOpenFileName(self, "Import Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as f:
                    feeds = json.load(f)
                    for feed in feeds:
                        if feed['url'] not in [f['url'] for f in self.feeds]:
                            if 'sort_column' not in feed:
                                feed['sort_column'] = 1
                            if 'sort_order' not in feed:
                                feed['sort_order'] = Qt.AscendingOrder
                            if 'visible_columns' not in feed:
                                feed['visible_columns'] = [True] * 6
                            self.feeds.append(feed)
                            parsed_url = urlparse(feed['url'])
                            domain = parsed_url.netloc or 'Unknown Domain'
                            group_name = self.group_name_mapping.get(domain, domain)
                            existing_group = self.find_or_create_group(group_name, domain)
                            feed_item = QTreeWidgetItem(existing_group)
                            feed_item.setText(0, feed['title'])
                            feed_item.setData(0, Qt.UserRole, feed['url'])
                            feed_item.setFlags(feed_item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled)
                self.save_feeds()
                self.statusBar().showMessage("Feeds imported")
                logging.info("Feeds imported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import feeds: {e}")
                logging.error(f"Failed to import feeds: {e}")

    def export_feeds(self):
        """Exports feeds to a JSON file."""
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    json.dump(self.feeds, f, indent=4)
                self.statusBar().showMessage("Feeds exported")
                logging.info("Feeds exported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export feeds: {e}")
                logging.error(f"Failed to export feeds: {e}")

    def show_header_menu(self, position):
        """Context menu for the articles tree header."""
        menu = QMenu()
        header = self.articles_tree.header()
        current_feed = self.get_current_feed()
        if not current_feed:
            return

        group_name = self.get_group_name_for_feed(current_feed['url'])
        group_settings = self.group_settings.get(group_name, {'omdb_enabled': True})
        omdb_enabled = group_settings.get('omdb_enabled', True)

        for i in range(header.count()):
            column_name = header.model().headerData(i, Qt.Horizontal)
            action = QAction(column_name, menu)
            action.setCheckable(True)
            visible = current_feed['visible_columns'][i] if 'visible_columns' in current_feed and i < len(current_feed['visible_columns']) else True
            action.setChecked(visible)
            action.setData(i)

            if not omdb_enabled and i > 1:
                # Disable toggling for columns beyond Title and Date
                action.setEnabled(False)

            action.toggled.connect(self.toggle_column_visibility)
            menu.addAction(action)
        menu.exec_(header.mapToGlobal(position))

    def toggle_column_visibility(self, checked):
        """Toggles the visibility of a column in the articles tree."""
        action = self.sender()
        index = action.data()
        if checked:
            self.articles_tree.showColumn(index)
        else:
            self.articles_tree.hideColumn(index)
        current_feed = self.get_current_feed()
        if current_feed and 'visible_columns' in current_feed and index < len(current_feed['visible_columns']):
            current_feed['visible_columns'][index] = checked
            self.save_feeds()
            logging.debug(f"Column {index} visibility set to {checked} for feed '{current_feed['title']}'.")

    def on_sort_changed(self, column, order):
        """Handles sort changes and saves the preference."""
        current_feed = self.get_current_feed()
        if current_feed:
            current_feed['sort_column'] = column
            current_feed['sort_order'] = order
            self.save_feeds()
            logging.debug(f"Sort settings updated for feed '{current_feed['title']}': column={column}, order={order}.")

    def select_first_feed(self):
        """Selects the first feed in the list if available."""
        if self.feeds_list.topLevelItemCount() > 0:
            first_group = self.feeds_list.topLevelItem(0)
            if first_group.childCount() > 0:
                first_feed = first_group.child(0)
                self.feeds_list.setCurrentItem(first_feed)

### Main Function ###

def main():
    """Main function to start the application."""
    parser = argparse.ArgumentParser(description="Small RSS Reader")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    # Set the working directory to the script's directory
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(application_path)

    # Configure logging based on the debug flag
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
    # Set the global application icon
    app.setWindowIcon(QIcon(resource_path('icons/rss_icon.png')))
    # This is a step to ensure your application behaves more like a regular windowed application on macOS.
    app.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app.setQuitOnLastWindowClosed(True)


    # Create and show the splash screen
    splash_pix = QPixmap(resource_path('icons/splash.png'))
    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.setMask(splash_pix.mask())
    splash.showMessage("Initializing...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
    splash.show()
    QApplication.processEvents()

    # Initialize the main window
    reader = RSSReader()
    reader.show()
    reader.raise_()
    reader.activateWindow()  # Ensure that it gets focus

    # Update splash screen message
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
    
    # Finish splash screen
    splash.finish(reader)

    # Ensure that Ctrl+C works on Unix-like systems
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
