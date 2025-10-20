#!/usr/bin/env python3
"""
Unified search tool for Outlook MCP Server.
Provides advanced search capabilities using SQLite database.
"""

import time
import logging
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timedelta
import calendar

from outlook_db import outlook_db

# Configure logging
logger = logging.getLogger(__name__)

def parse_date_filter(date_filter: str) -> tuple:
    """
    Parse a date filter string into start and end timestamps.
    
    Args:
        date_filter: String like 'today', 'yesterday', 'this week', 'last week',
                    'this month', 'last month', 'last 7 days', 'last 30 days',
                    or a specific date range like '2025-06-01..2025-06-30'
                    
    Returns:
        Tuple of (start_timestamp, end_timestamp)
    """
    now = datetime.now()
    today = datetime(now.year, now.month, now.day)
    
    if date_filter == "today":
        start = today
        end = today + timedelta(days=1) - timedelta(seconds=1)
    elif date_filter == "yesterday":
        start = today - timedelta(days=1)
        end = today - timedelta(seconds=1)
    elif date_filter == "this week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7) - timedelta(seconds=1)
    elif date_filter == "last week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=7) - timedelta(seconds=1)
    elif date_filter == "this month":
        start = datetime(now.year, now.month, 1)
        last_day = calendar.monthrange(now.year, now.month)[1]
        end = datetime(now.year, now.month, last_day, 23, 59, 59)
    elif date_filter == "last month":
        if now.month == 1:
            start = datetime(now.year - 1, 12, 1)
            end = datetime(now.year, 1, 1) - timedelta(seconds=1)
        else:
            start = datetime(now.year, now.month - 1, 1)
            last_day = calendar.monthrange(now.year, now.month - 1)[1]
            end = datetime(now.year, now.month - 1, last_day, 23, 59, 59)
    elif date_filter.startswith("last "):
        try:
            days = int(date_filter.split(" ")[1])
            start = today - timedelta(days=days)
            end = today + timedelta(days=1) - timedelta(seconds=1)
        except (ValueError, IndexError):
            raise ValueError(f"Invalid date filter format: {date_filter}")
    elif ".." in date_filter:
        try:
            start_str, end_str = date_filter.split("..")
            start = datetime.strptime(start_str.strip(), "%Y-%m-%d")
            end = datetime.strptime(end_str.strip(), "%Y-%m-%d")
            end = end.replace(hour=23, minute=59, second=59)
        except ValueError:
            raise ValueError(f"Invalid date range format: {date_filter}")
    else:
        try:
            # Try to parse as a single date
            start = datetime.strptime(date_filter, "%Y-%m-%d")
            end = start.replace(hour=23, minute=59, second=59)
        except ValueError:
            raise ValueError(f"Invalid date filter format: {date_filter}")
            
    return int(start.timestamp()), int(end.timestamp())

def get_folder_ids_by_names(folder_names: List[str]) -> List[int]:
    """
    Get folder IDs from folder names.
    
    Args:
        folder_names: List of folder names to look up
        
    Returns:
        List of folder IDs
    """
    folder_ids = []
    all_folders = outlook_db.get_folders()
    
    # Handle multiple folders with the same name by collecting all matching IDs
    for name in folder_names:
        # Handle multiple folders with the same name by collecting all matching IDs
        matching_folders = [folder["Record_RecordID"] for folder in all_folders 
                          if folder.get("Folder_Name") == name]
        folder_ids.extend(matching_folders)
        
        # Log ambiguous folder names for debugging
        if len(matching_folders) > 1:
            logger.warning(f"Found {len(matching_folders)} folders named '{name}'. Using all matching folders: {matching_folders}")
        elif len(matching_folders) == 0:
            logger.warning(f"No folder found with name '{name}'")

            
    return folder_ids

