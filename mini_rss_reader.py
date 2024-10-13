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
from omdbapi.movie_search import GetMovie
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox, QAction,
    QFileDialog, QMenu, QToolBar, QHeaderView, QDialog, QFormLayout,
    QSizePolicy, QStyle, QSpinBox, QAbstractItemView, QTextEdit, QInputDialog
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QUrl, QSettings, QSize
from PyQt5.QtGui import QDesktopServices, QFont, QIcon, QPixmap, QPainter, QBrush, QColor

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set level to INFO to suppress debug messages
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('rss_reader.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class FetchFeedThread(QThread):
    """Thread for fetching RSS feed data asynchronously."""
    feed_fetched = pyqtSignal(object, object)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            feed = feedparser.parse(self.url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            self.feed_fetched.emit(self.url, feed)
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
            return  # Do not attempt to fetch movie data without an API key
        for index, entry in enumerate(self.entries):
            title = entry.get('title', 'No Title')
            movie_title = self.extract_movie_title(title)
            if movie_title in self.movie_data_cache:
                movie_data = self.movie_data_cache[movie_title]
            else:
                movie_data = self.fetch_movie_data(movie_title)
                self.movie_data_cache[movie_title] = movie_data
            self.movie_data_fetched.emit(index, movie_data)

    def extract_movie_title(self, text):
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

        english_title = None
        for part in parts:
            part = part.strip()
            if is_mostly_latin(part):
                english_title = part
                break

        if not english_title:
            english_title = text.strip()

        english_title = re.split(r'[\(\[]', english_title)[0].strip()
        return english_title

    def fetch_movie_data(self, movie_title):
        """Fetches movie data from OMDb API."""
        if not self.api_key:
            return {}
        if movie_title in self.movie_data_cache:
            return self.movie_data_cache[movie_title]
        try:
            movie = GetMovie(api_key=self.api_key)
            movie_data = movie.get_movie(title=movie_title)
            return movie_data
        except Exception as e:
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

class WebEnginePage(QWebEnginePage):
    """Custom QWebEnginePage to handle link clicks in the content view."""
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if _type == QWebEnginePage.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return True

class SettingsDialog(QDialog):
    """Dialog for application settings."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QFormLayout(self)

        self.api_key_input = QLineEdit(self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setText(self.parent().api_key)
        layout.addRow("OMDb API Key:", self.api_key_input)

        # Notice about rating feature being disabled without API key
        self.api_key_notice = QLabel()
        self.api_key_notice.setStyleSheet("color: red;")
        if not self.parent().api_key:
            self.api_key_notice.setText("Ratings feature is disabled without an API key.")
        else:
            self.api_key_notice.setText("")
        layout.addRow("", self.api_key_notice)

        self.refresh_interval_input = QSpinBox(self)
        self.refresh_interval_input.setRange(1, 1440)
        self.refresh_interval_input.setValue(self.parent().refresh_interval)
        layout.addRow("Refresh Interval (minutes):", self.refresh_interval_input)

        buttons_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_settings)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(save_button)
        buttons_layout.addWidget(cancel_button)
        layout.addRow(buttons_layout)

    def save_settings(self):
        """Saves the settings when the user clicks 'Save'."""
        api_key = self.api_key_input.text().strip()
        refresh_interval = self.refresh_interval_input.value()
        self.parent().api_key = api_key
        self.parent().refresh_interval = refresh_interval
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('omdb_api_key', api_key)
        settings.setValue('refresh_interval', refresh_interval)
        self.parent().update_refresh_timer()
        self.accept()

class RSSReader(QMainWindow):
    """Main application class for the RSS Reader."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Small RSS Reader")
        self.resize(1200, 800)
        self.feeds = []
        self.current_entries = []
        self.api_key = ''
        self.refresh_interval = 60  # Default refresh interval in minutes
        self.movie_data_cache = {}
        self.read_articles = set()
        self.threads = []
        self.article_id_to_item = {}  # Mapping from article_id to QTreeWidgetItem
        self.init_ui()
        self.load_feeds()
        self.load_settings()
        self.load_read_articles()

    def init_ui(self):
        """Initializes the main UI components."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Main splitter divides the window vertically
        self.main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(self.main_splitter)

        # Horizontal splitter divides the top part horizontally
        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self.horizontal_splitter)

        self.init_feeds_panel()
        self.init_articles_panel()
        self.init_content_panel()

        # Set stretch factors for splitters
        self.horizontal_splitter.setStretchFactor(0, 1)
        self.horizontal_splitter.setStretchFactor(1, 3)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)

        self.init_menu()
        self.init_toolbar()

        self.statusBar().showMessage("Ready")

        # Refresh timer for auto-updating feeds
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.force_refresh_all_feeds)
        self.update_refresh_timer()

    def update_refresh_timer(self):
        """Updates the refresh timer based on the refresh interval."""
        if self.refresh_timer.isActive():
            self.refresh_timer.stop()
        self.refresh_timer.start(self.refresh_interval * 60 * 1000)
        logging.info(f"Refresh timer set to {self.refresh_interval} minutes.")

    def init_feeds_panel(self):
        """Initializes the feeds panel."""
        self.feeds_panel = QWidget()
        feeds_layout = QVBoxLayout(self.feeds_panel)
        feeds_layout.setContentsMargins(5, 5, 5, 5)

        feeds_label = QLabel("RSS Feeds")
        feeds_label.setFont(QFont("Arial", 12, QFont.Bold))
        feeds_layout.addWidget(feeds_label)

        self.feeds_list = QListWidget()
        self.feeds_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.feeds_list.itemSelectionChanged.connect(self.load_articles)
        self.feeds_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.feeds_list.customContextMenuRequested.connect(self.feeds_context_menu)
        feeds_layout.addWidget(self.feeds_list)

        # Enable drag-and-drop reordering of feeds
        self.feeds_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.feeds_list.model().rowsMoved.connect(self.on_feeds_reordered)

        feed_input_layout = QHBoxLayout()
        self.feed_url_input = QLineEdit()
        self.feed_url_input.setPlaceholderText("Enter feed URL")
        feed_input_layout.addWidget(self.feed_url_input)
        add_feed_button = QPushButton("Add")
        add_feed_button.clicked.connect(self.add_feed)
        feed_input_layout.addWidget(add_feed_button)
        feeds_layout.addLayout(feed_input_layout)

        self.feeds_panel.setMinimumWidth(200)
        self.feeds_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.horizontal_splitter.addWidget(self.feeds_panel)

    def init_articles_panel(self):
        """Initializes the articles panel."""
        self.articles_panel = QWidget()
        articles_layout = QVBoxLayout(self.articles_panel)
        articles_layout.setContentsMargins(5, 5, 5, 5)

        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.filter_articles)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        articles_layout.addLayout(search_layout)

        self.articles_tree = QTreeWidget()
        self.articles_tree.setHeaderLabels(['Title', 'Date', 'Rating', 'Released', 'Genre', 'Director'])
        self.articles_tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.articles_tree.setSortingEnabled(True)
        self.articles_tree.header().setSectionsClickable(True)
        self.articles_tree.header().setSortIndicatorShown(True)
        self.articles_tree.itemSelectionChanged.connect(self.display_content)
        articles_layout.addWidget(self.articles_tree)

        self.articles_tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.articles_tree.header().customContextMenuRequested.connect(self.show_header_menu)

        self.horizontal_splitter.addWidget(self.articles_panel)

    def init_content_panel(self):
        """Initializes the content panel."""
        self.content_panel = QWidget()
        content_layout = QVBoxLayout(self.content_panel)
        content_layout.setContentsMargins(5, 5, 5, 5)

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

        # View menu
        view_menu = menu.addMenu("View")

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

    def init_toolbar(self):
        """Initializes the toolbar."""
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QSize(16, 16))

        self.addToolBar(self.toolbar)

        back_icon = self.style().standardIcon(QStyle.SP_ArrowBack)
        self.back_action = QAction(back_icon, "Back", self)
        self.back_action.setEnabled(False)
        self.back_action.triggered.connect(self.go_back)
        self.toolbar.addAction(self.back_action)

        forward_icon = self.style().standardIcon(QStyle.SP_ArrowForward)
        self.forward_action = QAction(forward_icon, "Forward", self)
        self.forward_action.setEnabled(False)
        self.forward_action.triggered.connect(self.go_forward)
        self.toolbar.addAction(self.forward_action)

        refresh_icon = self.style().standardIcon(QStyle.SP_BrowserReload)
        refresh_action = QAction(refresh_icon, "Refresh Selected Feed", self)
        refresh_action.triggered.connect(self.refresh_feed)
        self.toolbar.addAction(refresh_action)

        force_refresh_icon = self.style().standardIcon(QStyle.SP_DialogResetButton)
        force_refresh_action = QAction(force_refresh_icon, "Force Refresh All Feeds", self)
        force_refresh_action.triggered.connect(self.force_refresh_all_feeds)
        self.toolbar.addAction(force_refresh_action)

        mark_unread_icon = self.style().standardIcon(QStyle.SP_DialogCancelButton)
        mark_unread_action = QAction(mark_unread_icon, "Mark Feed Unread", self)
        mark_unread_action.triggered.connect(self.mark_feed_unread)
        self.toolbar.addAction(mark_unread_action)

        self.toolbar.setVisible(True)

    def open_settings_dialog(self):
        """Opens the settings dialog."""
        dialog = SettingsDialog(self)
        dialog.exec_()

    def feeds_context_menu(self, position):
        """Context menu for the feeds list."""
        menu = QMenu()
        rename_action = QAction("Rename Feed", self)
        rename_action.triggered.connect(self.rename_feed)
        remove_action = QAction("Remove Feed", self)
        remove_action.triggered.connect(self.remove_feed)
        menu.addAction(rename_action)
        menu.addAction(remove_action)
        menu.exec_(self.feeds_list.viewport().mapToGlobal(position))

    def show_header_menu(self, position):
        """Context menu for the articles tree header."""
        menu = QMenu()
        header = self.articles_tree.header()
        for i in range(header.count()):
            action = QAction(header.model().headerData(i, Qt.Horizontal), menu)
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(i))
            action.setData(i)
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

    def add_feed(self):
        """Adds a new feed to the feeds list."""
        url = self.feed_url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a feed URL.")
            return
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        if url in [feed['url'] for feed in self.feeds]:
            QMessageBox.information(self, "Duplicate Feed", "This feed is already added.")
            return
        try:
            feed = feedparser.parse(url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            feed_title = feed.feed.get('title', url)
        except Exception as e:
            QMessageBox.critical(self, "Feed Error", f"Failed to load feed: {e}")
            return
        if feed_title in [feed['title'] for feed in self.feeds]:
            QMessageBox.information(self, "Duplicate Feed", "A feed with this title is already added.")
            return
        feed_data = {'title': feed_title, 'url': url, 'entries': []}
        self.feeds.append(feed_data)
        item = QListWidgetItem(feed_title)
        item.setData(Qt.UserRole, url)
        self.feeds_list.addItem(item)
        self.feed_url_input.clear()
        self.statusBar().showMessage(f"Added feed: {feed_title}")
        self.save_feeds()

    def remove_feed(self):
        """Removes the selected feed(s) from the feeds list."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            return
        reply = QMessageBox.question(self, 'Remove Feed', 'Are you sure you want to remove the selected feed(s)?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for item in selected_items:
                title = item.text()
                url = item.data(Qt.UserRole)
                self.feeds_list.takeItem(self.feeds_list.row(item))
                self.feeds = [feed for feed in self.feeds if feed['url'] != url]
                self.statusBar().showMessage(f"Removed feed: {title}")
            self.save_feeds()

    def rename_feed(self):
        """Renames the selected feed."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Feed Selected", "Please select a feed to rename.")
            return
        item = selected_items[0]
        current_name = item.text()
        new_name, ok = QInputDialog.getText(self, "Rename Feed", "Enter new name:", QLineEdit.Normal, current_name)
        if ok and new_name:
            # Check for duplicates
            if new_name in [feed['title'] for feed in self.feeds]:
                QMessageBox.warning(self, "Duplicate Name", "A feed with this name already exists.")
                return
            # Update the feeds list
            url = item.data(Qt.UserRole)
            feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
            if feed_data:
                feed_data['title'] = new_name
                item.setText(new_name)
                self.save_feeds()
                self.statusBar().showMessage(f"Renamed feed to: {new_name}")

    def load_feeds(self):
        """Loads the feeds from the saved feeds.json file."""
        if os.path.exists('feeds.json'):
            with open('feeds.json', 'r') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self.feeds = []
                    for url in data.keys():
                        feed_title = url
                        feed_data = {'title': feed_title, 'url': url, 'entries': data[url].get('entries', [])}
                        self.feeds.append(feed_data)
                elif isinstance(data, list):
                    self.feeds = data
                else:
                    self.feeds = []
                for feed in self.feeds:
                    item = QListWidgetItem(feed['title'])
                    item.setData(Qt.UserRole, feed['url'])
                    self.feeds_list.addItem(item)
            self.update_feed_titles()
        else:
            self.feeds = []

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
                    for index in range(self.feeds_list.count()):
                        item = self.feeds_list.item(index)
                        if item.data(Qt.UserRole) == feed['url']:
                            item.setText(feed_title)
                            break
                except Exception as e:
                    pass
        self.save_feeds()

    def save_feeds(self):
        """Saves the feeds to feeds.json file."""
        try:
            with open('feeds.json', 'w') as f:
                json.dump(self.feeds, f, indent=4)
        except Exception as e:
            pass

    def load_articles(self):
        """Loads the articles for the selected feed."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        url = item.data(Qt.UserRole)
        feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
        if feed_data and 'entries' in feed_data and feed_data['entries']:
            self.current_entries = feed_data['entries']
            self.populate_articles()
        else:
            self.statusBar().showMessage(f"Loading articles from {item.text()}")
            thread = FetchFeedThread(url)
            thread.feed_fetched.connect(self.on_feed_fetched)
            self.threads.append(thread)
            thread.finished.connect(lambda t=thread: self.remove_thread(t))
            thread.start()

    def on_feed_fetched(self, url, feed):
        """Callback when a feed is fetched."""
        if feed is None:
            QMessageBox.critical(self, "Feed Error", f"Failed to load feed.")
            return
        self.current_entries = feed.entries
        for feed_data in self.feeds:
            if feed_data['url'] == url:
                feed_data['entries'] = self.current_entries
                break
        self.populate_articles()

    def populate_articles(self):
        """Populates the articles tree with the current entries."""
        self.articles_tree.setSortingEnabled(False)
        self.articles_tree.clear()
        self.article_id_to_item = {}  # Reset the mapping
        for index, entry in enumerate(self.current_entries):
            title = entry.get('title', 'No Title')
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                date_obj = datetime.datetime(*date_struct[:6])
                date_formatted = date_obj.strftime('%d-%m-%Y')
            else:
                date_formatted = 'No Date'

            rating_str = 'N/A' if not self.api_key else 'Loading...'
            released_str = ''
            genre_str = ''
            director_str = ''

            article_id = self.get_article_id(entry)

            item = ArticleTreeWidgetItem([title, date_formatted, rating_str, released_str, genre_str, director_str])
            item.setData(2, Qt.UserRole, 0.0)
            item.setData(3, Qt.UserRole, datetime.datetime.min)
            item.setData(0, Qt.UserRole + 1, article_id)
            item.setData(0, Qt.UserRole, entry)  # Store the entry in the item

            self.article_id_to_item[article_id] = item  # Map article_id to item

            if article_id not in self.read_articles:
                item.setIcon(0, self.get_unread_icon())
            else:
                item.setIcon(0, QIcon())
            self.articles_tree.addTopLevelItem(item)
        self.articles_tree.setSortingEnabled(True)
        self.statusBar().showMessage(f"Loaded {len(self.current_entries)} articles")

        if self.api_key:
            # Start fetching movie data if API key is provided
            movie_thread = FetchMovieDataThread(self.current_entries, self.api_key, self.movie_data_cache)
            movie_thread.movie_data_fetched.connect(self.update_movie_info)
            self.threads.append(movie_thread)
            movie_thread.finished.connect(lambda t=movie_thread: self.remove_thread(t))
            movie_thread.start()
        else:
            logging.info("OMDb API key not provided; skipping movie data fetching.")

    def remove_thread(self, thread):
        """Removes a finished thread from the threads list."""
        if thread in self.threads:
            self.threads.remove(thread)

    def update_movie_info(self, index, movie_data):
        """Updates the article item with movie data."""
        entry = self.current_entries[index]
        article_id = self.get_article_id(entry)
        item = self.article_id_to_item.get(article_id)
        if item:
            imdb_rating = movie_data.get('imdbrating', 'N/A')
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

            # Optional: Re-sort the items if needed
            # self.articles_tree.sortItems(self.articles_tree.sortColumn(), self.articles_tree.header().sortIndicatorOrder())

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
            content = 'No Content Available.'

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
            padding: 20px;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 16px;
            line-height: 1.6;
            color: #333;
            background-color: #f9f9f9;
        }
        h1 {
            font-size: 24px;
        }
        p {
            margin: 0 0 10px;
        }
        img {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 10px 0;
        }
        a {
            color: #1e90ff;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        blockquote {
            margin: 20px 0;
            padding: 10px 20px;
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
        <p><em>{date_formatted}</em></p>
        {images_html}
        {content}
        {movie_info_html}
        {read_more}
        """

        current_feed_item = self.feeds_list.currentItem()
        if current_feed_item:
            feed_url = current_feed_item.data(Qt.UserRole)
        else:
            feed_url = QUrl()
        self.content_view.setHtml(html_content, baseUrl=QUrl(feed_url))
        self.statusBar().showMessage(f"Displaying article: {title}")
        self.update_navigation_buttons()

        article_id = item.data(0, Qt.UserRole + 1)
        if article_id not in self.read_articles:
            self.read_articles.add(article_id)
            item.setIcon(0, QIcon())
            self.save_read_articles()

    def filter_articles(self, text):
        """Filters the articles based on the search input."""
        for i in range(self.articles_tree.topLevelItemCount()):
            item = self.articles_tree.topLevelItem(i)
            if text.lower() in item.text(0).lower():
                item.setHidden(False)
            else:
                item.setHidden(True)

    def go_back(self):
        """Placeholder for back navigation."""
        pass

    def go_forward(self):
        """Placeholder for forward navigation."""
        pass

    def update_navigation_buttons(self):
        """Updates the state of navigation buttons."""
        self.back_action.setEnabled(False)
        self.forward_action.setEnabled(False)

    def refresh_feed(self):
        """Refreshes the selected feed."""
        self.load_articles()

    def force_refresh_all_feeds(self):
        """Forces a refresh of all feeds."""
        for feed_data in self.feeds:
            url = feed_data['url']
            thread = FetchFeedThread(url)
            thread.feed_fetched.connect(self.on_feed_fetched_force_refresh)
            self.threads.append(thread)
            thread.finished.connect(lambda t=thread: self.remove_thread(t))
            thread.start()

    def on_feed_fetched_force_refresh(self, url, feed):
        """Callback when a feed is forcefully refreshed."""
        if feed is not None:
            for feed_data in self.feeds:
                if feed_data['url'] == url:
                    feed_data['entries'] = feed.entries
                    break
        current_feed_item = self.feeds_list.currentItem()
        if current_feed_item and current_feed_item.data(Qt.UserRole) == url:
            self.on_feed_fetched(url, feed)

    def import_feeds(self):
        """Imports feeds from a JSON file."""
        file_name, _ = QFileDialog.getOpenFileName(self, "Import Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as f:
                    feeds = json.load(f)
                    for feed in feeds:
                        if feed['url'] not in [f['url'] for f in self.feeds]:
                            self.feeds.append(feed)
                            item = QListWidgetItem(feed['title'])
                            item.setData(Qt.UserRole, feed['url'])
                            self.feeds_list.addItem(item)
                self.save_feeds()
                self.statusBar().showMessage("Feeds imported")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import feeds: {e}")

    def export_feeds(self):
        """Exports feeds to a JSON file."""
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    json.dump(self.feeds, f, indent=4)
                self.statusBar().showMessage("Feeds exported")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export feeds: {e}")

    def load_read_articles(self):
        """Loads the set of read articles from settings."""
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        read_articles = settings.value('read_articles', [])
        if read_articles:
            self.read_articles = set(read_articles)
        else:
            self.read_articles = set()

    def save_read_articles(self):
        """Saves the set of read articles to settings."""
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('read_articles', list(self.read_articles))

    def closeEvent(self, event):
        """Handles the window close event."""
        self.save_feeds()
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.saveState())
        settings.setValue('splitterState', self.main_splitter.saveState())
        settings.setValue('articlesTreeHeaderState', self.articles_tree.header().saveState())
        settings.setValue('refresh_interval', self.refresh_interval)
        try:
            with open('movie_data_cache.json', 'w') as f:
                json.dump(self.movie_data_cache, f, indent=4)
        except Exception as e:
            pass
        self.save_read_articles()
        event.accept()

    def load_settings(self):
        """Loads application settings."""
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        geometry = settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        windowState = settings.value('windowState')
        if windowState:
            self.restoreState(windowState)
        splitterState = settings.value('splitterState')
        if splitterState:
            self.main_splitter.restoreState(splitterState)
        headerState = settings.value('articlesTreeHeaderState')
        if headerState:
            self.articles_tree.header().restoreState(headerState)
        self.api_key = settings.value('omdb_api_key', '')
        refresh_interval = settings.value('refresh_interval', 60)
        try:
            self.refresh_interval = int(refresh_interval)
        except ValueError:
            self.refresh_interval = 60
        self.update_refresh_timer()
        if os.path.exists('movie_data_cache.json'):
            try:
                with open('movie_data_cache.json', 'r') as f:
                    self.movie_data_cache = json.load(f)
            except Exception as e:
                self.movie_data_cache = {}
        else:
            self.movie_data_cache = {}

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
        unique_string = entry.get('id') or entry.get('link') or (entry.get('title', '') + entry.get('published', ''))
        return hashlib.md5(unique_string.encode('utf-8')).hexdigest()

    def mark_feed_unread(self):
        """Marks all articles in the selected feed as unread."""
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Feed Selected", "Please select a feed to mark as unread.")
            return
        item = selected_items[0]
        url = item.data(Qt.UserRole)
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

    def on_feeds_reordered(self, parent, start, end, destination, row):
        """Updates the internal feeds list when feeds are reordered."""
        new_order = []
        for i in range(self.feeds_list.count()):
            item = self.feeds_list.item(i)
            url = item.data(Qt.UserRole)
            feed_data = next((feed for feed in self.feeds if feed['url'] == url), None)
            if feed_data:
                new_order.append(feed_data)
        self.feeds = new_order
        self.save_feeds()

def main():
    """Main function to start the application."""
    app = QApplication(sys.argv)
    app.setOrganizationName("rocker")
    app.setApplicationName("Small RSS Reader")
    app.setApplicationDisplayName("Small RSS Reader")
    reader = RSSReader()
    reader.show()

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
