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
    QSizePolicy  # Added QSizePolicy here
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QUrl, QSettings, QSize
from PyQt5.QtGui import QDesktopServices, QFont

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
        self.extract_movie_title = None
        self.fetch_movie_data = None
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
        self.init_ui()
        self.load_feeds()
        self.load_settings()

    def init_ui(self):
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create vertical splitter to divide top and bottom sections
        self.vertical_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(self.vertical_splitter)

        # Top Section Widget
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)

        # Feeds Panel
        self.init_feeds_panel(top_layout)

        # Articles Panel
        self.init_articles_panel(top_layout)

        # Add top_widget to the vertical splitter
        self.vertical_splitter.addWidget(top_widget)

        # Content Panel (Bottom Section)
        self.init_content_panel(self.vertical_splitter)

        # Set stretch factors to allocate space appropriately
        self.vertical_splitter.setStretchFactor(0, 1)  # Top section (feeds + articles)
        self.vertical_splitter.setStretchFactor(1, 2)  # Bottom section (content)

        # Add Menu and Toolbars
        self.init_menu()
        self.init_toolbar()

        # Status Bar
        self.statusBar().showMessage("Ready")

        # Timer for automatic feed refresh
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_all_feeds)
        self.refresh_timer.start(15 * 60 * 1000)  # Refresh every 15 minutes

    def init_feeds_panel(self, parent_layout):
        self.feeds_panel = QWidget()
        feeds_layout = QHBoxLayout(self.feeds_panel)

        # Feeds Label
        feeds_label = QLabel("RSS Feeds")
        feeds_layout.addWidget(feeds_label)

        # Feeds List Widget
        self.feeds_list = QListWidget()
        self.feeds_list.setMaximumHeight(50)  # Decreased from 100 to 50
        self.feeds_list.itemSelectionChanged.connect(self.load_articles)
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

        # Adjust size policy to minimize unused space
        self.feeds_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        parent_layout.addWidget(self.feeds_panel)

    def init_articles_panel(self, parent_layout):
        self.articles_panel = QWidget()
        articles_layout = QVBoxLayout(self.articles_panel)

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
        self.articles_tree.itemSelectionChanged.connect(self.display_content)
        articles_layout.addWidget(self.articles_tree)

        # Set context menu for header to allow column visibility control
        self.articles_tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.articles_tree.header().customContextMenuRequested.connect(self.show_header_menu)

        parent_layout.addWidget(self.articles_panel)

    def init_content_panel(self, parent):
        self.content_panel = QWidget()
        content_layout = QVBoxLayout(self.content_panel)

        # Content Web View
        self.content_view = QWebEngineView()
        self.content_view.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.content_view.setPage(WebEnginePage(self.content_view))
        content_layout.addWidget(self.content_view)

        parent.addWidget(self.content_panel)

    def init_menu(self):
        menu = self.menuBar()
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

        view_menu = menu.addMenu("View")

        increase_font_action = QAction("Increase Font Size", self)
        increase_font_action.triggered.connect(self.increase_font_size)
        view_menu.addAction(increase_font_action)

        decrease_font_action = QAction("Decrease Font Size", self)
        decrease_font_action.triggered.connect(self.decrease_font_size)
        view_menu.addAction(decrease_font_action)

    def init_toolbar(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)

        # Back Button
        self.back_action = QAction("Back", self)
        self.back_action.setEnabled(False)
        self.back_action.triggered.connect(self.go_back)
        toolbar.addAction(self.back_action)

        # Forward Button
        self.forward_action = QAction("Forward", self)
        self.forward_action.setEnabled(False)
        self.forward_action.triggered.connect(self.go_forward)
        toolbar.addAction(self.forward_action)

        # Refresh Button
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_feed)
        toolbar.addAction(refresh_action)

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
        with open('feeds.json', 'w') as f:
            json.dump(self.feeds, f)

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
        for entry in self.current_entries:
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

            item = QTreeWidgetItem([title, date_formatted, rating_str, released_str, genre_str, director_str])
            self.articles_tree.addTopLevelItem(item)
        self.statusBar().showMessage(f"Loaded {len(self.current_entries)} articles")
        logging.info(f"Loaded {len(self.current_entries)} articles from {url}")

        # Start the movie data fetching thread
        self.movie_data_thread = FetchMovieDataThread(self.current_entries, self.api_key, self.movie_data_cache)
        self.movie_data_thread.extract_movie_title = self.extract_movie_title  # Pass the method
        self.movie_data_thread.fetch_movie_data = self.fetch_movie_data  # Pass the method
        self.movie_data_thread.movie_data_fetched.connect(self.update_movie_info)
        self.movie_data_thread.start()

    def update_movie_info(self, index, movie_data):
        item = self.articles_tree.topLevelItem(index)
        if item:
            rating = movie_data.get('imdbrating', 'N/A')
            released = movie_data.get('released', '')
            genre = movie_data.get('genre', '')
            director = movie_data.get('director', '')
            item.setText(2, rating)
            item.setText(3, released)
            item.setText(4, genre)
            item.setText(5, director)
            # Store the movie data in the entry for later use
            self.current_entries[index]['movie_data'] = movie_data

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

    def display_content(self):
        selected_items = self.articles_tree.selectedItems()
        if not selected_items:
            return
        index = self.articles_tree.indexOfTopLevelItem(selected_items[0])
        entry = self.current_entries[index]
        title = entry.get('title', 'No Title')
        date_formatted = self.articles_tree.topLevelItem(index).text(1)

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

    def refresh_all_feeds(self):
        logging.info("Refreshing all feeds")
        for feed_data in self.feeds:
            url = feed_data['url']
            self.thread = FetchFeedThread(url)
            self.thread.feed_fetched.connect(self.on_feed_fetched_refresh)
            self.thread.start()
        self.statusBar().showMessage("Feeds refreshed")

    def on_feed_fetched_refresh(self, url, feed):
        if feed is not None:
            # Update entries in feeds data
            for feed_data in self.feeds:
                if feed_data['url'] == url:
                    feed_data['entries'] = feed.entries
                    break
            logging.info(f"Refreshed feed: {url}")
        else:
            logging.error(f"Failed to refresh feed: {url}")

    def import_feeds(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Import Feeds", "", "JSON Files (*.json)")
        if file_name:
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

    def export_feeds(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Feeds", "", "JSON Files (*.json)")
        if file_name:
            with open(file_name, 'w') as f:
                json.dump(self.feeds, f)
            self.statusBar().showMessage("Feeds exported")

    def increase_font_size(self):
        font = self.font()
        font.setPointSize(font.pointSize() + 1)
        self.setFont(font)

    def decrease_font_size(self):
        font = self.font()
        font.setPointSize(font.pointSize() - 1)
        self.setFont(font)

    def closeEvent(self, event):
        self.save_feeds()
        # Save settings using QSettings
        settings = QSettings('YourOrganization', 'SmallRSSReader')
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.restoreState())
        settings.setValue('splitterState', self.vertical_splitter.saveState())
        # Save the header state of the articles tree
        settings.setValue('articlesTreeHeaderState', self.articles_tree.header().saveState())
        # Save the movie data cache
        with open('movie_data_cache.json', 'w') as f:
            json.dump(self.movie_data_cache, f)
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
            self.vertical_splitter.restoreState(splitterState)
        headerState = settings.value('articlesTreeHeaderState')
        if headerState:
            self.articles_tree.header().restoreState(headerState)
        # Load API key
        self.api_key = settings.value('omdb_api_key', '')
        # Load the movie data cache
        if os.path.exists('movie_data_cache.json'):
            with open('movie_data_cache.json', 'r') as f:
                self.movie_data_cache = json.load(f)
        else:
            self.movie_data_cache = {}


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Small RSS Reader")
    app.setApplicationDisplayName("Small RSS Reader")
    reader = RSSReader()
    reader.show()

    # Handle Ctrl+C (Cmd+C) to quit the application
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

