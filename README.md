# Small RSS Reader

A minimalistic RSS Reader application built with Python and PyQt5. This application allows you to subscribe to RSS feeds, view and search articles, and optionally fetch movie data from the OMDb API.

<img width="512" alt="Screenshot at Oct 13 00-26-26" src="https://github.com/user-attachments/assets/eaa86896-86ed-4502-9da3-91eda418c076">


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
2. **Create a virtual environment (optional but recommended):**
    ```bash 
    python -m venv venv
3. **Activate the virtual environment:**
   ```bash
    source venv/bin/activate
4. **Install the dependencies**:
   ```bash
   pip install -r requirements.txt

---

## Usage

1. **Run the application**:
   ```bash
   python mini_rss_reader.py

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


## 📄 JSON Files

The application utilizes two primary JSON files to manage and persist data:

### 1. `feeds.json`

- **Purpose:**  
  Stores all subscribed RSS feeds, including their titles, URLs, and fetched entries.

- **Location:**  
  Located in the application's working directory (same folder as the main script).

- **Structure:**  
  ```json
  [
      {
          "title": "Feed Title",
          "url": "https://example.com/rss",
          "entries": [
              {
                  "title": "Article Title",
                  "link": "https://example.com/article",
                  "published": "2024-04-01T10:00:00Z",
                  "summary": "Brief summary of the article."
              }
              // More entries...
          ]
      }
      // More feeds...
  ]

### 2. `movie_data_cache.json`

- **Purpose:**
  Caches movie-related data fetched from the OMDb API to optimize performance and reduce redundant API calls.

- **Location:**
  Located in the application's working directory (same folder as the main script).

- **Structure:**
  ```json
  {
      "Inception": {
          "Title": "Inception",
          "Year": "2010",
          "Rated": "PG-13",
          "Released": "16 Jul 2010",
          "Genre": "Action, Adventure, Sci-Fi",
          "Director": "Christopher Nolan",
          "Writer": "Christopher Nolan",
          "Actors": "Leonardo DiCaprio, Joseph Gordon-Levitt, Ellen Page",
          "Plot": "A thief who steals corporate secrets through use of dream-sharing technology...",
          "Language": "English, Japanese, French",
          "Country": "USA, UK",
          "Awards": "Won 4 Oscars. Another 152 wins & 204 nominations.",
          "Poster": "https://example.com/poster.jpg",
          "Ratings": [
              {
                  "Source": "Internet Movie Database",
                  "Value": "8.8/10"
              },
              {
                  "Source": "Rotten Tomatoes",
                  "Value": "87%"
              },
              {
                  "Source": "Metacritic",
                  "Value": "74/100"
              }
          ],
          "Metascore": "74",
          "imdbRating": "8.8",
          "imdbVotes": "2,000,000",
          "imdbID": "tt1375666",
          "Type": "movie",
          "DVD": "07 Dec 2010",
          "BoxOffice": "$292,576,195",
          "Production": "Syncopy, Warner Bros.",
          "Website": "N/A"
      }
      // More cached movies...
  }


