# Small RSS Reader

A minimalistic RSS Reader application built with Python and PyQt5. This application allows you to subscribe to RSS feeds, view and search articles, and optionally fetch movie data from the OMDb API.

## Features

- **Add and Remove Feeds**: Easily manage your RSS feeds by adding new ones or removing existing ones.
- **Feed Reordering**: Drag and drop feeds to reorder them in the list.
- **Article List View**: Displays articles with details such as Title, Date, Rating, Released Date, Genre, and Director.
- **Article Search**: Search through articles using keywords.
- **Unread Article Indicator**: Unread articles are marked with a blue dot.
- **Mark Feed as Unread**: Reset the read status of all articles in a feed.
- **Content Display**: View the content of articles with support for images and links.
- **Movie Data Integration**: Fetches movie data from the OMDb API if an API key is provided.
- **Customizable Interface**: Toggle the visibility of the toolbar, status bar, and menu bar.
- **Settings**: Configure the OMDb API key and refresh interval.
- **Import/Export Feeds**: Import and export feeds to/from a JSON file.
- **Auto Refresh**: Automatically refresh feeds at a specified interval.

## Prerequisites

- Python 3.6 or newer

## Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/yourusername/small-rss-reader.git
   cd small-rss-reader
2. **Create a virtual environment (optional but recommended):

    ```bash 
    python -m venv venv
3. **Activate the virtual environment:
```bash
    source venv/bin/activate
4. **Install the dependencies**:

   ```bash
   pip install -r requirements.txt


---

### **Part 5: Usage**

```markdown
## Usage

**Run the application**:

   ```bash
   python rss_reader.py

## Dependencies

- **PyQt5**: Provides the core Qt widgets and classes.
- **PyQtWebEngine**: Required for displaying web content within the application (`QWebEngineView`).
- **feedparser**: Used for parsing RSS feed data.
- **omdbapi**: Used for fetching movie data from the OMDb API.

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



