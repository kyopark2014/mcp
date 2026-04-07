---
name: book-search
description: "Search for books using Kyobo Book Centre's online catalog. Use when users want to find books by keyword, title, author, or topic. Supports Korean and English search terms and returns book titles with direct purchase links. Perfect for book recommendations, finding specific titles, or discovering books on particular subjects."
---

# Book Search

Search for books using Kyobo Book Centre's online catalog.

## Script Location

**IMPORTANT**: Always use the FULL path `skills/book-search/scripts/search_books.py` — do NOT shorten to `scripts/search_books.py`.

## Quick Start

```python
import subprocess
result = subprocess.run(['python', 'skills/book-search/scripts/search_books.py', 'keyword'],
                       capture_output=True, text=True)
print(result.stdout)
```

## Usage Examples

```python
# Search by keyword (Korean)
subprocess.run(['python', 'skills/book-search/scripts/search_books.py', '프로그래밍'], capture_output=True, text=True)

# Search by author
subprocess.run(['python', 'skills/book-search/scripts/search_books.py', '무라카미 하루키'], capture_output=True, text=True)

# Search by topic (English)
subprocess.run(['python', 'skills/book-search/scripts/search_books.py', 'artificial intelligence'], capture_output=True, text=True)
```

Returns up to 5 results with titles and direct Kyobo purchase links.

## Dependencies

```bash
pip install requests beautifulsoup4
```