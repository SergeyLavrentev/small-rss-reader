# Small RSS Reader

A minimalistic RSS Reader application built with Python and PyQt5. This application allows you to subscribe to RSS feeds, view and search articles, and optionally fetch movie data from the OMDb API.

<img width="512" alt="Screenshot at Oct 13 00-26-26" src="https://github.com/user-attachments/assets/eaa86896-86ed-4502-9da3-91eda418c076">

## Features

- **Manage Feeds**: Add, remove, and reorder RSS feeds.
- **Article Viewing**: Browse articles with titles, dates, and summaries.
- **Search**: Quickly find articles using keywords.
- **Unread Indicators**: Easily spot unread articles.
- **Content Display**: View articles with images and links.
- **OMDb Integration**: Optionally fetch movie data.
- **Customizable Interface**: Toggle toolbar, status bar, and menu bar.
- **Settings**: Configure OMDb API key and refresh intervals.
- **Import/Export**: Backup and restore feeds via JSON files.
- **Auto Refresh**: Automatically update feeds at set intervals.
- **System Tray Integration**: Minimize to tray for a clutter-free experience.

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

1. **Install `pync` Module**
   ```bash
   python3.13 -m pip install pync

---

## Usage

1. **Run the application** in the terminal:
   ```bash
   python mini_rss_reader.py
2. Run the application via Spotlight:
   
## Dependencies

- **PyQt5**: Core GUI components.
- **PyQtWebEngine**: Display web content within the app.
- **feedparser**: Parse RSS feed data.
- **pync**: Send native macOS notifications.
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
