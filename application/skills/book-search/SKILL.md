---
name: book-search
description: Search for books using Kyobo Book Centre's online catalog. Use when users want to find books by keyword, title, author, or topic. Supports Korean and English search terms and returns book titles with direct purchase links. Perfect for book recommendations, finding specific titles, or discovering books on particular subjects.
---

# Book Search

Search for books using Kyobo Book Centre's comprehensive online catalog.

## Quick Start

Use the search script to find books by any keyword:

```python
import subprocess
result = subprocess.run(['python', 'scripts/search_books.py', 'keyword'], 
                       capture_output=True, text=True, cwd='book-search')
print(result.stdout)
```

## Script Location

The search script is located at `skills/book-search/scripts/search_books.py` relative to the application working directory.
**IMPORTANT**: Always use the FULL path `skills/book-search/scripts/search_books.py` — do NOT shorten to `scripts/search_books.py`.

## Features

- **Keyword Search**: Find books by title, author, topic, or any relevant term
- **Korean & English Support**: Search in both Korean and English
- **Top Results**: Returns up to 5 most relevant books
- **Direct Links**: Provides direct URLs to book pages for purchase
- **Error Handling**: Graceful handling of network issues and parsing errors

## Usage Examples

### Basic Search
```python
# Search for programming books
result = subprocess.run(['python', 'scripts/search_books.py', '프로그래밍'], 
                       capture_output=True, text=True, cwd='book-search')
```

### Author Search
```python
# Search by author name
result = subprocess.run(['python', 'scripts/search_books.py', '무라카미 하루키'], 
                       capture_output=True, text=True, cwd='book-search')
```

### Topic Search
```python
# Search by topic
result = subprocess.run(['python', 'scripts/search_books.py', 'artificial intelligence'], 
                       capture_output=True, text=True, cwd='book-search')
```

## Implementation Notes

- Uses web scraping with proper User-Agent headers
- Handles URL encoding for special characters
- Returns formatted results with titles and purchase links
- Limited to top 5 results to avoid overwhelming output
- Includes error handling for network and parsing issues

## Dependencies

The script requires:
- `requests` - for HTTP requests
- `beautifulsoup4` - for HTML parsing
- `urllib.parse` - for URL encoding (built-in)

Install dependencies:
```bash
pip install requests beautifulsoup4
```