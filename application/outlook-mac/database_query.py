#!/usr/bin/env python3
"""
Catch-all database query tool for Outlook MCP Server.
Provides direct read-only SQL query capability for advanced scenarios.
"""

import os
import time
import logging
from typing import Dict, List, Any, Optional, Union

from outlook_db import outlook_db

# Configure logging
logger = logging.getLogger(__name__)

def get_example_queries() -> List[Dict[str, str]]:
    """Return example queries that work with the Outlook database schema."""
    return [
        {
            "name": "Recent unread emails",
            "query": """
            SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
                   datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime,
                   f.Folder_Name
            FROM Mail m
            JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
            WHERE m.Message_ReadFlag = 0
            ORDER BY m.Message_TimeReceived DESC
            LIMIT 10
            """
        },
        {
            "name": "Email count by folder",
            "query": """
            SELECT f.Folder_Name, COUNT(*) as EmailCount
            FROM Mail m
            JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
            GROUP BY f.Folder_Name
            ORDER BY EmailCount DESC
            LIMIT 20
            """
        },
        {
            "name": "Emails with attachments",
            "query": """
            SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
                   datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
            FROM Mail m
            WHERE m.Message_HasAttachment = 1
            ORDER BY m.Message_TimeReceived DESC
            LIMIT 10
            """
        },
        {
            "name": "Email volume by month",
            "query": """
            SELECT strftime('%Y-%m', datetime(m.Message_TimeReceived, 'unixepoch')) as Month,
                   COUNT(*) as EmailCount
            FROM Mail m
            GROUP BY Month
            ORDER BY Month DESC
            LIMIT 24
            """
        },
        {
            "name": "Top senders",
            "query": """
            SELECT m.Message_SenderList, COUNT(*) as EmailCount
            FROM Mail m
            GROUP BY m.Message_SenderList
            ORDER BY EmailCount DESC
            LIMIT 20
            """
        },
        {
            "name": "Flagged emails",
            "query": """
            SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
                   datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime,
                   f.Folder_Name
            FROM Mail m
            JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
            WHERE m.Record_FlagStatus > 0
            ORDER BY m.Message_TimeReceived DESC
            LIMIT 20
            """
        }
    ]

def execute_database_query(
    query: str,
    params: Optional[Dict[str, Any]] = None,
    max_results: int = 1000
) -> Dict[str, Any]:
    """
    Execute a custom read-only SQL query against the Outlook database.
    
    Args:
        query: SQL query to execute (must be SELECT only)
        params: Optional parameters for the query
        max_results: Maximum number of results to return
        
    Returns:
        Dictionary with query results and metadata
    """
    try:
        start_time = time.time()
        
        # Validate query is read-only
        if not query.strip().lower().startswith("select"):
            return {
                "error": "Only SELECT queries are allowed",
                "status": "error",
                "db_available": outlook_db.db_available
            }
            
        # Check if database is available
        if not outlook_db.db_available and not outlook_db.conn:
            if not outlook_db.connect():
                end_time = time.time()
                return {
                    "error": f"Database not available: {outlook_db.last_error}",
                    "status": "error",
                    "results": [],
                    "count": 0,
                    "query_time_ms": round((end_time - start_time) * 1000, 2),
                    "db_available": False
                }
            
        # Convert params dict to tuple if provided
        param_tuple = ()
        if params:
            # Extract values in the order they appear in the query
            # This is a simplified approach and may not work for all cases
            param_tuple = tuple(params.values())
            
        # Execute query with safety measures
        results = outlook_db.execute_custom_query(query, param_tuple, max_results)
        
        end_time = time.time()
        
        # Add query time if not already included
        if "query_time_ms" not in results:
            results["query_time_ms"] = round((end_time - start_time) * 1000, 2)
            
        results["status"] = "success" if "error" not in results else "error"
        
        return results
    except Exception as e:
        logger.error(f"Error executing database query: {e}")
        return {
            "error": str(e),
            "status": "error",
            "query_time_ms": round((time.time() - start_time) * 1000, 2),
            "db_available": outlook_db.db_available,
            "results": []
        }

