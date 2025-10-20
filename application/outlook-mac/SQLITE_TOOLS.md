# SQLite-Based Tools for Outlook MCP Server

This document describes the SQLite-based tools added to the Outlook MCP Server for enhanced email search and analytics capabilities.

## Overview

These tools provide direct read-only access to the Outlook database, enabling faster and more powerful search and analytics operations. They complement the existing AppleScript-based tools, which are still used for write operations and content retrieval.

## Installation

The SQLite-based tools are integrated into the main Outlook MCP Server. No additional installation is required beyond the standard server setup.

## Tools

### 1. Unified Email Search

**Tool Name:** `unified_email_search`

**Description:** A comprehensive search tool that combines multiple filtering capabilities into a single interface.

**Parameters:**
- `query`: Text to search in subject or preview
- `folders`: List of folder names to search in
- `account`: Email address of account to search in
- `is_unread`: Filter by read/unread status
- `has_attachment`: Filter by attachment presence
- `date_filter`: Date filter string (e.g., 'today', 'this week', 'last 30 days', '2025-06-01..2025-06-30')
- `sender`: Filter by sender
- `subject`: Filter by subject
- `limit`: Maximum number of results to return
- `offset`: Offset for pagination

**Example Usage:**
```python
# Search for unread emails from today with "meeting" in the subject
unified_email_search(
    subject="meeting",
    is_unread=True,
    date_filter="today"
)
```

### 2. Email Volume Analytics

**Tool Name:** `email_volume_analytics`

**Description:** Provides statistics about email volume over time.

**Parameters:**
- `account`: Email address of account to analyze
- `date_filter`: Date filter string (e.g., 'last 30 days')
- `group_by`: Time grouping ('day', 'week', 'month')

**Example Usage:**
```python
# Get daily email volume for the last 30 days
email_volume_analytics(
    date_filter="last 30 days",
    group_by="day"
)
```

### 3. Sender Analytics

**Tool Name:** `sender_analytics`

**Description:** Provides statistics about email senders.

**Parameters:**
- `account`: Email address of account to analyze
- `date_filter`: Date filter string (e.g., 'last 30 days')
- `limit`: Maximum number of senders to return

**Example Usage:**
```python
# Get top 10 senders for the last month
sender_analytics(
    date_filter="last 30 days",
    limit=10
)
```

### 4. Folder Analytics

**Tool Name:** `folder_analytics`

**Description:** Provides statistics about email folders.

**Parameters:**
- `account`: Email address of account to analyze
- `include_empty`: Whether to include empty folders

**Example Usage:**
```python
# Get statistics for all non-empty folders
folder_analytics(
    include_empty=False
)
```

### 5. Mailbox Overview

**Tool Name:** `mailbox_overview`

**Description:** Provides a comprehensive overview of the mailbox.

**Parameters:**
- `account`: Email address of account to analyze

**Example Usage:**
```python
# Get overview of the default mailbox
mailbox_overview()
```

### 6. Outlook Database Query

**Tool Name:** `outlook_database_query`

**Description:** A catch-all tool for executing custom read-only SQL queries against the Outlook database.

**Parameters:**
- `query`: SQL query to execute (must be SELECT only)
- `params`: Optional parameters for the query
- `max_results`: Maximum number of results to return

**Example Usage:**
```python
# Get count of emails by folder
outlook_database_query(
    query="""
    SELECT f.Folder_Name, COUNT(*) as EmailCount
    FROM Mail m
    JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
    GROUP BY f.Folder_Name
    ORDER BY EmailCount DESC
    LIMIT 10
    """
)
```

## Date Filter Syntax

The `date_filter` parameter supports the following formats:

- `today`: Emails from today
- `yesterday`: Emails from yesterday
- `this week`: Emails from the current week
- `last week`: Emails from the previous week
- `this month`: Emails from the current month
- `last month`: Emails from the previous month
- `last N days`: Emails from the last N days (e.g., 'last 7 days')
- `YYYY-MM-DD`: Emails from a specific date
- `YYYY-MM-DD..YYYY-MM-DD`: Emails from a date range

## Performance Considerations

- These tools are significantly faster than the AppleScript-based alternatives, especially for large mailboxes.
- The database connection is maintained between tool calls for better performance.
- Pagination is supported for large result sets.
- The database is accessed in read-only mode to prevent accidental modifications.

## Limitations

- These tools only provide read-only access to the database.
- Full email content is not available through these tools and still requires AppleScript.
- The database schema may change with Outlook updates, potentially requiring updates to these tools.

## Testing

A test script is provided to verify the functionality of these tools:

```bash
python3 test_sqlite_tools.py
```

## Implementation Details

The tools are implemented in the following files:

- `outlook_db.py`: Database connection and query execution
- `unified_search.py`: Unified search functionality
- `email_analytics.py`: Email analytics functionality
- `database_query.py`: Catch-all database query functionality
- `sqlite_tools.py`: Tool registration and integration with the MCP server
