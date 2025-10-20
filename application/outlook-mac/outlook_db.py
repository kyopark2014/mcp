#!/usr/bin/env python3
"""
SQLite database connection module for Outlook MCP Server.
Provides read-only access to the Outlook database.
"""

import os
import sqlite3
import logging
import glob
from typing import Dict, List, Any, Optional, Union, Tuple

# Configure logging
logger = logging.getLogger(__name__)

class OutlookDatabase:
    """Class for read-only access to Outlook SQLite database."""
    
    def __init__(self):
        """Initialize the database connection."""
        self.db_path = None
        self.conn = None
        self.db_available = False
        self.last_error = None
        
    def find_database_path(self) -> Optional[str]:
        """
        Find the Outlook SQLite database file by searching in common locations.
        
        Returns:
            Path to the Outlook SQLite database file or None if not found
        """
        # Base path for Outlook data
        base_path = os.path.expanduser("~/Library/Group Containers/UBF8T346G9.Office/Outlook/")
        
        # Possible profile paths (Outlook 15, 16, etc.)
        profile_paths = [
            "Outlook 15 Profiles/Main Profile/Data/Outlook.sqlite",
            "Outlook 16 Profiles/Main Profile/Data/Outlook.sqlite",
            # Add more potential paths if needed
        ]
        
        # Try each path
        for profile_path in profile_paths:
            full_path = os.path.join(base_path, profile_path)
            if os.path.exists(full_path):
                logger.info(f"Found Outlook database at: {full_path}")
                return full_path
                
        # If no specific path is found, try to find any Outlook.sqlite file
        pattern = os.path.join(base_path, "**/Outlook.sqlite")
        matches = glob.glob(pattern, recursive=True)
        
        if matches:
            logger.info(f"Found Outlook database at: {matches[0]}")
            return matches[0]
            
        # If still not found, log and return None
        error_msg = "Could not find Outlook SQLite database file"
        logger.error(error_msg)
        self.last_error = error_msg
        return None
        
    def connect(self) -> bool:
        """
        Connect to the Outlook database in read-only mode.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # If already connected, return True
            if self.conn is not None:
                return True
                
            if not self.db_path:
                self.db_path = self.find_database_path()
                
            if not self.db_path:
                self.db_available = False
                return False
                
            self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row
            logger.info("Connected to Outlook database")
            self.db_available = True
            return True
        except sqlite3.Error as e:
            logger.error(f"Error connecting to Outlook database: {e}")
            self.db_available = False
            self.last_error = str(e)
            return False
            
    def disconnect(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Disconnected from Outlook database")
            
    def get_error_response(self, error_message=None) -> Dict[str, Any]:
        """Return a standardized error response dictionary."""
        message = error_message or self.last_error or "Database not available"
        return {
            "status": "error",
            "message": message,
            "data": [],
            "db_available": self.db_available
        }
            
    def execute_query(self, query: str, params: tuple = (), empty_result=None, max_retries=1) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Execute a read-only SQL query and return results as a list of dictionaries.
        
        Args:
            query: SQL query to execute (must be SELECT only)
            params: Parameters for the query
            empty_result: Value to return if the database is not available (default: empty list)
            max_retries: Maximum number of reconnection attempts on failure
            
        Returns:
            List of dictionaries representing the query results, or error response dictionary
        """
        if empty_result is None:
            empty_result = []
            
        # Allow SELECT and PRAGMA queries for schema information
        query_lower = query.strip().lower()
        if not (query_lower.startswith("select") or query_lower.startswith("pragma")):
            return self.get_error_response("Only SELECT and PRAGMA queries are allowed")
            
        # Check if database is available
        if not self.db_available or not self.conn:
            if not self.connect():
                return empty_result
                
        retries = 0
        while retries <= max_retries:
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                results = [dict(row) for row in cursor.fetchall()]
                logger.debug(f"Query executed successfully, returned {len(results)} results")
                return results
            except sqlite3.Error as e:
                logger.error(f"Error executing query: {e}")
                self.last_error = str(e)
                
                # If this is a connection error and we have retries left, try reconnecting
                if "no such table" not in str(e).lower() and retries < max_retries:
                    logger.info(f"Attempting to reconnect to database (retry {retries+1}/{max_retries})")
                    self.disconnect()  # Ensure connection is fully closed
                    if self.connect():  # Try to reconnect
                        retries += 1
                        continue
                        
                return empty_result
            
    def get_account_info(self) -> List[Dict[str, Any]]:
        """Get information about all accounts in the database."""
        query = """
        SELECT Record_RecordID, Account_EmailAddress, Account_MailAccountUID
        FROM AccountsExchange
        """
        return self.execute_query(query)
        
    def get_folders(self, account_uid: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all folders, optionally filtered by account.
        
        Args:
            account_uid: Optional account UID to filter by
            
        Returns:
            List of folder information dictionaries
        """
        query = """
        SELECT f.Record_RecordID, f.Folder_Name, f.Folder_ParentID, 
               f.Record_AccountUID, f.Folder_FolderClass, f.Folder_FolderType,
               f.Folder_SpecialFolderType,
               (SELECT COUNT(*) FROM Mail m WHERE m.Record_FolderID = f.Record_RecordID) as EmailCount
        FROM Folders f
        """
        
        params = ()
        if account_uid:
            query += " WHERE f.Record_AccountUID = ?"
            params = (account_uid,)
            
        query += " ORDER BY f.Folder_ParentID, f.Folder_Name"
        
        return self.execute_query(query, params)
        
    def search_emails(self, 
                     query_text: Optional[str] = None,
                     folder_ids: Optional[List[int]] = None,
                     account_uid: Optional[int] = None,
                     is_unread: Optional[bool] = None,
                     has_attachment: Optional[bool] = None,
                     is_flagged: Optional[bool] = None,
                     category: Optional[str] = None,
                     date_from: Optional[int] = None,
                     date_to: Optional[int] = None,
                     sender: Optional[str] = None,
                     subject: Optional[str] = None,
                     limit: int = 100,
                     offset: int = 0) -> List[Dict[str, Any]]:
        """
        Search emails with various filtering criteria.
        
        Args:
            query_text: Text to search in subject or preview
            folder_ids: List of folder IDs to search in
            account_uid: Account UID to search in
            is_unread: Filter by read/unread status
            has_attachment: Filter by attachment presence
            is_flagged: Filter by flag status (True for flagged emails)
            category: Filter by category name
            date_from: Start date as Unix timestamp
            date_to: End date as Unix timestamp
            sender: Filter by sender
            subject: Filter by subject
            limit: Maximum number of results to return
            offset: Offset for pagination
            
        Returns:
            List of email information dictionaries
        """
        query = """
        SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
               m.Message_TimeReceived, m.Message_ReadFlag, m.Message_HasAttachment,
               m.Message_Preview, f.Folder_Name, f.Record_RecordID as FolderID
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        """
        
        # Add join for category filtering if needed
        if category:
            query += """
            JOIN Mail_Categories mc ON m.Record_RecordID = mc.Record_RecordID
            JOIN Categories c ON mc.Category_RecordID = c.Record_RecordID
            """
            
        query += " WHERE 1=1"
        
        params = []
        
        # Apply filters
        if query_text:
            query += " AND (m.Message_NormalizedSubject LIKE ? OR m.Message_Preview LIKE ?)"
            params.extend([f"%{query_text}%", f"%{query_text}%"])
            
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            query += f" AND m.Record_FolderID IN ({placeholders})"
            params.extend(folder_ids)
            
        if account_uid:
            query += " AND f.Record_AccountUID = ?"
            params.append(account_uid)
            
        if is_unread is not None:
            query += " AND m.Message_ReadFlag = ?"
            params.append(0 if is_unread else 1)
            
        if has_attachment is not None:
            query += " AND m.Message_HasAttachment = ?"
            params.append(1 if has_attachment else 0)
            
        if is_flagged is not None:
            query += " AND m.Record_FlagStatus > ?"
            params.append(0 if is_flagged else -1)
            
        if category:
            query += " AND c.Category_Name = ?"
            params.append(category)
            
        if date_from:
            query += " AND m.Message_TimeReceived >= ?"
            params.append(date_from)
            
        if date_to:
            query += " AND m.Message_TimeReceived <= ?"
            params.append(date_to)
            
        if sender:
            query += " AND m.Message_SenderList LIKE ?"
            params.append(f"%{sender}%")
            
        if subject:
            query += " AND m.Message_NormalizedSubject LIKE ?"
            params.append(f"%{subject}%")
            
        # Add ordering and pagination
        query += " ORDER BY m.Message_TimeReceived DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        return self.execute_query(query, tuple(params))
        
    def get_email_analytics(self, 
                           account_uid: Optional[int] = None,
                           date_from: Optional[int] = None,
                           date_to: Optional[int] = None,
                           group_by: str = "sender") -> List[Dict[str, Any]]:
        """
        Get email analytics grouped by various criteria.
        
        Args:
            account_uid: Account UID to analyze
            date_from: Start date as Unix timestamp
            date_to: End date as Unix timestamp
            group_by: Field to group by (sender, folder, date)
            
        Returns:
            List of analytics results
        """
        if group_by == "sender":
            query = """
            SELECT m.Message_SenderList as GroupValue, COUNT(*) as EmailCount
            FROM Mail m
            JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
            WHERE 1=1
            """
        elif group_by == "folder":
            query = """
            SELECT f.Folder_Name as GroupValue, COUNT(*) as EmailCount
            FROM Mail m
            JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
            WHERE 1=1
            """
        elif group_by == "date":
            query = """
            SELECT strftime('%Y-%m-%d', datetime(m.Message_TimeReceived, 'unixepoch')) as GroupValue,
                   COUNT(*) as EmailCount
            FROM Mail m
            JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
            WHERE 1=1
            """
        else:
            raise ValueError(f"Unsupported group_by value: {group_by}")
            
        params = []
        
        # Apply filters
        if account_uid:
            query += " AND f.Record_AccountUID = ?"
            params.append(account_uid)
            
        if date_from:
            query += " AND m.Message_TimeReceived >= ?"
            params.append(date_from)
            
        if date_to:
            query += " AND m.Message_TimeReceived <= ?"
            params.append(date_to)
            
        # Add grouping and ordering
        query += " GROUP BY GroupValue ORDER BY EmailCount DESC"
        
        return self.execute_query(query, tuple(params))
        
    def get_mailbox_stats(self, account_uid: Optional[int] = None) -> Dict[str, Any]:
        """
        Get statistics about the mailbox.
        
        Args:
            account_uid: Optional account UID to filter by
            
        Returns:
            Dictionary with mailbox statistics
        """
        # Check if database is available
        if not self.db_available or not self.conn:
            if not self.connect():
                return {
                    "status": "error",
                    "message": f"Database not available: {self.last_error}",
                    "TotalEmails": 0,
                    "UnreadEmails": 0,
                    "EmailsWithAttachments": 0,
                    "TopFolders": []
                }
        
        stats = {
            "status": "success",
            "db_available": self.db_available
        }
        
        # Total email count
        query = """
        SELECT COUNT(*) as TotalEmails,
               SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as UnreadEmails,
               SUM(CASE WHEN m.Message_HasAttachment = 1 THEN 1 ELSE 0 END) as EmailsWithAttachments
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        """
        
        params = ()
        if account_uid:
            query += " WHERE f.Record_AccountUID = ?"
            params = (account_uid,)
            
        results = self.execute_query(query, params)
        if isinstance(results, dict) and "status" in results and results["status"] == "error":
            return results
            
        if results and len(results) > 0:
            stats.update(results[0])
        else:
            stats.update({
                "TotalEmails": 0,
                "UnreadEmails": 0,
                "EmailsWithAttachments": 0
            })
            
        # Folder statistics
        query = """
        SELECT f.Folder_Name, COUNT(*) as EmailCount,
               SUM(CASE WHEN m.Message_ReadFlag = 0 THEN 1 ELSE 0 END) as UnreadCount
        FROM Mail m
        JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
        """
        
        if account_uid:
            query += " WHERE f.Record_AccountUID = ?"
            
        query += " GROUP BY f.Record_RecordID ORDER BY EmailCount DESC LIMIT 10"
        
        folder_stats = self.execute_query(query, params)
        if isinstance(folder_stats, dict) and "status" in folder_stats and folder_stats["status"] == "error":
            stats["TopFolders"] = []
        else:
            stats["TopFolders"] = folder_stats
        
        return stats
        
    def execute_custom_query(self, query: str, params: tuple = (), max_results: int = 1000) -> Dict[str, Any]:
        """
        Execute a custom read-only SQL query with safety checks.
        
        Args:
            query: SQL query to execute (must be SELECT only)
            params: Parameters for the query
            max_results: Maximum number of results to return
            
        Returns:
            Dictionary with query results and metadata
        """
        if not query.strip().lower().startswith("select"):
            return {
                "status": "error",
                "message": "Only SELECT queries are allowed",
                "results": [],
                "count": 0,
                "db_available": self.db_available
            }
            
        # Check if database is available
        if not self.db_available or not self.conn:
            if not self.connect():
                return {
                    "status": "error",
                    "message": f"Database not available: {self.last_error}",
                    "results": [],
                    "count": 0,
                    "db_available": False
                }
                
        try:
            # Add LIMIT clause if not present
            if "limit" not in query.lower():
                query += f" LIMIT {max_results}"
                
            cursor = self.conn.cursor()
            start_time = __import__('time').time()
            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]
            end_time = __import__('time').time()
            
            return {
                "status": "success",
                "results": results,
                "count": len(results),
                "query_time_ms": round((end_time - start_time) * 1000, 2),
                "truncated": len(results) >= max_results,
                "db_available": self.db_available
            }
        except sqlite3.Error as e:
            logger.error(f"Error executing custom query: {e}")
            self.last_error = str(e)
            return {
                "status": "error",
                "message": str(e),
                "results": [],
                "count": 0,
                "db_available": self.db_available
            }
            
    def get_schema_info(self) -> Dict[str, Any]:
        """
        Get information about the database schema.
        
        Returns:
            Dictionary with table and column information
        """
        # Check if database is available
        if not self.db_available and not self.conn:
            if not self.connect():
                return {
                    "status": "error",
                    "message": f"Database not available: {self.last_error}",
                    "tables": {},
                    "db_available": False
                }
        
        schema = {
            "status": "success",
            "tables": {},
            "db_available": self.db_available
        }
        
        # Get list of tables
        tables = self.execute_query("SELECT name FROM sqlite_master WHERE type='table'")
        if isinstance(tables, dict) and "status" in tables and tables["status"] == "error":
            return tables
        
        for table in tables:
            table_name = table["name"]
            columns = self.execute_query(f"PRAGMA table_info({table_name})")
            if isinstance(columns, dict) and "status" in columns and columns["status"] == "error":
                continue
                
            schema["tables"][table_name] = {
                "columns": [{"name": col["name"], "type": col["type"]} for col in columns]
            }
            
        return schema


# Singleton instance
outlook_db = OutlookDatabase()
