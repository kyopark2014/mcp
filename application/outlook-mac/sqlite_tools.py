#!/usr/bin/env python3
"""
SQLite-based tools for Outlook MCP Server.
These tools provide enhanced search and analytics capabilities.
"""

import logging
import os
from typing import Dict, List, Any, Optional, Union
from functools import wraps

from outlook_db import outlook_db
from unified_search import unified_search
from email_analytics import (
    get_email_volume_by_time,
    get_sender_statistics,
    get_folder_statistics,
    get_mailbox_overview
)
from database_query import execute_database_query, get_database_schema
# Commented out SQLite-based calendar functions due to timestamp conversion issues
# from calendar_analytics import (
#     get_calendar_overview,
#     get_calendar_events_by_date_range,
#     search_calendar_events_sqlite
# )

# Configure logging
logger = logging.getLogger(__name__)

# Create a decorator for logging tool calls
def log_tool_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        tool_name = func.__name__
        logger.info(f"Tool called: {tool_name}")
        logger.info(f"Arguments: args={args}, kwargs={kwargs}")
        try:
            import time
            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed_time = time.time() - start_time
            logger.info(f"Tool {tool_name} completed in {elapsed_time:.2f}s")
            logger.info(f"Result: {result}")
            return result
        except Exception:
            logger.exception(f"Error in tool {tool_name}")
            raise
    return wrapper