def unified_search(
    query: Optional[str] = None,
    folders: Optional[Union[List[str], List[int]]] = None,
    account: Optional[str] = None,
    is_unread: Optional[bool] = None,
    has_attachment: Optional[bool] = None,
    is_flagged: Optional[bool] = None,
    category: Optional[str] = None,
    date_filter: Optional[str] = None,
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Unified search function that combines multiple search capabilities.
    
    Args:
        query: Text to search in subject or preview
        folders: List of folder names or IDs to search in
        account: Email address of account to search in
        is_unread: Filter by read/unread status
        has_attachment: Filter by attachment presence
        is_flagged: Filter by flag status (True for flagged emails)
        category: Filter by category name
        date_filter: Date filter string (e.g., 'today', 'this week')
        sender: Filter by sender
        subject: Filter by subject
        limit: Maximum number of results to return
        offset: Offset for pagination
        
    Returns:
        Dictionary with search results and metadata
    """
    try:
        start_time = time.time()
        
        # Connect to database if not already connected
        if not outlook_db.conn:
            outlook_db.connect()
            
        # Process folder names to IDs if needed
        folder_ids = None
        if folders:
            if all(isinstance(f, int) for f in folders):
                folder_ids = folders
                logger.debug(f"Using provided folder IDs: {folder_ids}")
            else:
                folder_ids = get_folder_ids_by_names(folders)
                logger.debug(f"Resolved folder names {folders} to IDs: {folder_ids}")
                
                # If no folder IDs were found, return empty results with a warning
                if not folder_ids:
                    logger.warning(f"No folders found matching names: {folders}")
                    return {
                        "results": [],
                        "count": 0,
                        "query_time_ms": 0,
                        "warning": f"No folders found matching names: {folders}"
                    }
                
                # Check for ambiguous folder names and prompt user for selection
                ambiguous_folders = []
                all_folders = outlook_db.get_folders()
                all_accounts = outlook_db.get_account_info()
                
                # Create lookup maps for friendly names
                folder_id_to_name = {f["Record_RecordID"]: f.get("Folder_Name", "Unknown") for f in all_folders}
                account_uid_to_email = {a["Account_MailAccountUID"]: a.get("Account_EmailAddress", "Local Archive") for a in all_accounts}
                # Add entry for local archive (Account UID 0)
                account_uid_to_email[0] = "Local Archive"
                
                for name in folders:
                    matching_folders = [f for f in all_folders if f.get("Folder_Name") == name]
                    if len(matching_folders) > 1:
                        folder_info = []
                        for folder in matching_folders:
                            # Get email count for context
                            email_count_query = "SELECT COUNT(*) as count FROM Mail WHERE Record_FolderID = ?"
                            count_result = outlook_db.execute_query(email_count_query, (folder["Record_RecordID"],))
                            email_count = count_result[0]["count"] if count_result else 0
                            
                            # Get full folder path by traversing ancestors
                            def get_folder_path(folder_id, folder_lookup):
                                path = []
                                current_id = folder_id
                                while current_id:
                                    current_folder = next((f for f in all_folders if f["Record_RecordID"] == current_id), None)
                                    if not current_folder:
                                        break
                                    folder_name = current_folder.get("Folder_Name")
                                    if folder_name and folder_name != "None":
                                        if folder_name == "Placeholder_On_My_Computer_Placeholder":
                                            folder_name = "On My Computer"
                                        elif folder_name.startswith("mailto:"):
                                            folder_name = folder_name[7:]  # Remove "mailto:" prefix
                                        path.append(folder_name)
                                    parent_id = current_folder.get("Folder_ParentID")
                                    if parent_id == current_id:  # Prevent infinite loops
                                        break
                                    current_id = parent_id
                                return " > ".join(reversed(path)) if path else "N/A"
                            
                            folder_path = get_folder_path(folder.get("Folder_ParentID"), all_folders)
                            
                            # Get friendly account name
                            account_uid = folder.get("Record_AccountUID", 0)
                            account_name = account_uid_to_email.get(account_uid, "Local Archive")
                            
                            folder_info.append({
                                "folder_id": folder["Record_RecordID"],
                                "folder_name": folder["Folder_Name"],
                                "folder_path": folder_path,
                                "email_count": email_count,
                                "account_name": account_name
                            })
                        ambiguous_folders.append({
                            "folder_name": name,
                            "options": folder_info
                        })
                
                if ambiguous_folders:
                    return {
                        "results": [],
                        "count": 0,
                        "query_time_ms": 0,
                        "ambiguous_folders": ambiguous_folders,
                        "message": "STOP: Multiple folders found with the same name. Do NOT choose for the user. Display ALL folder information exactly as provided (folder_id, folder_name, folder_path regardless of value, email_count, account_name) and ask the user which specific folder ID they want to search, or if they want to search all folders."
                    }
                
        # Process account name to UID if needed
        account_uid = None
        if account:
            accounts = outlook_db.get_account_info()
            logger.debug(f"Available accounts: {accounts}")
            for acc in accounts:
                # Use case-insensitive comparison to match email addresses
                if acc["Account_EmailAddress"].lower() == account.lower():
                    account_uid = acc["Record_RecordID"]
                    logger.debug(f"Found account match: {acc['Account_EmailAddress']} -> {account_uid}")
                    break
                
            if account_uid is None:
                logger.warning(f"No matching account found for '{account}' in the database")
                    
        # Process date filter
        date_from = None
        date_to = None
        if date_filter:
            try:
                date_from, date_to = parse_date_filter(date_filter)
            except ValueError as e:
                return {"error": str(e)}
                
        # Execute search
        results = outlook_db.search_emails(
            query_text=query,
            folder_ids=folder_ids,
            account_uid=account_uid,
            is_unread=is_unread,
            has_attachment=has_attachment,
            is_flagged=is_flagged,
            category=category,
            date_from=date_from,
            date_to=date_to,
            sender=sender,
            subject=subject,
            limit=limit,
            offset=offset
        )
        
        # Format results
        formatted_results = []
        for email in results:
            formatted_results.append({
                "id": email["Record_RecordID"],
                "subject": email["Message_NormalizedSubject"],
                "sender": email["Message_SenderList"],
                "time_received": email["Message_TimeReceived"],
                "time_received_formatted": datetime.fromtimestamp(email["Message_TimeReceived"]).strftime("%Y-%m-%d %H:%M:%S"),
                "is_read": not email["Message_ReadFlag"] == 0,
                "has_attachment": email["Message_HasAttachment"] == 1,
                "preview": email["Message_Preview"],
                "folder": email["Folder_Name"],
                "folder_id": email["FolderID"]
            })
            
        end_time = time.time()
        
        return {
            "results": formatted_results,
            "count": len(formatted_results),
            "query_time_ms": round((end_time - start_time) * 1000, 2)
        }
    except Exception as e:
        logger.error(f"Error in unified search: {e}")
        return {"error": str(e)}
    finally:
        # Keep connection open for future queries
        pass

def test_unified_search():
    """Test the unified search functionality."""
    print("Testing unified search...")
    
    # Test 1: Basic search
    print("\nTest 1: Basic search")
    results = unified_search(query="meeting")
    print(f"Found {results.get('count', 0)} results in {results.get('query_time_ms', 0)} ms")
    if results.get('results'):
        print(f"First result: {results['results'][0]['subject']} from {results['results'][0]['sender']}")
        
    # Test 2: Search with date filter
    print("\nTest 2: Search with date filter")
    results = unified_search(date_filter="today")
    print(f"Found {results.get('count', 0)} results in {results.get('query_time_ms', 0)} ms")
    
    # Test 3: Search for unread emails
    print("\nTest 3: Search for unread emails")
    results = unified_search(is_unread=True, limit=5)
    print(f"Found {results.get('count', 0)} results in {results.get('query_time_ms', 0)} ms")
    
    # Test 4: Search in specific folder
    print("\nTest 4: Search in specific folder")
    results = unified_search(folders=["Inbox"], limit=5)
    print(f"Found {results.get('count', 0)} results in {results.get('query_time_ms', 0)} ms")
    
    # Test 5: Search with multiple filters
    print("\nTest 5: Search with multiple filters")
    results = unified_search(
        is_unread=True,
        has_attachment=True,
        limit=5
    )
    print(f"Found {results.get('count', 0)} results in {results.get('query_time_ms', 0)} ms")
    
    # Close database connection
    outlook_db.disconnect()
    
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Run tests
    test_unified_search()
