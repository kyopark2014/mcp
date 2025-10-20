#!/usr/bin/env python3
"""
Email analytics tool for Outlook MCP Server.
Provides statistics and trends about email usage.
"""

import time
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import re

from outlook_db import outlook_db
from unified_search import parse_date_filter

# Configure logging
logger = logging.getLogger(__name__)

def extract_domain(email_address: str) -> str:
    """
    Extract domain from an email address.
    
    Args:
        email_address: Email address to extract domain from
        
    Returns:
        Domain name or original string if no domain found
    """
    # Simple regex to extract domain from email address
    match = re.search(r'@([^@\s]+)', email_address)
    if match:
        return match.group(1)
    return email_address

def get_email_volume_by_time(
    account: Optional[str] = None,
    date_filter: Optional[str] = None,
    group_by: str = "day"
) -> Dict[str, Any]:
    """
    Get email volume statistics grouped by time period.
    
    Args:
        account: Email address of account to analyze
        date_filter: Date filter string (e.g., 'last 30 days')
        group_by: Time grouping ('day', 'week', 'month')
        
    Returns:
        Dictionary with email volume statistics
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
        else:
            # Default to last 30 days
            now = datetime.now()
            date_to = int(now.timestamp())
            date_from = int((now - timedelta(days=30)).timestamp())
            
        # Prepare query based on grouping
        if group_by == "day":
            time_format = "%Y-%m-%d"
        elif group_by == "week":
            time_format = "%Y-%W"  # ISO week number
        elif group_by == "month":
            time_format = "%Y-%m"
        else:
            return {"error": f"Unsupported group_by value: {group_by}"}
            
        query = f"""
        SELECT strftime('{time_format}', datetime(m.Message_TimeReceived, 'unixepoch')) as TimePeriod,
               COUNT(*) as EmailCount,
               SUM(CASE WHEN m.Message_HasAttachment = 1 THEN 1 ELSE 0 END) as WithAttachments
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        WHERE m.Message_TimeReceived >= ? AND m.Message_TimeReceived <= ?
        """
        
        params = [date_from, date_to]
        
        if account_uid:
            query += " AND f.Record_AccountUID = ?"
            params.append(account_uid)
            
        query += " GROUP BY TimePeriod ORDER BY TimePeriod"
        
        results = outlook_db.execute_query(query, tuple(params))
        
        end_time = time.time()
        
        return {
            "results": results,
            "count": len(results),
            "query_time_ms": round((end_time - start_time) * 1000, 2),
            "date_range": {
                "from": datetime.fromtimestamp(date_from).strftime("%Y-%m-%d"),
                "to": datetime.fromtimestamp(date_to).strftime("%Y-%m-%d")
            }
        }
    except Exception as e:
        logger.error(f"Error in email volume analysis: {e}")
        return {"error": str(e)}

def get_sender_statistics(
    account: Optional[str] = None,
    date_filter: Optional[str] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Get statistics about email senders.
    
    Args:
        account: Email address of account to analyze
        date_filter: Date filter string (e.g., 'last 30 days')
        limit: Maximum number of senders to return
        
    Returns:
        Dictionary with sender statistics including:
        - Overall sender statistics
        - Domain statistics
        - Per-folder breakdown for each sender
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
                
        # Build common WHERE clause for all queries
        where_clause = "1=1"
        params = []
        
        if date_from and date_to:
            where_clause += " AND m.Message_TimeReceived >= ? AND m.Message_TimeReceived <= ?"
            params.extend([date_from, date_to])
            
        if account_uid:
            where_clause += " AND f.Record_AccountUID = ?"
            params.append(account_uid)
        
        # 1. Get overall sender statistics (as before)
        query = f"""
        SELECT m.Message_SenderList as Sender,
               COUNT(*) as EmailCount,
               SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as UnreadCount,
               SUM(CASE WHEN m.Message_HasAttachment = 1 THEN 1 ELSE 0 END) as WithAttachments
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        WHERE {where_clause}
        GROUP BY Sender 
        ORDER BY EmailCount DESC 
        LIMIT ?
        """
        
        query_params = params.copy()
        query_params.append(limit)
        
        results = outlook_db.execute_query(query, tuple(query_params))
        
        # Process results to extract domains
        for result in results:
            result["Domain"] = extract_domain(result["Sender"])
        
        # 2. Get per-folder breakdown for top senders
        sender_folder_query = f"""
        SELECT m.Message_SenderList as Sender,
               f.Folder_Name as FolderName,
               COUNT(*) as EmailCount,
               SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as UnreadCount,
               SUM(CASE WHEN m.Message_HasAttachment = 1 THEN 1 ELSE 0 END) as WithAttachments
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        WHERE {where_clause} AND m.Message_SenderList IN (
            SELECT m2.Message_SenderList 
            FROM Mail m2 
            JOIN Folders f2 ON m2.Record_FolderID = f2.Record_RecordID 
            WHERE {where_clause}
            GROUP BY m2.Message_SenderList 
            ORDER BY COUNT(*) DESC 
            LIMIT ?
        )
        GROUP BY Sender, FolderName
        ORDER BY Sender, EmailCount DESC
        """
        
        sender_folder_params = params.copy() + params.copy()
        sender_folder_params.append(limit)
        
        folder_breakdown = outlook_db.execute_query(sender_folder_query, tuple(sender_folder_params))
            
        # 3. Get domain statistics (as before)
        domain_query = f"""
        SELECT 
            CASE 
                WHEN m.Message_SenderList LIKE '%@%' THEN 
                    substr(m.Message_SenderList, instr(m.Message_SenderList, '@') + 1) 
                ELSE 'unknown' 
            END as Domain,
            COUNT(*) as EmailCount,
            SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as UnreadCount,
            SUM(CASE WHEN m.Message_HasAttachment = 1 THEN 1 ELSE 0 END) as WithAttachments
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        WHERE {where_clause} AND m.Message_SenderList LIKE '%@%'
        GROUP BY Domain 
        ORDER BY EmailCount DESC 
        LIMIT ?
        """
        
        domain_params = params.copy()
        domain_params.append(limit)
        
        domain_results = outlook_db.execute_query(domain_query, tuple(domain_params))
        
        # 4. Get domain folder breakdown
        domain_folder_query = f"""
        SELECT 
            CASE 
                WHEN m.Message_SenderList LIKE '%@%' THEN 
                    substr(m.Message_SenderList, instr(m.Message_SenderList, '@') + 1) 
                ELSE 'unknown' 
            END as Domain,
            f.Folder_Name as FolderName,
            COUNT(*) as EmailCount,
            SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as UnreadCount,
            SUM(CASE WHEN m.Message_HasAttachment = 1 THEN 1 ELSE 0 END) as WithAttachments
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        WHERE {where_clause} AND m.Message_SenderList LIKE '%@%' AND
            CASE 
                WHEN m.Message_SenderList LIKE '%@%' THEN 
                    substr(m.Message_SenderList, instr(m.Message_SenderList, '@') + 1) 
                ELSE 'unknown' 
            END IN (
                SELECT
                    CASE 
                        WHEN m2.Message_SenderList LIKE '%@%' THEN 
                            substr(m2.Message_SenderList, instr(m2.Message_SenderList, '@') + 1) 
                        ELSE 'unknown' 
                    END as Domain
                FROM Mail m2
                JOIN Folders f2 ON m2.Record_FolderID = f2.Record_RecordID 
                WHERE {where_clause} AND m2.Message_SenderList LIKE '%@%'
                GROUP BY Domain
                ORDER BY COUNT(*) DESC
                LIMIT ?
            )
        GROUP BY Domain, FolderName
        ORDER BY Domain, EmailCount DESC
        """
        
        domain_folder_params = params.copy() + params.copy()
        domain_folder_params.append(limit)
        
        domain_folder_breakdown = outlook_db.execute_query(domain_folder_query, tuple(domain_folder_params))
        
        end_time = time.time()
        
        # Organize folder breakdown by sender for easier consumption
        sender_folder_map = {}
        for item in folder_breakdown:
            sender = item["Sender"]
            if sender not in sender_folder_map:
                sender_folder_map[sender] = []
            sender_folder_map[sender].append({
                "folder": item["FolderName"],
                "count": item["EmailCount"],
                "unread": item["UnreadCount"],
                "attachments": item["WithAttachments"]
            })
        
        # Organize folder breakdown by domain for easier consumption
        domain_folder_map = {}
        for item in domain_folder_breakdown:
            domain = item["Domain"]
            if domain not in domain_folder_map:
                domain_folder_map[domain] = []
            domain_folder_map[domain].append({
                "folder": item["FolderName"],
                "count": item["EmailCount"],
                "unread": item["UnreadCount"],
                "attachments": item["WithAttachments"]
            })
        
        return {
            "senders": results,
            "sender_folders": sender_folder_map,
            "domains": domain_results,
            "domain_folders": domain_folder_map,
            "count": len(results),
            "query_time_ms": round((end_time - start_time) * 1000, 2)
        }
    except Exception as e:
        logger.error(f"Error in sender statistics: {e}")
        return {"error": str(e)}

def get_folder_statistics(
    account: Optional[str] = None,
    include_empty: bool = False
) -> Dict[str, Any]:
    """
    Get statistics about email folders.
    
    Args:
        account: Email address of account to analyze
        include_empty: Whether to include empty folders
        
    Returns:
        Dictionary with folder statistics
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
                    account_uid = acc["Record_RecordID"]
                    logger.debug(f"Found account match: {acc['Account_EmailAddress']} -> {account_uid}")
                    break
                
            if account_uid is None:
                logger.warning(f"No matching account found for '{account}' in the database")
                    
        # Prepare query
        query = """
        SELECT f.Record_RecordID as FolderID, f.Folder_Name as FolderName,
               f.Folder_ParentID as ParentID,
               COUNT(m.Record_RecordID) as EmailCount,
               SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as UnreadCount,
               SUM(CASE WHEN m.Message_HasAttachment = 1 THEN 1 ELSE 0 END) as WithAttachments
        FROM Folders f
        LEFT JOIN Mail m ON f.Record_RecordID = m.Record_FolderID
        """
        
        params = []
        
        if account_uid:
            query += " WHERE f.Record_AccountUID = ?"
            params.append(account_uid)
            
        query += " GROUP BY f.Record_RecordID"
        
        if not include_empty:
            query += " HAVING EmailCount > 0"
            
        query += " ORDER BY EmailCount DESC"
        
        results = outlook_db.execute_query(query, tuple(params))
        
        # Build folder hierarchy
        folder_map = {folder["FolderID"]: folder for folder in results}
        root_folders = []
        
        for folder in results:
            parent_id = folder["ParentID"]
            if parent_id in folder_map:
                if "children" not in folder_map[parent_id]:
                    folder_map[parent_id]["children"] = []
                folder_map[parent_id]["children"].append(folder)
            else:
                root_folders.append(folder)
                
        end_time = time.time()
        
        return {
            "folders": root_folders,
            "flat_folders": results,
            "count": len(results),
            "query_time_ms": round((end_time - start_time) * 1000, 2)
        }
    except Exception as e:
        logger.error(f"Error in folder statistics: {e}")
        return {"error": str(e)}

