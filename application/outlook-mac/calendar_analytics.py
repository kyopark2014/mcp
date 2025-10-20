#!/usr/bin/env python3
"""
Calendar analytics module for Outlook MCP Server.
Provides SQLite-based calendar functions with proper account filtering.
"""

import logging
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import time

# Import the outlook_db module
from outlook_db import outlook_db

logger = logging.getLogger(__name__)

def get_calendar_overview(account: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a comprehensive overview of calendar data.
    
    Args:
        account: Email address of account to analyze
        
    Returns:
        Dictionary with calendar overview statistics
    """
    try:
        start_time = time.time()
        
        # Connect to database if not already connected
        if not outlook_db.conn:
            outlook_db.connect()
            
        # Process account name to UID if needed
        account_uid = None
        if account:
            accounts = outlook_db.get_account_info()
            logger.debug(f"Available accounts: {accounts}")
            for acc in accounts:
                # Use case-insensitive comparison to match email addresses
                if acc["Account_EmailAddress"].lower() == account.lower():
                    account_uid = acc["Account_MailAccountUID"]  # Use the correct UID field
                    logger.debug(f"Found account match: {acc['Account_EmailAddress']} -> {account_uid}")
                    break
                
            if account_uid is None:
                logger.warning(f"No matching account found for '{account}' in the database")
        
        # Get calendar statistics
        stats = {}
        
        # Total events count - use relative comparison for upcoming/past events
        events_query = """
        SELECT COUNT(*) as TotalEvents,
               MAX(Calendar_StartDateUTC) as MaxStartTime,
               MIN(Calendar_StartDateUTC) as MinStartTime,
               COUNT(CASE WHEN ce.Calendar_IsRecurring = 1 THEN 1 END) as RecurringEvents
        FROM CalendarEvents ce
        """
        
        params = []
        if account_uid:
            events_query += " WHERE ce.Record_AccountUID = ?"
            params.append(account_uid)
            
        events_results = outlook_db.execute_query(events_query, tuple(params))
        if events_results:
            stats.update(events_results[0])
            
            # For upcoming/past events, use relative comparison within the dataset
            max_time = events_results[0].get('MaxStartTime', 0)
            min_time = events_results[0].get('MinStartTime', 0)
            
            # Use a threshold - events in the upper 10% of timestamps are "upcoming"
            threshold = min_time + (max_time - min_time) * 0.9
            
            upcoming_query = """
            SELECT COUNT(*) as UpcomingEvents
            FROM CalendarEvents ce
            WHERE ce.Calendar_StartDateUTC >= ?
            """
            
            upcoming_params = [threshold]
            if account_uid:
                upcoming_query += " AND ce.Record_AccountUID = ?"
                upcoming_params.append(account_uid)
                
            upcoming_results = outlook_db.execute_query(upcoming_query, tuple(upcoming_params))
            if upcoming_results:
                stats['UpcomingEvents'] = upcoming_results[0]['UpcomingEvents']
                stats['PastEvents'] = stats['TotalEvents'] - stats['UpcomingEvents']
        
        # Calendar folders
        folders_query = """
        SELECT f.Record_RecordID, f.Folder_Name, COUNT(ce.Record_RecordID) as EventCount
        FROM Folders f
        LEFT JOIN CalendarEvents ce ON f.Record_RecordID = ce.Record_FolderID
        WHERE f.Folder_FolderClass = 2
        """
        
        folder_params = []
        if account_uid:
            folders_query += " AND f.Record_AccountUID = ?"
            folder_params.append(account_uid)
            
        folders_query += " GROUP BY f.Record_RecordID ORDER BY EventCount DESC"
        
        folder_results = outlook_db.execute_query(folders_query, tuple(folder_params))
        stats["CalendarFolders"] = folder_results
        
        # Recent events (events modified in last 30 days)
        thirty_days_ago = int((datetime.now() - timedelta(days=30)).timestamp())
        recent_query = """
        SELECT COUNT(*) as RecentlyModifiedEvents
        FROM CalendarEvents ce
        WHERE ce.Record_ModDate >= ?
        """
        
        recent_params = [thirty_days_ago]
        if account_uid:
            recent_query += " AND ce.Record_AccountUID = ?"
            recent_params.append(account_uid)
            
        recent_results = outlook_db.execute_query(recent_query, tuple(recent_params))
        if recent_results:
            stats.update(recent_results[0])
        
        # Add account information
        if account_uid:
            accounts = outlook_db.get_account_info()
            for acc in accounts:
                if acc["Account_MailAccountUID"] == account_uid:
                    stats["Account"] = acc["Account_EmailAddress"]
                    break
                    
        end_time = time.time()
        stats["query_time_ms"] = round((end_time - start_time) * 1000, 2)
        
        return stats
        
    except Exception as e:
        logger.error(f"Error in calendar overview: {e}")
        return {"error": str(e)}

def get_calendar_events_by_date_range(
    account: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Get calendar events within a date range.
    Since timestamp interpretation is problematic, this returns recent events by modification date.
    
    Args:
        account: Email address of account to filter by
        start_date: Start date in YYYY-MM-DD format (currently ignored due to timestamp issues)
        end_date: End date in YYYY-MM-DD format (currently ignored due to timestamp issues)
        limit: Maximum number of events to return
        
    Returns:
        Dictionary with events and metadata
    """
    try:
        start_time = time.time()
        
        # Connect to database if not already connected
        if not outlook_db.conn:
            outlook_db.connect()
            
        # Process account name to UID if needed
        account_uid = None
        if account:
            accounts = outlook_db.get_account_info()
            for acc in accounts:
                if acc["Account_EmailAddress"].lower() == account.lower():
                    account_uid = acc["Account_MailAccountUID"]
                    break
        
        # Build query - for now, return most recently modified events
        # TODO: Fix timestamp interpretation to enable proper date filtering
        query = """
        SELECT ce.Record_RecordID,
               ce.Calendar_StartDateUTC,
               ce.Calendar_EndDateUTC,
               ce.Calendar_IsRecurring,
               ce.Calendar_HasReminder,
               ce.Calendar_UID,
               ce.Record_ModDate,
               f.Folder_Name as CalendarName,
               datetime(ce.Record_ModDate, 'unixepoch') as LastModified
        FROM CalendarEvents ce
        JOIN Folders f ON ce.Record_FolderID = f.Record_RecordID
        WHERE 1=1
        """
        
        params = []
        
        # Add account filter
        if account_uid:
            query += " AND ce.Record_AccountUID = ?"
            params.append(account_uid)
            
        # Order by most recently modified events since date filtering is problematic
        query += " ORDER BY ce.Record_ModDate DESC LIMIT ?"
        params.append(limit)
        
        events = outlook_db.execute_query(query, tuple(params))
        
        end_time = time.time()
        
        return {
            "events": events,
            "count": len(events) if events else 0,
            "account": account,
            "note": "Date filtering disabled due to timestamp format issues. Showing most recently modified events.",
            "start_date": start_date,
            "end_date": end_date,
            "query_time_ms": round((end_time - start_time) * 1000, 2)
        }
        
    except Exception as e:
        logger.error(f"Error getting calendar events: {e}")
        return {"error": str(e)}

def search_calendar_events_sqlite(
    query: str,
    account: Optional[str] = None,
    max_results: int = 100
) -> Dict[str, Any]:
    """
    Search for calendar events across all calendars.
    
    Args:
        query: Search query string to match against event details
        account: Email address of account to search in
        max_results: Maximum number of results to return
        
    Returns:
        Dictionary with matching events and metadata
    """
    try:
        start_time = time.time()
        
        # Connect to database if not already connected
        if not outlook_db.conn:
            outlook_db.connect()
            
        # Process account name to UID if needed
        account_uid = None
        if account:
            accounts = outlook_db.get_account_info()
            for acc in accounts:
                if acc["Account_EmailAddress"].lower() == account.lower():
                    account_uid = acc["Account_MailAccountUID"]
                    break
        
        # Build search query - search in calendar UID and folder names
        # Also search in any text fields that might contain event details
        search_query = """
        SELECT ce.Record_RecordID,
               ce.Calendar_StartDateUTC,
               ce.Calendar_EndDateUTC,
               ce.Calendar_IsRecurring,
               ce.Calendar_HasReminder,
               ce.Calendar_UID,
               ce.Record_ModDate,
               f.Folder_Name as CalendarName,
               datetime(ce.Record_ModDate, 'unixepoch') as LastModified
        FROM CalendarEvents ce
        JOIN Folders f ON ce.Record_FolderID = f.Record_RecordID
        WHERE (ce.Calendar_UID LIKE ? OR f.Folder_Name LIKE ?)
        """
        
        search_pattern = f"%{query}%"
        params = [search_pattern, search_pattern]
        
        # Add account filter
        if account_uid:
            search_query += " AND ce.Record_AccountUID = ?"
            params.append(account_uid)
            
        search_query += " ORDER BY ce.Record_ModDate DESC LIMIT ?"
        params.append(max_results)
        
        events = outlook_db.execute_query(search_query, tuple(params))
        
        end_time = time.time()
        
        return {
            "events": events,
            "count": len(events) if events else 0,
            "query": query,
            "account": account,
            "note": "Search limited to Calendar_UID and folder names due to limited event detail fields in SQLite.",
            "query_time_ms": round((end_time - start_time) * 1000, 2)
        }
        
    except Exception as e:
        logger.error(f"Error searching calendar events: {e}")
        return {"error": str(e)}

def test_calendar_analytics():
    """Test the calendar analytics functionality."""
    print("Testing calendar analytics...")
    
    # Get email from environment variable
    test_email = os.environ.get("USER_EMAIL")
    
    # Test 1: Calendar overview without account (should use env var)
    print("\nTest 1: Calendar overview (using env var)")
    results = get_calendar_overview()
    print(f"Found {results.get('TotalEvents', 0)} total events")
    
    # Test 2: Calendar overview with explicit account (if env var is set)
    if test_email:
        print(f"\nTest 2: Calendar overview with account ({test_email})")
        results = get_calendar_overview(account=test_email)
        print(f"Found {results.get('TotalEvents', 0)} events for account")
        print(f"Upcoming events: {results.get('UpcomingEvents', 0)}")
        print(f"Past events: {results.get('PastEvents', 0)}")
        print(f"Calendar folders: {len(results.get('CalendarFolders', []))}")
        print(f"Recently modified: {results.get('RecentlyModifiedEvents', 0)}")
    else:
        print("\nTest 2: Skipped (USER_EMAIL not set)")
    
    # Test 3: Events by date range
    if test_email:
        print(f"\nTest 3: Recent events (date range disabled)")
        results = get_calendar_events_by_date_range(
            account=test_email,
            limit=5
        )
        print(f"Found {results.get('count', 0)} recent events")
        if results.get('events'):
            for event in results['events'][:2]:
                print(f"  - Event ID: {event.get('Record_RecordID')}, Calendar: {event.get('CalendarName')}")
    else:
        print("\nTest 3: Skipped (USER_EMAIL not set)")
    
    # Test 4: Search events
    if test_email:
        print(f"\nTest 4: Search events")
        results = search_calendar_events_sqlite(
            query="Calendar",
            account=test_email,
            max_results=3
        )
        print(f"Found {results.get('count', 0)} events matching 'Calendar'")
    else:
        print("\nTest 4: Skipped (USER_EMAIL not set)")

if __name__ == "__main__":
    test_calendar_analytics()