def register_tools(mcp):
    """Register all SQLite-based tools with the MCP server."""
    
    # Test database connection at startup
    if outlook_db.connect():
        logger.info(f"Successfully connected to Outlook database at: {outlook_db.db_path}")
        # Keep the connection open for future queries - do not disconnect
    else:
        logger.warning(f"Could not connect to Outlook database: {outlook_db.last_error}")
        logger.warning("SQLite-based tools will return empty results when database operations are requested.")
        logger.info("Non-database functionality will continue to work normally.")
    
    @mcp.tool()
    @log_tool_call
    def unified_email_search(
        query: Optional[str] = None,
        folders: Optional[List[Union[str, int]]] = None,
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
        Unified search tool for finding emails with advanced filtering.
        
        Args:
            query: Text to search in subject or preview
            folders: List of folder names (strings) or folder IDs (integers) to search in
            account: Email address of account to search in
            is_unread: Filter by read/unread status
            has_attachment: Filter by attachment presence
            is_flagged: Filter by flag status (True for flagged emails)
            category: Filter by category name
            date_filter: Date filter string (e.g., 'today', 'this week', 'last 30 days', '2025-06-01..2025-06-30')
            sender: Filter by sender
            subject: Filter by subject
            limit: Maximum number of results to return
            offset: Offset for pagination
            
        Returns:
            Dictionary with search results and metadata
        """
        return unified_search(
            query=query,
            folders=folders,
            account=account,
            is_unread=is_unread,
            has_attachment=has_attachment,
            is_flagged=is_flagged,
            category=category,
            date_filter=date_filter,
            sender=sender,
            subject=subject,
            limit=limit,
            offset=offset
        )

    @mcp.tool()
    @log_tool_call
    def email_volume_analytics(
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
        return get_email_volume_by_time(
            account=account,
            date_filter=date_filter,
            group_by=group_by
        )

    @mcp.tool()
    @log_tool_call
    def sender_analytics(
        account: Optional[str] = None,
        date_filter: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get comprehensive statistics about email senders including per-folder breakdowns.
        
        Args:
            account: Email address of account to analyze
            date_filter: Date filter string (e.g., 'last 30 days')
            limit: Maximum number of senders to return
            
        Returns:
            Dictionary with detailed sender statistics including:
            - Overall counts for top senders
            - Per-folder breakdowns showing where emails from each sender are located
            - Domain-level statistics with per-folder breakdowns
            - Additional metrics: unread counts and attachment counts
        """
        return get_sender_statistics(
            account=account,
            date_filter=date_filter,
            limit=limit
        )

    @mcp.tool()
    @log_tool_call
    def folder_analytics(
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
        return get_folder_statistics(
            account=account,
            include_empty=include_empty
        )

    @mcp.tool()
    @log_tool_call
    def mailbox_overview(account: Optional[str] = None) -> Dict[str, Any]:
        """
        Get a comprehensive overview of the mailbox.
        
        Args:
            account: Email address of account to analyze
            
        Returns:
            Dictionary with mailbox overview statistics
        """
        return get_mailbox_overview(account=account)

    @mcp.tool()
    @log_tool_call
    def outlook_database_query(
        query: str,
        params: Optional[Dict[str, Any]] = None,
        max_results: int = 1000
    ) -> Dict[str, Any]:
        """
        Execute a custom read-only SQL query against the Outlook database.
        
        TOOL HIERARCHY - IMPORTANT:
        This tool should be used as a LAST RESORT after trying more specialized tools:
        1. mailbox_overview - For getting comprehensive mailbox statistics including categories
        2. unified_email_search - For searching emails with advanced filtering
        3. email_volume_analytics - For analyzing email volume over time
        4. sender_statistics - For analyzing sender patterns
        5. folder_analytics - For analyzing folder usage
        
        IMPORTANT: This tool should be used in a two-step process:
        
        STEP 1: ALWAYS call this tool first with an empty query (query="") to retrieve the complete 
        database schema, table structure, and example queries. Example:
            outlook_database_query(query="")
        
        STEP 2: After reviewing the schema, call this tool again with your specific SQL query.
        
        This tool allows direct read-only SQL queries against the Outlook database structure for advanced
        or unique information retrieval needs when existing specialized tools cannot fulfill the request.
        
        Args:
            query: SQL query to execute (must be SELECT only) or empty string to get schema
            params: Optional parameters for the query
            max_results: Maximum number of results to return
            
        Returns:
            Dictionary with query results and metadata or complete schema information
        """
        if not query:
            # If no query is provided, return schema information
            return get_database_schema()
            
        return execute_database_query(
            query=query,
            params=params,
            max_results=max_results
        )
    
    # Commented out SQLite-based calendar tools due to timestamp conversion issues
    # # Calendar-related tools
    # @mcp.tool()
    # @log_tool_call
    # def calendar_overview(account: Optional[str] = None) -> Dict[str, Any]:
    #     """
    #     Get a comprehensive overview of calendar data.
    #     
    #     Args:
    #         account: Email address of account to analyze (uses USER_EMAIL env var if not provided)
    #         
    #     Returns:
    #         Dictionary with calendar overview statistics
    #     """
    #     # Resolve account - use environment variable if not provided
    #     if not account:
    #         account = os.environ.get("USER_EMAIL")
    #         
    #     return get_calendar_overview(account=account)
    # 
    # @mcp.tool()
    # @log_tool_call
    # def calendar_events_by_date_range(
    #     account: Optional[str] = None,
    #     start_date: Optional[str] = None,
    #     end_date: Optional[str] = None,
    #     limit: int = 100
    # ) -> Dict[str, Any]:
    #     """
    #     Get calendar events within a date range.
    #     
    #     Args:
    #         account: Email address of account to filter by (uses USER_EMAIL env var if not provided)
    #         start_date: Start date in YYYY-MM-DD format
    #         end_date: End date in YYYY-MM-DD format
    #         limit: Maximum number of events to return
    #         
    #     Returns:
    #         Dictionary with events and metadata
    #     """
    #     # Resolve account - use environment variable if not provided
    #     if not account:
    #         account = os.environ.get("USER_EMAIL")
    #         
    #     return get_calendar_events_by_date_range(
    #         account=account,
    #         start_date=start_date,
    #         end_date=end_date,
    #         limit=limit
    #     )
    # 
    # @mcp.tool()
    # @log_tool_call
    # def search_calendar_events(
    #     query: str,
    #     account: Optional[str] = None,
    #     max_results: int = 100
    # ) -> Dict[str, Any]:
    #     """
    #     Search for calendar events across all calendars.
    #     
    #     Args:
    #         query: Search query string to match against event details
    #         account: Email address of account to search in (uses USER_EMAIL env var if not provided)
    #         max_results: Maximum number of results to return
    #         
    #     Returns:
    #         Dictionary with matching events and metadata
    #     """
    #     # Resolve account - use environment variable if not provided
    #     if not account:
    #         account = os.environ.get("USER_EMAIL")
    #         
    #     return search_calendar_events_sqlite(
    #         query=query,
    #         account=account,
    #         max_results=max_results
    #     )
        
    logger.info("SQLite-based tools registered successfully")

def cleanup():
    """Clean up resources when the server exits."""
    logger.info("Cleaning up SQLite resources...")
    try:
        outlook_db.disconnect()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

# Register cleanup function to be called on exit
import atexit
atexit.register(cleanup)