def get_mailbox_overview(account: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a comprehensive overview of the mailbox.
    
    Args:
        account: Email address of account to analyze
        
    Returns:
        Dictionary with mailbox overview statistics
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
                    
        # Get basic statistics
        stats = outlook_db.get_mailbox_stats(account_uid)
        
        # Get recent activity
        now = datetime.now()
        last_week = int((now - timedelta(days=7)).timestamp())
        
        activity_query = """
        SELECT COUNT(*) as RecentEmails,
               SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as RecentUnread
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        WHERE m.Message_TimeReceived >= ?
        """
        
        params = [last_week]
        
        if account_uid:
            activity_query += " AND f.Record_AccountUID = ?"
            params.append(account_uid)
            
        activity_results = outlook_db.execute_query(activity_query, tuple(params))
        
        if activity_results:
            stats.update(activity_results[0])
            
        # Get category information
        category_query = """
        SELECT c.Category_Name, COUNT(*) AS EmailCount
        FROM Mail_Categories mc
        JOIN Categories c ON mc.Category_RecordID = c.Record_RecordID
        """
        
        category_params = []
        if account_uid:
            category_query += " WHERE c.Record_AccountUID = ?"
            category_params.append(account_uid)
            
        category_query += " GROUP BY c.Category_Name ORDER BY EmailCount DESC"
        
        category_results = outlook_db.execute_query(category_query, tuple(category_params))
        stats["Categories"] = category_results
        
        # Get emails in categories
        if category_results:
            emails_in_categories_query = """
            SELECT c.Category_Name, 
                   m.Record_RecordID,
                   m.Message_NormalizedSubject AS Subject, 
                   m.Message_SenderList AS Sender,
                   datetime(m.Message_TimeReceived, 'unixepoch') AS ReceivedTime,
                   f.Folder_Name AS Folder
            FROM Mail_Categories mc
            JOIN Categories c ON mc.Category_RecordID = c.Record_RecordID
            JOIN Mail m ON mc.Record_RecordID = m.Record_RecordID
            JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
            """
            
            emails_params = []
            if account_uid:
                emails_in_categories_query += " WHERE c.Record_AccountUID = ?"
                emails_params.append(account_uid)
                
            emails_in_categories_query += " ORDER BY c.Category_Name, m.Message_TimeReceived DESC"
            
            emails_results = outlook_db.execute_query(emails_in_categories_query, tuple(emails_params))
            
            # Group emails by category
            emails_by_category = {}
            for email in emails_results:
                category = email["Category_Name"]
                if category not in emails_by_category:
                    emails_by_category[category] = []
                emails_by_category[category].append({
                    "id": email["Record_RecordID"],
                    "subject": email["Subject"],
                    "sender": email["Sender"],
                    "received_time": email["ReceivedTime"],
                    "folder": email["Folder"]
                })
            
            stats["EmailsByCategory"] = emails_by_category
            
        # Get account information
        if account_uid:
            accounts = outlook_db.get_account_info()
            for acc in accounts:
                if acc["Record_RecordID"] == account_uid:
                    stats["Account"] = acc["Account_EmailAddress"]
                    break
                    
        end_time = time.time()
        
        stats["query_time_ms"] = round((end_time - start_time) * 1000, 2)
        
        return stats
    except Exception as e:
        logger.error(f"Error in mailbox overview: {e}")
        return {"error": str(e)}

def test_email_analytics():
    """Test the email analytics functionality."""
    print("Testing email analytics...")
    
    # Test 1: Email volume by time
    print("\nTest 1: Email volume by time")
    results = get_email_volume_by_time(date_filter="last 30 days", group_by="day")
    print(f"Found {results.get('count', 0)} time periods in {results.get('query_time_ms', 0)} ms")
    
    # Test 2: Sender statistics
    print("\nTest 2: Sender statistics")
    results = get_sender_statistics(limit=10)
    print(f"Found {results.get('count', 0)} senders in {results.get('query_time_ms', 0)} ms")
    if 'domains' in results:
        print(f"Top domain: {results['domains'][0]['Domain']} with {results['domains'][0]['EmailCount']} emails")
    
    # Test 3: Folder statistics
    print("\nTest 3: Folder statistics")
    results = get_folder_statistics()
    print(f"Found {results.get('count', 0)} folders in {results.get('query_time_ms', 0)} ms")
    
    # Test 4: Mailbox overview
    print("\nTest 4: Mailbox overview")
    results = get_mailbox_overview()
    print(f"Total emails: {results.get('TotalEmails', 0)}, Unread: {results.get('UnreadEmails', 0)}")
    print(f"Query time: {results.get('query_time_ms', 0)} ms")
    
    # Close database connection
    outlook_db.disconnect()
    
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Run tests
    test_email_analytics()
