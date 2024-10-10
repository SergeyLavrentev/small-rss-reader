import sys
import os
import json
import logging
import feedparser
import datetime
import signal
import re
import unicodedata
from omdbapi.movie_search import GetMovie
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox, QAction,
    QFileDialog, QMenu, QToolBar, QHeaderView, QDialog, QFormLayout,
    QSizePolicy,QStyle
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QUrl, QSettings, QSize
from PyQt5.QtGui import QDesktopServices, QFont, QIcon, QPixmap, QPainter, QBrush, QColor

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('rss_reader.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class FetchFeedThread(QThread):
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
    movie_data_fetched = pyqtSignal(int, dict)  # Signal to emit the index and movie data

    def __init__(self, entries, api_key, cache):
        super().__init__()
        self.entries = entries
        self.api_key = api_key
        self.movie_data_cache = cache  # Use the shared cache

    def run(self):
        for index, entry in enumerate(self.entries):
            title = entry.get('title', 'No Title')
            movie_title = self.extract_movie_title(title)
            if movie_title in self.movie_data_cache:
                movie_data = self.movie_data_cache[movie_title]
                logging.debug(f"Cache hit for movie: {movie_title}")
            else:
                movie_data = self.fetch_movie_data(movie_title)
                self.movie_data_cache[movie_title] = movie_data
                logging.debug(f"Fetched data for movie: {movie_title}")
            self.movie_data_fetched.emit(index, movie_data)

    def extract_movie_title(self, text):
        # Remove leading tags like [Updated]
        text = re.sub(r'^\[.*?\]\s*', '', text)
        logging.debug(f"Title after removing leading tags: {text}")

        # Split the title using '/'
        parts = text.split('/')
        logging.debug(f"Title parts after splitting by '/': {parts}")

        # Function to detect if a string is mostly Latin characters
        def is_mostly_latin(s):
            try:
                latin_count = sum('LATIN' in unicodedata.name(c) for c in s if c.isalpha())
                total_count = sum(c.isalpha() for c in s)
                return latin_count > total_count / 2 if total_count > 0 else False
            except ValueError:
                return False

        # Find the part that is mostly Latin characters
        english_title = None
        for part in parts:
            part = part.strip()
            if is_mostly_latin(part):
                english_title = part
                break

        if not english_title:
            logging.debug(f"No English title found. Using full title: {text}")
            english_title = text.strip()
        else:
            logging.debug(f"Extracted English title: {english_title}")

        # Remove extra metadata after the English title
        # Remove anything after '(' or '['
        english_title = re.split(r'[\(\[]', english_title)[0].strip()

        logging.debug(f"Final English title after cleanup: {english_title}")
        return english_title

    def fetch_movie_data(self, movie_title):
        if not self.api_key:
            logging.error("OMDb API key is not set.")
            return {}
        # Check if the movie data is already in the global cache
        if movie_title in self.movie_data_cache:
            logging.debug(f"Using cached data for movie: {movie_title}")
            return self.movie_data_cache[movie_title]
        try:
            logging.debug(f"Fetching movie data for: {movie_title}")
            movie = GetMovie(api_key=self.api_key)
            movie_data = movie.get_movie(title=movie_title)
            logging.debug(f"Movie data for '{movie_title}': {movie_data}")
            return movie_data
        except Exception as e:
            logging.error(f"Error fetching data for {movie_title}: {e}")
            return {}


class ArticleTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        data1 = self.data(column, Qt.UserRole)
        data2 = other.data(column, Qt.UserRole)
        
        # Handle None values
        if data1 is None:
            data1 = ''
        if data2 is None:
            data2 = ''

        # Sorting logic based on column
        if column == 2:  # Rating column
            try:
                return float(data1) < float(data2)
            except:
                return QTreeWidgetItem.__lt__(self, other)
        elif column == 3:  # Released column
            return data1 < data2
        else:
            return QTreeWidgetItem.__lt__(self, other)


class WebEnginePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if _type == QWebEnginePage.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return True  # Allow other navigation


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QFormLayout(self)

        self.api_key_input = QLineEdit(self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setText(self.parent().api_key)

        layout.addRow("OMDb API Key:", self.api_key_input)

        buttons_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_settings)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(save_button)
        buttons_layout.addWidget(cancel_button)
        layout.addRow(buttons_layout)

    def save_settings(self):
        api_key = self.api_key_input.text().strip()
        if api_key:
            self.parent().api_key = api_key
            settings = QSettings('YourOrganization', 'SmallRSSReader')
            settings.setValue('omdb_api_key', api_key)
            self.accept()
        else:
            QMessageBox.warning(self, "Input Error", "API Key cannot be empty.")


class RSSReader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Small RSS Reader")
        self.resize(1200, 800)
        self.feeds = []
        self.current_entries = []
        self.content_history = []
        self.history_index = -1
        self.api_key = ''  # Initialize API key
        self.movie_data_cache = {}  # Cache for movie data
        self.read_articles = set()  # Set to track read articles
        self.init_ui()
        self.load_feeds()
        self.load_settings()
        self.load_read_articles()  # Load read articles

    def init_ui(self):
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create main vertical splitter to divide top and bottom sections
        self.main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(self.main_splitter)

        # Create horizontal splitter for feeds and articles
        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self.horizontal_splitter)

        # Feeds Panel (Left)
        self.init_feeds_panel()

        # Articles Panel (Center)
        self.init_articles_panel()

        # Content Panel (Bottom)
        self.init_content_panel()

        # Set stretch factors
        self.horizontal_splitter.setStretchFactor(0, 1)  # Feeds panel
        self.horizontal_splitter.setStretchFactor(1, 3)  # Articles panel
        self.main_splitter.setStretchFactor(0, 3)       # Top splitter
        self.main_splitter.setStretchFactor(1, 2)       # Bottom panel

        # Add Menu and Toolbars
        self.init_menu()
        self.init_toolbar()

        # Status Bar
        self.statusBar().showMessage("Ready")
        # Optionally, show the status bar
        # self.statusBar().show()

        # Timer for automatic feed refresh
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.force_refresh_all_feeds)  # Connect to the correct method
        self.refresh_timer.start(15 * 60 * 1000)  # Refresh every 15 minutes

    def init_feeds_panel(self):
        self.feeds_panel = QWidget()
        feeds_layout = QVBoxLayout(self.feeds_panel)
        feeds_layout.setContentsMargins(5, 5, 5, 5)

        # Feeds Label
        feeds_label = QLabel("RSS Feeds")
        feeds_label.setFont(QFont("Arial", 12, QFont.Bold))
        feeds_layout.addWidget(feeds_label)

        # Feeds List Widget
        self.feeds_list = QListWidget()
        self.feeds_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # Allow expansion
        self.feeds_list.itemSelectionChanged.connect(self.load_articles)
        self.feeds_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.feeds_list.customContextMenuRequested.connect(self.feeds_context_menu)
        feeds_layout.addWidget(self.feeds_list)

        # Add Feed Input and Buttons
        feed_input_layout = QHBoxLayout()
        self.feed_url_input = QLineEdit()
        self.feed_url_input.setPlaceholderText("Enter feed URL")
        feed_input_layout.addWidget(self.feed_url_input)
        add_feed_button = QPushButton("Add")
        add_feed_button.clicked.connect(self.add_feed)
        feed_input_layout.addWidget(add_feed_button)
        feeds_layout.addLayout(feed_input_layout)

        # Set fixed minimum width for feeds panel
        self.feeds_panel.setMinimumWidth(200)
        self.feeds_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.horizontal_splitter.addWidget(self.feeds_panel)

    def init_articles_panel(self):
        self.articles_panel = QWidget()
        articles_layout = QVBoxLayout(self.articles_panel)
        articles_layout.setContentsMargins(5, 5, 5, 5)

        # Search Bar
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.filter_articles)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        articles_layout.addLayout(search_layout)

        # Articles Tree Widget
        self.articles_tree = QTreeWidget()
        self.articles_tree.setHeaderLabels(['Title', 'Date', 'Rating', 'Released', 'Genre', 'Director'])
        self.articles_tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.articles_tree.setSortingEnabled(True)  # Enable sorting
        self.articles_tree.itemSelectionChanged.connect(self.display_content)
        articles_layout.addWidget(self.articles_tree)

        # Set context menu for header to allow column visibility control
        self.articles_tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.articles_tree.header().customContextMenuRequested.connect(self.show_header_menu)

        self.horizontal_splitter.addWidget(self.articles_panel)

    def init_content_panel(self):
        self.content_panel = QWidget()
        content_layout = QVBoxLayout(self.content_panel)
        content_layout.setContentsMargins(5, 5, 5, 5)

        # Content Web View
        self.content_view = QWebEngineView()
        self.content_view.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.content_view.setPage(WebEnginePage(self.content_view))
        content_layout.addWidget(self.content_view)

        self.main_splitter.addWidget(self.content_panel)

    def init_menu(self):
        menu = self.menuBar()
        
        # File Menu
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

        # View Menu (for the toolbar toggle)
        view_menu = menu.addMenu("View")
        
        # Toolbar toggle action
        self.toggle_toolbar_action = QAction("Show Toolbar", self)
        self.toggle_toolbar_action.setCheckable(True)
        self.toggle_toolbar_action.setChecked(True)  # Assuming the toolbar is visible by default
        self.toggle_toolbar_action.triggered.connect(self.toggle_toolbar_visibility)
        view_menu.addAction(self.toggle_toolbar_action)

    def toggle_toolbar_visibility(self):
        # Toggle the visibility of the toolbar
        visible = self.toggle_toolbar_action.isChecked()
        self.toolbar.setVisible(visible)

    def init_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")  # Make toolbar an instance variable
        self.toolbar.setIconSize(QSize(16, 16))

        # Add toolbar to the window
        self.addToolBar(self.toolbar)

        # Back Button
        back_icon = self.style().standardIcon(QStyle.SP_ArrowBack)
        self.back_action = QAction(back_icon, "Back", self)
        self.back_action.setEnabled(False)
        self.back_action.triggered.connect(self.go_back)
        self.toolbar.addAction(self.back_action)

        # Forward Button
        forward_icon = self.style().standardIcon(QStyle.SP_ArrowForward)
        self.forward_action = QAction(forward_icon, "Forward", self)
        self.forward_action.setEnabled(False)
        self.forward_action.triggered.connect(self.go_forward)
        self.toolbar.addAction(self.forward_action)

        # Refresh Selected Feed Button
        refresh_icon = self.style().standardIcon(QStyle.SP_BrowserReload)
        refresh_action = QAction(refresh_icon, "Refresh Selected Feed", self)
        refresh_action.triggered.connect(self.refresh_feed)
        self.toolbar.addAction(refresh_action)

        # Force Refresh All Feeds Button
        force_refresh_icon = self.style().standardIcon(QStyle.SP_BrowserReload)
        force_refresh_action = QAction(force_refresh_icon, "Force Refresh All Feeds", self)
        force_refresh_action.triggered.connect(self.force_refresh_all_feeds)
        self.toolbar.addAction(force_refresh_action)

        # Set the toolbar visible by default
        self.toolbar.setVisible(True)

    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.exec_()

    def feeds_context_menu(self, position):
        menu = QMenu()
        remove_action = QAction("Remove Feed", self)
        remove_action.triggered.connect(self.remove_feed)
        menu.addAction(remove_action)
        menu.exec_(self.feeds_list.viewport().mapToGlobal(position))

    def show_header_menu(self, position):
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
        action = self.sender()
        index = action.data()
        if checked:
            self.articles_tree.showColumn(index)
        else:
            self.articles_tree.hideColumn(index)

    def add_feed(self):
        url = self.feed_url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a feed URL.")
            return
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        if url in [feed['url'] for feed in self.feeds]:
            QMessageBox.information(self, "Duplicate Feed", "This feed is already added.")
            return
        # Fetch the feed to get its title
        try:
            feed = feedparser.parse(url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            feed_title = feed.feed.get('title', url)
        except Exception as e:
            QMessageBox.critical(self, "Feed Error", f"Failed to load feed: {e}")
            return
        # Check if title already exists
        if feed_title in [feed['title'] for feed in self.feeds]:
            QMessageBox.information(self, "Duplicate Feed", "A feed with this title is already added.")
            return
        # Add feed to feeds list
        feed_data = {'title': feed_title, 'url': url, 'entries': []}
        self.feeds.append(feed_data)
        # Add to the list widget
        item = QListWidgetItem(feed_title)
        item.setData(Qt.UserRole, url)
        self.feeds_list.addItem(item)
        self.feed_url_input.clear()
        self.statusBar().showMessage(f"Added feed: {feed_title}")
        logging.info(f"Added feed: {feed_title}")
        self.save_feeds()

    def remove_feed(self):
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
                logging.info(f"Removed feed: {title}")
            self.save_feeds()

    def load_feeds(self):
        if os.path.exists('feeds.json'):
            with open('feeds.json', 'r') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Old format detected, convert to new format
                    self.feeds = []
                    for url in data.keys():
                        feed_title = url  # Temporarily use the URL as the title
                        feed_data = {'title': feed_title, 'url': url, 'entries': data[url].get('entries', [])}
                        self.feeds.append(feed_data)
                elif isinstance(data, list):
                    # New format
                    self.feeds = data
                else:
                    self.feeds = []
                for feed in self.feeds:
                    item = QListWidgetItem(feed['title'])
                    item.setData(Qt.UserRole, feed['url'])
                    self.feeds_list.addItem(item)
            # Update feed titles for feeds that have the URL as title
            self.update_feed_titles()
        else:
            self.feeds = []

    def update_feed_titles(self):
        for feed in self.feeds:
            if feed['title'] == feed['url']:
                try:
                    parsed_feed = feedparser.parse(feed['url'])
                    if parsed_feed.bozo and parsed_feed.bozo_exception:
                        raise parsed_feed.bozo_exception
                    feed_title = parsed_feed.feed.get('title', feed['url'])
                    feed['title'] = feed_title
                    # Update the item in the list
                    for index in range(self.feeds_list.count()):
                        item = self.feeds_list.item(index)
                        if item.data(Qt.UserRole) == feed['url']:
                            item.setText(feed_title)
                            break
                except Exception as e:
                    logging.error(f"Failed to update feed title for {feed['url']}: {e}")
        # Save the updated feeds
        self.save_feeds()

    def save_feeds(self):
        try:
            with open('feeds.json', 'w') as f:
                json.dump(self.feeds, f, indent=4)
            logging.info("Feeds saved successfully.")
        except Exception as e:
            logging.error(f"Failed to save feeds: {e}")

    def load_articles(self):
        if not self.api_key:
            QMessageBox.warning(self, "API Key Missing", "Please set your OMDb API key in Settings.")
            return
        selected_items = self.feeds_list.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        url = item.data(Qt.UserRole)
        self.statusBar().showMessage(f"Loading articles from {item.text()}")
        self.thread = FetchFeedThread(url)
        self.thread.feed_fetched.connect(self.on_feed_fetched)
        self.thread.start()

    def on_feed_fetched(self, url, feed):
        if feed is None:
            QMessageBox.critical(self, "Feed Error", f"Failed to load feed.")
            return
        self.current_entries = feed.entries
        # Update entries in feeds data
        for feed_data in self.feeds:
            if feed_data['url'] == url:
                feed_data['entries'] = self.current_entries
                break
        self.articles_tree.clear()
        for index, entry in enumerate(self.current_entries):
            title = entry.get('title', 'No Title')
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                date_obj = datetime.datetime(*date_struct[:6])
                date_formatted = date_obj.strftime('%d-%m-%Y')
            else:
                date_formatted = 'No Date'

            # Initially set placeholders for new columns
            rating_str = 'Loading...'
            released_str = ''
            genre_str = ''
            director_str = ''

            item = ArticleTreeWidgetItem([title, date_formatted, rating_str, released_str, genre_str, director_str])
            
            # Check if the article is unread
            article_id = entry.get('id', entry.get('link', title))
            if article_id not in self.read_articles:
                item.setIcon(0, self.get_unread_icon())  # Set blue dot icon
            self.articles_tree.addTopLevelItem(item)
        self.statusBar().showMessage(f"Loaded {len(self.current_entries)} articles")
        logging.info(f"Loaded {len(self.current_entries)} articles from {url}")

        # Start the movie data fetching thread
        self.movie_data_thread = FetchMovieDataThread(self.current_entries, self.api_key, self.movie_data_cache)
        self.movie_data_thread.movie_data_fetched.connect(self.update_movie_info)
        self.movie_data_thread.start()

    def update_movie_info(self, index, movie_data):
        item = self.articles_tree.topLevelItem(index)
        if item:
            # Parse and set Rating
            imdb_rating = movie_data.get('imdbrating', 'N/A')
            # Extract numeric part if possible
            rating_value = self.parse_rating(imdb_rating)
            item.setData(2, Qt.UserRole, rating_value)
            item.setText(2, imdb_rating)

            # Parse and set Release Date
            released = movie_data.get('released', '')
            release_date = self.parse_release_date(released)
            item.setData(3, Qt.UserRole, release_date)
            item.setText(3, released)

            # Set other fields
            genre = movie_data.get('genre', '')
            director = movie_data.get('director', '')
            item.setText(4, genre)
            item.setText(5, director)

            # Store the movie data in the entry for later use
            self.current_entries[index]['movie_data'] = movie_data

        # After updating all items, sorting is already enabled and can be triggered by user

    def parse_rating(self, rating_str):
        try:
            # Extract the numeric part before '/'
            return float(rating_str.split('/')[0])
        except:
            return 0.0

    def parse_release_date(self, released_str):
        try:
            # Convert to datetime object
            return datetime.datetime.strptime(released_str, '%d %b %Y')
        except:
            return datetime.datetime.min

    def display_content(self):
        selected_items = self.articles_tree.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        index = self.articles_tree.indexOfTopLevelItem(item)
        entry = self.current_entries[index]
        title = entry.get('title', 'No Title')
        date_formatted = item.text(1)

        # Safely extract content
        if 'content' in entry and entry['content']:
            content = entry['content'][0].get('value', '')
        elif 'summary' in entry:
            content = entry.get('summary', 'No Content')
        else:
            content = 'No Content Available.'

        # Extract images
        images_html = ''
        if 'media_content' in entry:
            for media in entry.media_content:
                img_url = media.get('url')
                if img_url:
                    images_html += f'<img src="{img_url}" alt="" /><br/>'
        elif 'media_thumbnail' in entry:
            for media in entry.media_thumbnail:
                img_url = media.get('url')
                if img_url:
                    images_html += f'<img src="{img_url}" alt="" /><br/>'
        elif 'links' in entry:
            for link in entry.links:
                if link.get('rel') == 'enclosure' and 'image' in link.get('type', ''):
                    img_url = link.get('href')
                    if img_url:
                        images_html += f'<img src="{img_url}" alt="" /><br/>'

        # Get the link to the original article
        link = entry.get('link', '')

        # Include additional movie data if available
        movie_data = entry.get('movie_data', {})
        movie_info_html = ''
        if movie_data:
            # Poster
            poster_url = movie_data.get('poster', '')
            if poster_url and poster_url != 'N/A':
                movie_info_html += f'<img src="{poster_url}" alt="Poster" style="max-width:200px;" /><br/>'
            # Other details
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
            # Ratings from different sources
            ratings = movie_data.get('ratings', [])
            if ratings:
                ratings_html = '<ul>'
                for rating in ratings:
                    ratings_html += f"<li>{rating.get('Source')}: {rating.get('Value')}</li>"
                ratings_html += '</ul>'
                movie_info_html += f'<p><strong>Ratings:</strong>{ratings_html}</p>'

        # Add CSS styles
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
        h1, h2, h3, h4, h5, h6 {
            font-weight: 600;
            line-height: 1.2;
            margin: 10px 0 5px;
        }
        h1 {
            font-size: 24px;  /* Reduce the font size of h1 */
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

        # Include the link to the original article
        if link:
            read_more = f'<p><a href="{link}">Read more</a></p>'
        else:
            read_more = ''

        # Use h3 tag for the title to make it smaller
        html_content = f"""
        {styles}
        <h3>{title}</h3>
        <p><em>{date_formatted}</em></p>
        {images_html}
        {content}
        {movie_info_html}
        {read_more}
        """

        # Get the base URL
        feed_url = self.feeds_list.currentItem().data(Qt.UserRole)
        self.content_view.setHtml(html_content, baseUrl=QUrl(feed_url))
        self.statusBar().showMessage(f"Displaying article: {title}")
        self.update_navigation_buttons()

        # Mark the article as read
        article_id = entry.get('id', entry.get('link', title))
        if article_id not in self.read_articles:
            self.read_articles.add(article_id)
            item.setIcon(0, QIcon())  # Remove the blue dot
            self.save_read_articles()

    def filter_articles(self, text):
        for i in range(self.articles_tree.topLevelItemCount()):
            item = self.articles_tree.topLevelItem(i)
            if text.lower() in item.text(0).lower():
                item.setHidden(False)
            else:
                item.setHidden(True)

    def go_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.load_history()

    def go_forward(self):
        if self.history_index < len(self.content_history) - 1:
            self.history_index += 1
            self.load_history()

    def load_history(self):
        # Implement history loading if required
        pass

    def update_navigation_buttons(self):
        self.back_action.setEnabled(self.history_index > 0)
        self.forward_action.setEnabled(self.history_index < len(self.content_history) - 1)

    def refresh_feed(self):
        self.load_articles()

    def force_refresh_all_feeds(self):
        if not self.api_key:
            QMessageBox.warning(self, "API Key Missing", "Please set your OMDb API key in Settings.")
            return
        logging.info("Force refreshing all feeds")
        self.statusBar().showMessage("Force refreshing all feeds...")
        for feed_data in self.feeds:
            url = feed_data['url']
            thread = FetchFeedThread(url)
            thread.feed_fetched.connect(self.on_feed_fetched_force_refresh)
            thread.start()

    def on_feed_fetched_force_refresh(self, url, feed):
        if feed is not None:
            # Update entries in feeds data
            for feed_data in self.feeds:
                if feed_data['url'] == url:
                    feed_data['entries'] = feed.entries
                    break
            logging.info(f"Refreshed feed: {url}")
        else:
            logging.error(f"Failed to refresh feed: {url}")

        # If the refreshed feed is currently selected, update the articles tree
        current_feed_item = self.feeds_list.currentItem()
        if current_feed_item and current_feed_item.data(Qt.UserRole) == url:
            self.on_feed_fetched(url, feed)

    def import_feeds(self):
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
                logging.info("Feeds imported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import feeds: {e}")
                logging.error(f"Failed to import feeds from {file_name}: {e}")

    def export_feeds(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    json.dump(self.feeds, f, indent=4)
                self.statusBar().showMessage("Feeds exported")
                logging.info("Feeds exported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export feeds: {e}")
                logging.error(f"Failed to export feeds to {file_name}: {e}")

    def increase_font_size(self):
        font = self.font()
        font.setPointSize(font.pointSize() + 1)
        self.setFont(font)

    def decrease_font_size(self):
        font = self.font()
        font.setPointSize(font.pointSize() - 1)
        self.setFont(font)

    def load_read_articles(self):
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        read_articles = settings.value('read_articles', [])
        if read_articles:
            self.read_articles = set(read_articles)
        else:
            self.read_articles = set()

    def save_read_articles(self):
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('read_articles', list(self.read_articles))

    def closeEvent(self, event):
        self.save_feeds()
        # Save settings using QSettings
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.saveState())  # Correctly saveState()
        settings.setValue('splitterState', self.main_splitter.saveState())
        # Save the header state of the articles tree
        settings.setValue('articlesTreeHeaderState', self.articles_tree.header().saveState())
        # Save the movie data cache
        try:
            with open('movie_data_cache.json', 'w') as f:
                json.dump(self.movie_data_cache, f, indent=4)
            logging.info("Movie data cache saved successfully.")
        except Exception as e:
            logging.error(f"Failed to save movie data cache: {e}")
        # Save read articles
        self.save_read_articles()
        event.accept()

    def load_settings(self):
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
        # Load API key
        self.api_key = settings.value('omdb_api_key', '')
        # Load the movie data cache
        if os.path.exists('movie_data_cache.json'):
            try:
                with open('movie_data_cache.json', 'r') as f:
                    self.movie_data_cache = json.load(f)
                logging.info("Movie data cache loaded successfully.")
            except Exception as e:
                logging.error(f"Failed to load movie data cache: {e}")
                self.movie_data_cache = {}
        else:
            self.movie_data_cache = {}

    def get_unread_icon(self):
        # Create a simple blue dot pixmap
        pixmap = QPixmap(10, 10)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QBrush(QColor(0, 122, 204)))  # A pleasant blue color
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 10, 10)
        painter.end()
        return QIcon(pixmap)

    def on_feed_fetched(self, url, feed):
        if feed is None:
            QMessageBox.critical(self, "Feed Error", f"Failed to load feed.")
            return
        self.current_entries = feed.entries
        # Update entries in feeds data
        for feed_data in self.feeds:
            if feed_data['url'] == url:
                feed_data['entries'] = self.current_entries
                break
        self.articles_tree.clear()
        for index, entry in enumerate(self.current_entries):
            title = entry.get('title', 'No Title')
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                date_obj = datetime.datetime(*date_struct[:6])
                date_formatted = date_obj.strftime('%d-%m-%Y')
            else:
                date_formatted = 'No Date'

            # Initially set placeholders for new columns
            rating_str = 'Loading...'
            released_str = ''
            genre_str = ''
            director_str = ''

            item = ArticleTreeWidgetItem([title, date_formatted, rating_str, released_str, genre_str, director_str])
            
            # Check if the article is unread
            article_id = entry.get('id', entry.get('link', title))
            if article_id not in self.read_articles:
                item.setIcon(0, self.get_unread_icon())  # Set blue dot icon
            self.articles_tree.addTopLevelItem(item)
        self.statusBar().showMessage(f"Loaded {len(self.current_entries)} articles")
        logging.info(f"Loaded {len(self.current_entries)} articles from {url}")

        # Start the movie data fetching thread
        self.movie_data_thread = FetchMovieDataThread(self.current_entries, self.api_key, self.movie_data_cache)
        self.movie_data_thread.movie_data_fetched.connect(self.update_movie_info)
        self.movie_data_thread.start()

    def update_movie_info(self, index, movie_data):
        item = self.articles_tree.topLevelItem(index)
        if item:
            # Parse and set Rating
            imdb_rating = movie_data.get('imdbrating', 'N/A')
            # Extract numeric part if possible
            rating_value = self.parse_rating(imdb_rating)
            item.setData(2, Qt.UserRole, rating_value)
            item.setText(2, imdb_rating)

            # Parse and set Release Date
            released = movie_data.get('released', '')
            release_date = self.parse_release_date(released)
            item.setData(3, Qt.UserRole, release_date)
            item.setText(3, released)

            # Set other fields
            genre = movie_data.get('genre', '')
            director = movie_data.get('director', '')
            item.setText(4, genre)
            item.setText(5, director)

            # Store the movie data in the entry for later use
            self.current_entries[index]['movie_data'] = movie_data

    def parse_rating(self, rating_str):
        try:
            # Extract the numeric part before '/'
            return float(rating_str.split('/')[0])
        except:
            return 0.0

    def parse_release_date(self, released_str):
        try:
            # Convert to datetime object
            return datetime.datetime.strptime(released_str, '%d %b %Y')
        except:
            return datetime.datetime.min

    def display_content(self):
        selected_items = self.articles_tree.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        index = self.articles_tree.indexOfTopLevelItem(item)
        entry = self.current_entries[index]
        title = entry.get('title', 'No Title')
        date_formatted = item.text(1)

        # Safely extract content
        if 'content' in entry and entry['content']:
            content = entry['content'][0].get('value', '')
        elif 'summary' in entry:
            content = entry.get('summary', 'No Content')
        else:
            content = 'No Content Available.'

        # Extract images
        images_html = ''
        if 'media_content' in entry:
            for media in entry.media_content:
                img_url = media.get('url')
                if img_url:
                    images_html += f'<img src="{img_url}" alt="" /><br/>'
        elif 'media_thumbnail' in entry:
            for media in entry.media_thumbnail:
                img_url = media.get('url')
                if img_url:
                    images_html += f'<img src="{img_url}" alt="" /><br/>'
        elif 'links' in entry:
            for link in entry.links:
                if link.get('rel') == 'enclosure' and 'image' in link.get('type', ''):
                    img_url = link.get('href')
                    if img_url:
                        images_html += f'<img src="{img_url}" alt="" /><br/>'

        # Get the link to the original article
        link = entry.get('link', '')

        # Include additional movie data if available
        movie_data = entry.get('movie_data', {})
        movie_info_html = ''
        if movie_data:
            # Poster
            poster_url = movie_data.get('poster', '')
            if poster_url and poster_url != 'N/A':
                movie_info_html += f'<img src="{poster_url}" alt="Poster" style="max-width:200px;" /><br/>'
            # Other details
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
            # Ratings from different sources
            ratings = movie_data.get('ratings', [])
            if ratings:
                ratings_html = '<ul>'
                for rating in ratings:
                    ratings_html += f"<li>{rating.get('Source')}: {rating.get('Value')}</li>"
                ratings_html += '</ul>'
                movie_info_html += f'<p><strong>Ratings:</strong>{ratings_html}</p>'

        # Add CSS styles
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
        h1, h2, h3, h4, h5, h6 {
            font-weight: 600;
            line-height: 1.2;
            margin: 10px 0 5px;
        }
        h1 {
            font-size: 24px;  /* Reduce the font size of h1 */
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

        # Include the link to the original article
        if link:
            read_more = f'<p><a href="{link}">Read more</a></p>'
        else:
            read_more = ''

        # Use h3 tag for the title to make it smaller
        html_content = f"""
        {styles}
        <h3>{title}</h3>
        <p><em>{date_formatted}</em></p>
        {images_html}
        {content}
        {movie_info_html}
        {read_more}
        """

        # Get the base URL
        feed_url = self.feeds_list.currentItem().data(Qt.UserRole)
        self.content_view.setHtml(html_content, baseUrl=QUrl(feed_url))
        self.statusBar().showMessage(f"Displaying article: {title}")
        self.update_navigation_buttons()

        # Mark the article as read
        article_id = entry.get('id', entry.get('link', title))
        if article_id not in self.read_articles:
            self.read_articles.add(article_id)
            item.setIcon(0, QIcon())  # Remove the blue dot
            self.save_read_articles()

    def filter_articles(self, text):
        for i in range(self.articles_tree.topLevelItemCount()):
            item = self.articles_tree.topLevelItem(i)
            if text.lower() in item.text(0).lower():
                item.setHidden(False)
            else:
                item.setHidden(True)

    def go_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.load_history()

    def go_forward(self):
        if self.history_index < len(self.content_history) - 1:
            self.history_index += 1
            self.load_history()

    def load_history(self):
        # Implement history loading if required
        pass

    def update_navigation_buttons(self):
        self.back_action.setEnabled(self.history_index > 0)
        self.forward_action.setEnabled(self.history_index < len(self.content_history) - 1)

    def refresh_feed(self):
        self.load_articles()

    def force_refresh_all_feeds(self):
        if not self.api_key:
            QMessageBox.warning(self, "API Key Missing", "Please set your OMDb API key in Settings.")
            return
        logging.info("Force refreshing all feeds")
        self.statusBar().showMessage("Force refreshing all feeds...")
        for feed_data in self.feeds:
            url = feed_data['url']
            thread = FetchFeedThread(url)
            thread.feed_fetched.connect(self.on_feed_fetched_force_refresh)
            thread.start()

    def on_feed_fetched_force_refresh(self, url, feed):
        if feed is not None:
            # Update entries in feeds data
            for feed_data in self.feeds:
                if feed_data['url'] == url:
                    feed_data['entries'] = feed.entries
                    break
            logging.info(f"Refreshed feed: {url}")
        else:
            logging.error(f"Failed to refresh feed: {url}")

        # If the refreshed feed is currently selected, update the articles tree
        current_feed_item = self.feeds_list.currentItem()
        if current_feed_item and current_feed_item.data(Qt.UserRole) == url:
            self.on_feed_fetched(url, feed)

    def import_feeds(self):
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
                logging.info("Feeds imported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Failed to import feeds: {e}")
                logging.error(f"Failed to import feeds from {file_name}: {e}")

    def export_feeds(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Feeds", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'w') as f:
                    json.dump(self.feeds, f, indent=4)
                self.statusBar().showMessage("Feeds exported")
                logging.info("Feeds exported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export feeds: {e}")
                logging.error(f"Failed to export feeds to {file_name}: {e}")

    def increase_font_size(self):
        font = self.font()
        font.setPointSize(font.pointSize() + 1)
        self.setFont(font)

    def decrease_font_size(self):
        font = self.font()
        font.setPointSize(font.pointSize() - 1)
        self.setFont(font)

    def load_read_articles(self):
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        read_articles = settings.value('read_articles', [])
        if read_articles:
            self.read_articles = set(read_articles)
        else:
            self.read_articles = set()

    def save_read_articles(self):
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('read_articles', list(self.read_articles))

    def closeEvent(self, event):
        self.save_feeds()
        # Save settings using QSettings
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.saveState())  # Correctly saveState()
        settings.setValue('splitterState', self.main_splitter.saveState())
        # Save the header state of the articles tree
        settings.setValue('articlesTreeHeaderState', self.articles_tree.header().saveState())
        # Save the movie data cache
        try:
            with open('movie_data_cache.json', 'w') as f:
                json.dump(self.movie_data_cache, f, indent=4)
            logging.info("Movie data cache saved successfully.")
        except Exception as e:
            logging.error(f"Failed to save movie data cache: {e}")
        # Save read articles
        self.save_read_articles()
        event.accept()

    def load_settings(self):
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
        # Load API key
        self.api_key = settings.value('omdb_api_key', '')
        # Load the movie data cache
        if os.path.exists('movie_data_cache.json'):
            try:
                with open('movie_data_cache.json', 'r') as f:
                    self.movie_data_cache = json.load(f)
                logging.info("Movie data cache loaded successfully.")
            except Exception as e:
                logging.error(f"Failed to load movie data cache: {e}")
                self.movie_data_cache = {}
        else:
            self.movie_data_cache = {}

    def get_unread_icon(self):
        # Create a simple blue dot pixmap
        pixmap = QPixmap(10, 10)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QBrush(QColor(0, 122, 204)))  # A pleasant blue color
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 10, 10)
        painter.end()
        return QIcon(pixmap)

    def on_feed_fetched(self, url, feed):
        if feed is None:
            QMessageBox.critical(self, "Feed Error", f"Failed to load feed.")
            return
        self.current_entries = feed.entries
        # Update entries in feeds data
        for feed_data in self.feeds:
            if feed_data['url'] == url:
                feed_data['entries'] = self.current_entries
                break
        self.articles_tree.clear()
        for index, entry in enumerate(self.current_entries):
            title = entry.get('title', 'No Title')
            date_struct = entry.get('published_parsed', entry.get('updated_parsed', None))
            if date_struct:
                date_obj = datetime.datetime(*date_struct[:6])
                date_formatted = date_obj.strftime('%d-%m-%Y')
            else:
                date_formatted = 'No Date'

            # Initially set placeholders for new columns
            rating_str = 'Loading...'
            released_str = ''
            genre_str = ''
            director_str = ''

            item = ArticleTreeWidgetItem([title, date_formatted, rating_str, released_str, genre_str, director_str])
            
            # Check if the article is unread
            article_id = entry.get('id', entry.get('link', title))
            if article_id not in self.read_articles:
                item.setIcon(0, self.get_unread_icon())  # Set blue dot icon
            self.articles_tree.addTopLevelItem(item)
        self.statusBar().showMessage(f"Loaded {len(self.current_entries)} articles")
        logging.info(f"Loaded {len(self.current_entries)} articles from {url}")

        # Start the movie data fetching thread
        self.movie_data_thread = FetchMovieDataThread(self.current_entries, self.api_key, self.movie_data_cache)
        self.movie_data_thread.movie_data_fetched.connect(self.update_movie_info)
        self.movie_data_thread.start()

if __name__ == "__main__":
    def main():
        app = QApplication(sys.argv)
        app.setOrganizationName("YourOrganization")  # Set your organization name
        app.setApplicationName("Small RSS Reader")    # Set your application name
        app.setApplicationDisplayName("Small RSS Reader")  # Set the display name
        reader = RSSReader()
        reader.show()

        # Handle Ctrl+C (Cmd+C) to quit the application
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        sys.exit(app.exec_())

    main()