def get_database_schema() -> Dict[str, Any]:
    """
    Get information about the Outlook database schema.
    
    Returns:
        Dictionary with schema information
    """
    try:
        start_time = time.time()
        
        # Check if database is available
        if not outlook_db.db_available and not outlook_db.conn:
            if not outlook_db.connect():
                end_time = time.time()
                return {
                    "error": f"Database not available: {outlook_db.last_error}",
                    "status": "error",
                    "schema": {
                        "tables": {},
                        "example_queries": get_example_queries(),
                        "documentation": "Database connection unavailable. Schema information cannot be retrieved, but example queries are still available."
                    },
                    "query_time_ms": round((end_time - start_time) * 1000, 2),
                    "db_available": False
                }
            
        # Get schema information directly from the database
        schema = {"tables": {}}
        
        # Get list of tables - use execute_query directly to bypass the SELECT check
        try:
            if not outlook_db.conn:
                outlook_db.connect()
                
            cursor = outlook_db.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [dict(row) for row in cursor.fetchall()]
            
            # Get columns for each table
            for table in tables:
                table_name = table["name"]
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [dict(row) for row in cursor.fetchall()]
                schema["tables"][table_name] = {
                    "columns": [{"name": col["name"], "type": col["type"]} for col in columns]
                }
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
            schema["tables"] = {}
            schema["error"] = f"Error getting table schema: {e}"
            
        # Add example queries
        schema["example_queries"] = get_example_queries()
        
        # Add comprehensive schema documentation
        try:
            schema_doc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outlook_schema.md")
            with open(schema_doc_path, 'r') as f:
                schema["documentation"] = f.read()
        except Exception as e:
            logger.error(f"Error reading schema documentation: {e}")
            schema["documentation"] = "Schema documentation not available."
        
        end_time = time.time()
        
        return {
            "schema": schema,
            "query_time_ms": round((end_time - start_time) * 1000, 2),
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Error getting database schema: {e}")
        return {
            "error": str(e),
            "schema": {
                "tables": {},
                "example_queries": get_example_queries(),
                "documentation": "Error retrieving schema documentation. Please try again."
            },
            "status": "error",
            "db_available": outlook_db.db_available,
            "query_time_ms": round((time.time() - start_time) * 1000, 2)
        }

def test_database_query():
    """Test the database query functionality."""
    print("Testing database query...")
    
    # Test 1: Execute a simple query
    print("\nTest 1: Execute a simple query")
    query = """
    SELECT COUNT(*) as EmailCount
    FROM Mail
    """
    results = execute_database_query(query)
    print(f"Query status: {results.get('status')}")
    print(f"Query time: {results.get('query_time_ms', 0)} ms")
    if "results" in results:
        print(f"Total emails: {results['results'][0]['EmailCount']}")
        
    # Test 2: Execute a query with parameters
    print("\nTest 2: Execute a query with parameters")
    query = """
    SELECT COUNT(*) as UnreadCount
    FROM Mail
    WHERE Message_ReadFlag = 0
    """
    results = execute_database_query(query)
    print(f"Query status: {results.get('status')}")
    print(f"Query time: {results.get('query_time_ms', 0)} ms")
    if "results" in results:
        print(f"Unread emails: {results['results'][0]['UnreadCount']}")
        
    # Test 3: Get database schema
    print("\nTest 3: Get database schema")
    schema = get_database_schema()
    print(f"Schema status: {schema.get('status')}")
    print(f"Query time: {schema.get('query_time_ms', 0)} ms")
    if "schema" in schema:
        print(f"Number of tables: {len(schema['schema']['tables'])}")
        print(f"Example queries: {len(schema.get('example_queries', []))}")
        
    # Test 4: Try a non-SELECT query (should be rejected)
    print("\nTest 4: Try a non-SELECT query")
    query = """
    DELETE FROM Mail
    WHERE Message_ReadFlag = 0
    """
    results = execute_database_query(query)
    print(f"Query status: {results.get('status')}")
    print(f"Error message: {results.get('error')}")
    
    # Close database connection
    outlook_db.disconnect()
    
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Run tests
    test_database_query()
