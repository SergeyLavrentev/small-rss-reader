# Small RSS Reader

A minimalistic RSS Reader application built with Python and PyQt5. This application allows you to subscribe to RSS feeds, view and search articles, and optionally fetch movie data from the OMDb API.

<img width="1070" alt="SCR-20241023-pbzy" src="https://github.com/user-attachments/assets/a994e306-210b-447f-8702-698779b9bc83">

## Features

## Features

- **Manage Feeds**: Add, remove, and reorder RSS feeds with smart, domain-based grouping.
- **Article Viewing**: Browse articles with titles, dates, summaries, images, and links.
- **Search**: Quickly find articles using keywords across titles, summaries, and content.
- **Unread Indicators**: Easily spot unread articles with visual markers.
- **Background Article Opening**: Open articles in the browser in the background without losing focus.
- **OMDb Integration**: Optionally fetch and display movie data for relevant articles.
- **Customizable Interface**: Toggle the toolbar, status bar, and menu bar; adjust fonts and display settings.
- **Settings**: Configure OMDb API key, refresh intervals, notifications, tray icon behavior, and iCloud backup.
- **Import/Export**: Backup and restore feeds and settings via JSON files.
- **Auto Refresh**: Automatically update feeds at set intervals.
- **System Tray Integration**: Minimize the application to the system tray for a clutter-free experience.
- **iCloud Backup & Restore**: Automatically backup and restore feeds and user settings to/from iCloud.

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/small-rss-reader.git
   cd small-rss-reader
2. **Create a virtual environment (optional but recommended):**
    ```bash 
    python -m venv venv
3. **Activate the virtual environment:**
   ```bash
    source venv/bin/activate
4. **Install the dependencies**:
   ```bash
   pip install -r requirements.txt
5. **Build the application**:
   ```bash
   make clean build install

## Native macOS Notifications
Stay updated with native macOS notifications for new articles.
Please enable notifications for the App in System Preferences > Security & Privacy > Privacy > Notifications.

---

## Usage

1. **Run the application** in the terminal:
   ```bash
   python small_rss_reader.py
2. Run the application via Spotlight:
   
## Dependencies

- **PyQt5**: Core GUI components.
- **PyQtWebEngine**: Display web content within the app.
- **feedparser**: Parse RSS feed data.
- **omdbapi**: Fetch movie data from the OMDb API.

## OMDb API Key (Optional)

To enable the movie data fetching feature, you need to obtain an API key from [OMDb API](http://www.omdbapi.com/apikey.aspx).

- **How to Get an API Key**:
  1. Go to the [OMDb API website](http://www.omdbapi.com/apikey.aspx).
  2. Choose a plan (the free plan works for basic usage).
  3. Sign up with your email address to receive the API key.

- **Setting the API Key**:
  - Open the application.
  - Go to **File** > **Settings**.
  - Enter your API key in the **OMDb API Key** field.
  - Click **Save**.

**Note**: If no API key is provided, the application will function without fetching movie data, and ratings will be displayed as "N/A".

## Data Management

### JSON Files

The application uses JSON files to store and manage data.

- **`feeds.json`**
  - **Purpose:** Stores your subscribed RSS feeds and their articles.
  - **Location:** Application's working directory.

- **`movie_data_cache.json`**
  - **Purpose:** Caches movie data fetched from the OMDb API to optimize performance.
  - **Location:** Application's working directory.

*These files are managed automatically. Avoid manual edits to prevent data corruption.*
