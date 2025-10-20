#!/usr/bin/env python3

# Allow configuring Python interpreter via environment variable
import os
import sys

# Prevent re-execution loops
if "PYTHON_PATH" in os.environ and "PYTHON_PATH_USED" not in os.environ:
    python_path = os.environ["PYTHON_PATH"]
    
    # Make sure the specified path exists and is executable
    if os.path.exists(python_path) and os.access(python_path, os.X_OK):
        # Check if we're already running with the desired interpreter
        current_python = sys.executable
        if current_python != python_path:
            print(f"Switching to Python interpreter: {python_path}", file=sys.stderr)
            # Set flag to prevent further re-executions
            os.environ["PYTHON_PATH_USED"] = "1"
            # Re-execute this script with the specified Python interpreter
            os.execv(python_path, [python_path] + sys.argv)
        else:
            print(f"Already using specified Python interpreter: {python_path}", file=sys.stderr)
    else:
        print(f"Warning: PYTHON_PATH '{python_path}' is invalid or not executable, using {sys.executable}", file=sys.stderr)

# Basic imports
import json
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP

# Import our custom modules
from sqlite_tools import register_tools, cleanup as sqlite_cleanup


# Display help information
def display_help():
    """Display help information for the Outlook MCP server"""
    help_text = """
Outlook MCP Server - A bridge between Microsoft Outlook and other applications

Usage: python outlook_mcp.py [options]

Options:
  --help            Show this help message and exit
  
Environment Variables:
  OUTLOOK_MCP_LOG_LEVEL
                    Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                    Default: INFO

Available Tools:
  Email Operations:
    get_email_content             Get full content of a specific email
    send_email_as_html            Send a new email with HTML content to a destination address
    create_draft_as_html          Create a draft email with HTML content to a destination address
    reply_to_email_as_html        Reply to an email with HTML content
    forward_email_as_html         Forward an email to a destination address with optional HTML content
    mark_as_read                  Mark an email as read
    mark_as_unread                Mark an email as unread
    delete_email                  Delete an email
    save_attachments              Save attachments from a specific email to a local directory
    assign_category               Assign a category to an email or multiple emails
    clear_category                Clear a specific category or all categories from an email
    
  Email Search & Analytics:
    unified_email_search          Unified search for emails with advanced filtering
    email_volume_analytics        Get email volume statistics grouped by time period
    sender_analytics              Get comprehensive statistics about email senders
    folder_analytics              Get statistics about email folders
    mailbox_overview              Get a comprehensive overview of the mailbox
    outlook_database_query        Execute a custom read-only SQL query against the Outlook database
    
  Calendar Operations:
    get_calendars                 Get a list of available calendars
    get_calendar_events           Get events from a calendar with optional date filtering
    get_event_details             Get detailed information about a specific event
    search_calendar_events        Search for events across all calendars
    create_calendar_event         Create a new calendar event with full parameter support
    update_calendar_event         Update an existing calendar event with selective field updates
    delete_calendar_event         Delete a calendar event safely


For more information, see the README.md file.
"""
    print(help_text)

# Check for command-line arguments first
if __name__ == "__main__" and len(sys.argv) > 1:
    if sys.argv[1] == "--help":
        display_help()
        sys.exit(0)
    else:
        print(f"Unknown option: {sys.argv[1]}")
        print("Use --help for usage information")
        sys.exit(1)

# Set up logging
def setup_logging():
    """Configure logging to write to a .log file with the same name as the script"""
    # Use an absolute path for the log file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(script_dir, "outlook_mcp.log")
    
    # Get log level from environment variable, default to INFO
    log_level_name = os.environ.get('OUTLOOK_MCP_LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    
    # Configure logging to overwrite the file each time
    logging.basicConfig(
        filename=log_file,
        filemode='w',  # 'w' mode overwrites the file each time
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=log_level
    )
    
    # Add console handler to see logs in terminal too
    console = logging.StreamHandler()
    console.setLevel(log_level)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    
    logging.info(f"Logging initialized. Writing to {log_file} with level {log_level_name}")
    return logging.getLogger()

# Initialize logger
logger = setup_logging()
logger.info(f"Starting Outlook MCP Server at {datetime.now().isoformat()}")

# Create a decorator for logging tool calls
def log_tool_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        tool_name = func.__name__
        logger.info(f"Tool called: {tool_name}")
        logger.info(f"Arguments: args={args}, kwargs={kwargs}")
        try:
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

# Create a decorator for logging resource calls
def log_resource_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        resource_name = func.__name__
        logger.info(f"Resource accessed: {resource_name}")
        logger.info(f"Arguments: args={args}, kwargs={kwargs}")
        try:
            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed_time = time.time() - start_time
            logger.info(f"Resource {resource_name} accessed in {elapsed_time:.2f}s")
            logger.info(f"Result: {result}")
            return result
        except Exception:
            logger.exception(f"Error in resource {resource_name}")
            raise
    return wrapper

# Check for email address in environment variable
try:
    DEFAULT_USER_EMAIL = os.environ["USER_EMAIL"]
    logger.info(f"Using default source email address from environment: {DEFAULT_USER_EMAIL}")
    logger.warning("Consider using per-tool email parameters for more flexibility.")
except KeyError:
    DEFAULT_USER_EMAIL = ""
    logger.info("USER_EMAIL environment variable is not set. Will use default Outlook account if no email is specified.")

# Helper function to resolve which email address to use
def resolve_email_address(email=None, account_type=None):
    """Resolve which email address and account type to use
    
    Args:
        email: Optional source email address that takes priority if provided (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
        
    Returns:
        Tuple of (email_address, account_type)
    """
    # If email is explicitly provided, use it
    if email:
        # If account type is specified, use it; otherwise default to Exchange
        user_account_type = account_type or "Exchange"
        return email, user_account_type
    
    # Fall back to environment variable if no email is explicitly provided
    if DEFAULT_USER_EMAIL:
        logger.info("Using email from USER_EMAIL environment variable")
        user_account_type = account_type or "Exchange"
        return DEFAULT_USER_EMAIL, user_account_type
    
    # If no email is provided and no environment variable is set, try to get default account
    try:
        # Create a temporary AppleScript to get the default account
        temp_script = """
        tell application "Microsoft Outlook"
            set allAccounts to every exchange account
            if (count of allAccounts) > 0 then
                set defaultAccount to item 1 of allAccounts
                return email address of defaultAccount
            else
                return ""
            end if
        end tell
        """
        # Run the temporary script to get the default email address
        default_email_result = subprocess.run(["osascript", "-e", temp_script], 
                                            text=True, capture_output=True, check=True)
        default_email = default_email_result.stdout.strip()
        
        if default_email:
            logger.info(f"Using default account: {default_email}")
            return default_email, "Exchange"
        else:
            logger.warning("No default account found, using empty string")
            return "", "Exchange"
    except Exception as e:
        logger.error(f"Error getting default account: {str(e)}")
        return "", "Exchange"

# Helper function to run AppleScript files
def run_applescript(script_path, *args):
    """Run an AppleScript file with arguments and return the result
    
    Args:
        script_path: Path to the AppleScript file
        *args: Arguments to pass to the script
    """
    try:
        cmd = ["osascript", script_path]
        
        # Add all arguments
        for arg in args:
            cmd.append(arg)
        
        # Log the command at debug level (to avoid exposing sensitive data at info level)
        logger.debug(f"Running AppleScript: {script_path}")
        logger.debug(f"AppleScript arguments: {args}")
        
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
        
        # Log the result at appropriate levels
        if result.stdout.strip():
            logger.debug(f"AppleScript stdout: {result.stdout.strip()}")
            logger.info(f"AppleScript completed successfully: {script_path}")
        
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"AppleScript error: {e.stderr.strip()}")
        raise RuntimeError(f"AppleScript error: {e.stderr.strip()}")
    except Exception:
        logger.exception(f"Error running AppleScript: {script_path}")
        raise

# Helper function to run JavaScript for Automation (JXA) files
def run_applescript_js(script_path, *args):
    """Run a JavaScript for Automation file with arguments and return the result
    
    Args:
        script_path: Path to the JXA file
        *args: Arguments to pass to the script
    """
    try:
        cmd = ["osascript", "-l", "JavaScript", script_path]
        
        # Add all arguments
        for arg in args:
            cmd.append(arg)
        
        # Log the command at debug level (to avoid exposing sensitive data at info level)
        logger.debug(f"Running JXA: {script_path}")
        logger.debug(f"JXA arguments: {args}")
        
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
        
        # Log the result at appropriate levels
        if result.stdout.strip():
            logger.debug(f"JXA stdout: {result.stdout.strip()}")
            logger.info(f"JXA completed successfully: {script_path}")
        
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"JXA error: {e.stderr.strip()}")
        raise RuntimeError(f"JXA error: {e.stderr.strip()}")
    except Exception:
        logger.exception(f"Error running JXA: {script_path}")
        raise

# Create custom MCP class to log all commands
class LoggingMCP(FastMCP):
    def handle_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Received command: {command}")
        try:
            result = super().handle_command(command)
            logger.info(f"Command result: {result}")
            return result
        except Exception:
            logger.exception(f"Error handling command: {command}")
            raise

# Instantiate the logging MCP server client
mcp = LoggingMCP("Outlook MCP Server")
logger.info("MCP Server initialized")

@mcp.tool()
@log_tool_call
def send_email_as_html(to: str, subject: str, body: str, email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Send an email with HTML content using Outlook
    
    Args:
        to: Destination recipient email address to send the email to
        subject: Email subject
        body: HTML-formatted content for the email body
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not to or '@' not in to:
        logger.error(f"Invalid email address: {to}")
        return {"status": "error", "message": "Invalid email address. Must contain '@'."}
    
    if not subject:
        logger.error("Empty subject")
        return {"status": "error", "message": "Subject cannot be empty."}
    
    if not body:
        logger.error("Empty body")
        return {"status": "error", "message": "Email body cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "send_email.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        logger.debug(f"Sending email to: {to}, subject: {subject}, body length: {len(body)}")
        # Pass email and account type as regular arguments, followed by the other parameters
        result = run_applescript(script_path, user_email, user_account_type, subject, body, to)
        logger.info(f"Email sent successfully to {to}")
        return {"status": "success", "message": result}
    except ValueError as e:
        logger.error(str(e))
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception(f"Error sending HTML email to {to}")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def create_draft_as_html(to: str, subject: str, body: str, email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Create a draft email with HTML content in Outlook
    
    Args:
        to: Destination recipient email address for the draft
        subject: Email subject
        body: HTML-formatted content for the email body
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not to or '@' not in to:
        logger.error(f"Invalid email address: {to}")
        return {"status": "error", "message": "Invalid email address. Must contain '@'."}
    
    if not subject:
        logger.error("Empty subject")
        return {"status": "error", "message": "Subject cannot be empty."}
    
    if not body:
        logger.error("Empty body")
        return {"status": "error", "message": "Email body cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "create_draft.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        # Note: The order of arguments must match the order expected by the AppleScript
        # AppleScript expects: email, account_type, subject, body, recipient
        logger.debug(f"Creating draft email to: {to}, subject: {subject}, body length: {len(body)}")
        result = run_applescript(script_path, user_email, user_account_type, subject, body, to)
        logger.info(f"Draft email created successfully for {to}")
        return {"status": "success", "message": result}
    except ValueError as e:
        logger.error(str(e))
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception(f"Error creating HTML draft email to {to}")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def reply_to_email_as_html(message_id: str, reply_text: str, email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Reply to an email with HTML content in Outlook
    
    Args:
        message_id: ID of the message to reply to
        reply_text: HTML-formatted content for the reply
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"status": "error", "message": "Message ID cannot be empty."}
    
    if not reply_text:
        logger.error("Empty reply text")
        return {"status": "error", "message": "Reply text cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "reply_to_email.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        logger.debug(f"Replying to email ID: {message_id}, reply text length: {len(reply_text)}")
        result = run_applescript(script_path, user_email, user_account_type, message_id, reply_text)
        logger.info(f"Reply sent successfully to email {message_id}")
        return {"status": "success", "message": result}
    except ValueError as e:
        logger.error(str(e))
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception(f"Error replying with HTML to email {message_id}")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def get_email_content(message_id: str, email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Get the full content of a specific email
    
    Args:
        message_id: ID of the message to retrieve
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with email details including subject, sender, date, and content
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"error": "Message ID cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "get_email_content.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        logger.debug(f"Getting content for email: {message_id}")
        result = run_applescript(script_path, user_email, user_account_type, message_id)
        parts = result.split('||')
        
        if len(parts) >= 4:
            email_content = {
                "subject": parts[0],
                "sender": parts[1],
                "date": parts[2],
                "content": parts[3]
            }
            logger.debug(f"Retrieved email content: subject='{parts[0]}', sender='{parts[1]}', date='{parts[2]}', content length={len(parts[3])}")
            return email_content
        else:
            logger.error(f"Invalid response format from AppleScript: {result}")
            return {"error": "Invalid response format from AppleScript"}
    except ValueError as e:
        logger.error(str(e))
        return {"error": str(e)}
    except Exception as e:
        logger.exception(f"Error getting email content for {message_id}")
        return {"error": str(e)}

# DEFINE RESOURCES

@mcp.tool()
@log_tool_call
def delete_email(message_id: Union[str, List[str]], email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Delete an email or multiple emails from Outlook
    
    Args:
        message_id: ID of the message to delete or a list of message IDs to delete multiple emails
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"status": "error", "message": "Message ID cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "delete_email.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        # Handle single message ID or list of message IDs
        if isinstance(message_id, list):
            # Join multiple message IDs with a comma delimiter
            message_ids_str = ",".join([str(mid) for mid in message_id])
            logger.debug(f"Deleting multiple emails: {len(message_id)} emails")
            result = run_applescript(script_path, user_email, user_account_type, message_ids_str)
            logger.info(f"Successfully processed deletion of {len(message_id)} emails")
            return {"status": "success", "message": result, "count": len(message_id)}
        else:
            # Single message ID
            logger.debug(f"Deleting email: {message_id}")
            result = run_applescript(script_path, user_email, user_account_type, str(message_id))
            logger.info(f"Email {message_id} deleted successfully")
            return {"status": "success", "message": result, "count": 1}
    except Exception as e:
        if isinstance(message_id, list):
            logger.exception(f"Error deleting multiple emails")
        else:
            logger.exception(f"Error deleting email {message_id}")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def mark_as_read(message_id: Union[str, List[str]], email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Mark an email as read in Outlook
    
    Args:
        message_id: ID of the message to mark as read
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"status": "error", "message": "Message ID cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "mark_as_read.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        # Handle single message ID or list of message IDs
        if isinstance(message_id, list):
            # Join multiple message IDs with a comma delimiter
            message_ids_str = ",".join([str(mid) for mid in message_id])
            logger.debug(f"Marking multiple emails as read: {len(message_id)} emails")
            result = run_applescript(script_path, user_email, user_account_type, message_ids_str)
            logger.info(f"Successfully marked {len(message_id)} emails as read")
            return {"status": "success", "message": result, "count": len(message_id)}
        else:
            # Single message ID
            logger.debug(f"Marking email as read: {message_id}")
            result = run_applescript(script_path, user_email, user_account_type, str(message_id))
            logger.info(f"Email {message_id} marked as read successfully")
            return {"status": "success", "message": result, "count": 1}
    except Exception as e:
        if isinstance(message_id, list):
            logger.exception(f"Error marking multiple emails as read")
        else:
            logger.exception(f"Error marking email {message_id} as read")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def mark_as_unread(message_id: Union[str, List[str]], email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Mark an email as unread in Outlook
    
    Args:
        message_id: ID of the message to mark as unread
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"status": "error", "message": "Message ID cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "mark_as_unread.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        # Handle single message ID or list of message IDs
        if isinstance(message_id, list):
            # Join multiple message IDs with a comma delimiter
            message_ids_str = ",".join([str(mid) for mid in message_id])
            logger.debug(f"Marking multiple emails as unread: {len(message_id)} emails")
            result = run_applescript(script_path, user_email, user_account_type, message_ids_str)
            logger.info(f"Successfully marked {len(message_id)} emails as unread")
            return {"status": "success", "message": result, "count": len(message_id)}
        else:
            # Single message ID
            logger.debug(f"Marking email as unread: {message_id}")
            result = run_applescript(script_path, user_email, user_account_type, str(message_id))
            logger.info(f"Email {message_id} marked as unread successfully")
            return {"status": "success", "message": result, "count": 1}
    except Exception as e:
        if isinstance(message_id, list):
            logger.exception(f"Error marking multiple emails as unread")
        else:
            logger.exception(f"Error marking email {message_id} as unread")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def forward_email_as_html(message_id: str, to: str, additional_text: str = "", email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Forward an email to another recipient with HTML content in the additional text
    
    Args:
        message_id: ID of the message to forward
        to: Destination recipient email address to forward the email to
        additional_text: Optional HTML content to add to the beginning of the forwarded message
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"status": "error", "message": "Message ID cannot be empty."}
    
    if not to or '@' not in to:
        logger.error(f"Invalid email address: {to}")
        return {"status": "error", "message": "Invalid email address. Must contain '@'."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "forward_email.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        logger.debug(f"Forwarding email ID: {message_id} to: {to}, additional text length: {len(additional_text)}")
        result = run_applescript(script_path, user_email, user_account_type, message_id, to, additional_text)
        logger.info(f"Email {message_id} forwarded successfully to {to}")
        return {"status": "success", "message": result}
    except Exception as e:
        logger.exception(f"Error forwarding email with HTML {message_id}")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def save_attachments(message_id: str, save_path: str, email: Optional[str] = None, account_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Save attachments from a specific email to a local directory
    
    Args:
        message_id: ID of the message containing attachments
        save_path: Local directory path where attachments should be saved
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        List of dictionaries containing information about saved attachments:
        - name: Filename of the attachment
        - size: Size of the file in bytes
        - type: MIME type of the attachment
        - path: Full path where the file was saved
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return []
    
    if not save_path:
        logger.error("Empty save path")
        return []
    
    # Ensure save directory exists
    if not os.path.exists(save_path):
        try:
            os.makedirs(save_path)
            logger.info(f"Created save directory: {save_path}")
        except Exception as e:
            logger.error(f"Could not create save directory: {str(e)}")
            return []
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "save_attachments.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        logger.debug(f"Saving attachments from message {message_id} to {save_path}")
        result = run_applescript(script_path, user_email, user_account_type, message_id, save_path)
        
        # Process the results
        saved_files = []
        for line in result.strip().split('\n'):
            if line.startswith("Error"):
                logger.error(line)
                continue
                
            parts = line.split('|')
            if len(parts) == 4:
                saved_files.append({
                    "name": parts[0],
                    "size": int(parts[1]),
                    "type": parts[2],
                    "path": parts[3]
                })
            else:
                logger.warning(f"Unexpected format in line: {line}")
        
        logger.info(f"Saved {len(saved_files)} attachments from message {message_id}")
        return saved_files
    except Exception as e:
        logger.exception(f"Error saving attachments from message {message_id}")
        return []

@mcp.tool()
@log_tool_call
def clear_category(message_id: Union[str, List[str]], category_name: str = "", email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Clear a specific category or all categories from an email or multiple emails in Outlook
    
    Args:
        message_id: ID of the message to clear categories from or a list of message IDs
        category_name: Name of the category to remove (if empty, all categories will be cleared)
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"status": "error", "message": "Message ID cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "clear_category.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        # Handle single message ID or list of message IDs
        if isinstance(message_id, list):
            # Join multiple message IDs with a comma delimiter
            message_ids_str = ",".join([str(mid) for mid in message_id])
            if category_name:
                logger.debug(f"Removing category '{category_name}' from multiple emails: {len(message_id)} emails")
            else:
                logger.debug(f"Clearing all categories from multiple emails: {len(message_id)} emails")
                
            result = run_applescript(script_path, user_email, user_account_type, message_ids_str, category_name)
            logger.info(f"Successfully processed category removal for {len(message_id)} emails")
            return {"status": "success", "message": result, "count": len(message_id)}
        else:
            # Single message ID
            if category_name:
                logger.debug(f"Removing category '{category_name}' from email: {message_id}")
            else:
                logger.debug(f"Clearing all categories from email: {message_id}")
                
            result = run_applescript(script_path, user_email, user_account_type, str(message_id), category_name)
            logger.info(f"Email {message_id} categories processed successfully")
            return {"status": "success", "message": result, "count": 1}
    except Exception as e:
        if isinstance(message_id, list):
            logger.exception(f"Error clearing categories from multiple emails")
        else:
            logger.exception(f"Error clearing categories from email {message_id}")
        return {"status": "error", "message": str(e)}





@mcp.resource("status://server")
@log_resource_call
def get_server_status() -> Dict[str, Any]:
    """Get the current server status"""
    status = {
        "status": "online",
        "timestamp": time.time(),
        "tools_available": len(mcp._tools),  # Access internal attribute with underscore
        "resources_available": len(mcp._resources),  # Access internal attribute with underscore
        "server_type": "Outlook MCP Server"
    }
    return status

@mcp.tool()
@log_tool_call
def assign_category(message_id: Union[str, List[str]], category_name: str, email: Optional[str] = None, account_type: Optional[str] = None) -> Dict[str, Any]:
    """Assign a category to an email or multiple emails in Outlook
    
    Args:
        message_id: ID of the message to categorize or a list of message IDs to categorize multiple emails
        category_name: Name of the category to assign (will be created if it doesn't exist)
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        Dictionary with status of the operation
    """
    # Parameter validation
    if not message_id:
        logger.error("Empty message ID")
        return {"status": "error", "message": "Message ID cannot be empty."}
    
    if not category_name:
        logger.error("Empty category name")
        return {"status": "error", "message": "Category name cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "assign_category.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        # Handle single message ID or list of message IDs
        if isinstance(message_id, list):
            # Join multiple message IDs with a comma delimiter
            message_ids_str = ",".join([str(mid) for mid in message_id])
            logger.debug(f"Assigning category '{category_name}' to multiple emails: {len(message_id)} emails")
            result = run_applescript(script_path, user_email, user_account_type, message_ids_str, category_name)
            logger.info(f"Successfully processed category assignment for {len(message_id)} emails")
            return {"status": "success", "message": result, "count": len(message_id)}
        else:
            # Single message ID
            logger.debug(f"Assigning category '{category_name}' to email: {message_id}")
            result = run_applescript(script_path, user_email, user_account_type, str(message_id), category_name)
            logger.info(f"Email {message_id} categorized successfully")
            return {"status": "success", "message": result, "count": 1}
    except Exception as e:
        if isinstance(message_id, list):
            logger.exception(f"Error categorizing multiple emails")
        else:
            logger.exception(f"Error categorizing email {message_id}")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def get_calendars(email: Optional[str] = None, account_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get a list of available calendars in Outlook
    
    Args:
        email: Optional source email address to use (your local Outlook account)
        account_type: Optional account type ('Exchange', 'POP3', 'IMAP')
    
    Returns:
        List of calendar information including name and ID
    """
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "get_calendars.scpt")
    
    try:
        # Resolve which email address and account type to use
        user_email, user_account_type = resolve_email_address(email, account_type)
        
        # Run the AppleScript to get calendar information
        result = run_applescript_js(script_path, user_email, user_account_type)
        
        logger.info(f"Raw AppleScript result length: {len(result)}")
        
        # Check if the result is an error message
        if result.startswith("Error"):
            logger.error(f"Access error: {result}")
            return []  # Return empty list instead of error dict
        
        # Parse the JSON response
        try:
            calendars = json.loads(result)
            if isinstance(calendars, dict) and "error" in calendars:
                logger.error(f"Calendar error: {calendars}")
                return []  # Return empty list instead of error dict
            return calendars
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Raw response: {result}")
            return []  # Return empty list instead of error dict
            
    except Exception as e:
        logger.exception(f"Error getting calendars: {str(e)}")
        return []  # Return empty list instead of error dict

@mcp.tool()
@log_tool_call
def get_calendar_events(calendar_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get events from a specific calendar with optional date range
    
    Args:
        calendar_id: ID of the calendar to get events from
        start_date: Optional start date in format 'YYYY-MM-DD'
        end_date: Optional end date in format 'YYYY-MM-DD' (must be greater than start_date)
        
    Returns:
        List of calendar events from the specified calendar
    """
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "get_calendar_events.scpt")
    
    try:
        # Validate date parameters if both are provided
        if start_date and end_date:
            try:
                from datetime import datetime
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                if end <= start:
                    logger.error(f"Invalid date range: end date {end_date} must be greater than start date {start_date}")
                    return []  # Return empty list instead of error dict
            except ValueError as e:
                logger.error(f"Invalid date format: {str(e)}")
                return []  # Return empty list instead of error dict
        
        # Prepare arguments
        args = [str(calendar_id)]
        if start_date:
            args.append(start_date)
        if end_date:
            args.append(end_date)
        
        # Log the arguments for debugging
        logger.debug(f"Calendar ID: {calendar_id}")
        logger.debug(f"Arguments: {args}")
        
        result = run_applescript_js(script_path, *args)
        
        logger.info(f"Raw AppleScript result length: {len(result)}")
        
        # Check if the result is an error message
        if result.startswith("Error"):
            logger.error(f"Access error: {result}")
            return []  # Return empty list instead of error dict
        
        # Parse the JSON response
        try:
            parsed_result = json.loads(result)
            
            # Check if the result is an error
            if isinstance(parsed_result, dict) and "error" in parsed_result:
                logger.error(f"Calendar error: {parsed_result}")
                return []  # Return empty list instead of error dict
            
            return parsed_result
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Raw response: {result}")
            return []  # Return empty list instead of error dict
            
    except Exception as e:
        logger.exception(f"Error getting calendar events: {str(e)}")
        return []  # Return empty list instead of error dict

@mcp.tool()
@log_tool_call
def get_event_details(event_id: int) -> Dict[str, Any]:
    """Get detailed information about a specific calendar event
    
    Args:
        event_id: ID of the event to get details for
        
    Returns:
        Dictionary with detailed event information including:
        - Basic event details (subject, time, location)
        - My response status (accepted, tentative, none)
        - Free/busy status (free, busy, tentative, out of office)
        - Organizer and attendees with their response status
    """
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "get_event_details.scpt")
    
    try:
        result = run_applescript_js(script_path, str(event_id))
        
        logger.info(f"Raw AppleScript result length: {len(result)}")
        
        # Check if the result is an error message
        if result.startswith("Error"):
            logger.error(f"Access error: {result}")
            return {}  # Return empty dict instead of error dict
        
        # Parse the JSON response
        try:
            event_details = json.loads(result)
            if isinstance(event_details, dict) and "error" in event_details:
                logger.error(f"Event details error: {event_details}")
                return {}  # Return empty dict instead of error dict
            return event_details
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Raw response: {result}")
            return {}  # Return empty dict instead of error dict
            
    except Exception as e:
        logger.exception(f"Error getting event details: {str(e)}")
        return {}  # Return empty dict instead of error dict

@mcp.tool()
@log_tool_call
def search_calendar_events(query: str, max_results: int = 100) -> List[Dict[str, Any]]:
    """Search for calendar events across all calendars
    
    Args:
        query: Search query string to match against event subject, location, or content.
              Special formats supported:
              - "today" - Find events scheduled for today
              - "YYYY-MM-DD" (e.g., "2025-04-24") - Find events on specific date
              - "Month Day" or "Month Day, Year" (e.g., "April 24" or "April 24, 2025")
        max_results: Maximum number of results to return (default: 100)
        
    Returns:
        List of calendar events matching the search query
    """
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "search_calendar_events.scpt")
    
    try:
        result = run_applescript_js(script_path, query, str(max_results))
        
        logger.info(f"Raw AppleScript result length: {len(result)}")
        
        # Check if the result is an error message
        if result.startswith("Error"):
            logger.error(f"Access error: {result}")
            return []  # Return empty list instead of error dict
        
        # Parse the JSON response
        try:
            events = json.loads(result)
            if isinstance(events, dict) and "error" in events:
                logger.error(f"Calendar search error: {events}")
                return []  # Return empty list instead of error dict
            return events
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Raw response: {result}")
            return []  # Return empty list instead of error dict
            
    except Exception as e:
        logger.exception(f"Error searching calendar events: {str(e)}")
        return []  # Return empty list instead of error dict

@mcp.tool()
@log_tool_call
def create_calendar_event(
    subject: str,
    start_time: str,
    end_time: str,
    location: Optional[str] = None,
    description: Optional[str] = None,
    calendar_id: Optional[int] = None,
    attendees: Optional[List[str]] = None,
    is_all_day: Optional[bool] = False
) -> Dict[str, Any]:
    """Create a new calendar event in Outlook
    
    Args:
        subject: Event subject/title
        start_time: Start time in ISO format (e.g., "2025-07-02T14:00:00")
        end_time: End time in ISO format (e.g., "2025-07-02T15:00:00")
        location: Optional location for the event
        description: Optional description/body for the event
        calendar_id: Optional calendar ID (uses default calendar if not specified)
        attendees: Optional list of attendee email addresses
        is_all_day: Whether this is an all-day event (default: False)
        
    Returns:
        Dictionary with status and event details or error message
    """
    # Parameter validation
    if not subject:
        logger.error("Empty subject")
        return {"status": "error", "message": "Subject cannot be empty."}
    
    if not start_time:
        logger.error("Empty start time")
        return {"status": "error", "message": "Start time cannot be empty."}
    
    if not end_time:
        logger.error("Empty end time")
        return {"status": "error", "message": "End time cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "create_calendar_event.scpt")
    
    try:
        # Prepare arguments
        args = [
            subject,
            start_time,
            end_time,
            location or "",
            description or "",
            str(calendar_id) if calendar_id is not None else "",
            ",".join(attendees) if attendees else "",
            "true" if is_all_day else "false"
        ]
        
        logger.debug(f"Creating calendar event: subject='{subject}', start='{start_time}', end='{end_time}'")
        result = run_applescript_js(script_path, *args)
        
        # Parse the JSON response
        try:
            response = json.loads(result)
            
            if response.get("status") == "error":
                logger.error(f"Error creating calendar event: {response.get('error')}")
                return {"status": "error", "message": response.get("error")}
            
            logger.info(f"Calendar event created successfully: {response.get('event_id')}")
            return response
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Raw response: {result}")
            return {"status": "error", "message": f"Invalid response format: {str(e)}"}
            
    except Exception as e:
        logger.exception(f"Error creating calendar event")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def update_calendar_event(
    event_id: int,
    subject: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    is_all_day: Optional[bool] = None
) -> Dict[str, Any]:
    """Update an existing calendar event in Outlook
    
    Args:
        event_id: ID of the event to update
        subject: Optional new subject/title
        start_time: Optional new start time in ISO format (e.g., "2025-07-02T14:00:00")
        end_time: Optional new end time in ISO format (e.g., "2025-07-02T15:00:00")
        location: Optional new location
        description: Optional new description/body
        is_all_day: Optional new all-day flag
        
    Returns:
        Dictionary with status and updated event details or error message
    """
    if not event_id:
        logger.error("Empty event ID")
        return {"status": "error", "message": "Event ID cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "update_calendar_event.scpt")
    
    try:
        # Prepare arguments
        args = [
            str(event_id),
            subject or "",
            start_time or "",
            end_time or "",
            location or "",
            description or "",
            "true" if is_all_day is True else ("false" if is_all_day is False else "")
        ]
        
        logger.debug(f"Updating calendar event: event_id={event_id}")
        result = run_applescript_js(script_path, *args)
        
        # Parse the JSON response
        try:
            response = json.loads(result)
            
            if response.get("status") == "error":
                logger.error(f"Error updating calendar event: {response.get('error')}")
                return {"status": "error", "message": response.get("error")}
            
            logger.info(f"Calendar event updated successfully: {event_id}")
            return response
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Raw response: {result}")
            return {"status": "error", "message": f"Invalid response format: {str(e)}"}
            
    except Exception as e:
        logger.exception(f"Error updating calendar event")
        return {"status": "error", "message": str(e)}

@mcp.tool()
@log_tool_call
def delete_calendar_event(event_id: int) -> Dict[str, Any]:
    """Delete a calendar event from Outlook
    
    Args:
        event_id: ID of the event to delete
        
    Returns:
        Dictionary with status and deleted event details or error message
    """
    if not event_id:
        logger.error("Empty event ID")
        return {"status": "error", "message": "Event ID cannot be empty."}
    
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "delete_calendar_event.scpt")
    
    try:
        logger.debug(f"Deleting calendar event: event_id={event_id}")
        result = run_applescript_js(script_path, str(event_id))
        
        # Parse the JSON response
        try:
            response = json.loads(result)
            
            if response.get("status") == "error":
                logger.error(f"Error deleting calendar event: {response.get('error')}")
                return {"status": "error", "message": response.get("error")}
            
            logger.info(f"Calendar event deleted successfully: {event_id}")
            return response
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Raw response: {result}")
            return {"status": "error", "message": f"Invalid response format: {str(e)}"}
            
    except Exception as e:
        logger.exception(f"Error deleting calendar event")
        return {"status": "error", "message": str(e)}

# DEFINE RESOURCES

if __name__ == "__main__":
    # Get user email from environment variable - warn if not defined
    try:
        USER_EMAIL = os.environ["USER_EMAIL"]
        logger.info(f"Using default source email address from environment: {USER_EMAIL}")
    except KeyError:
        USER_EMAIL = ""
        logger.warning("USER_EMAIL environment variable is not set. You'll need to provide a source email address for each tool call or the default Outlook account will be used.")
        print("INFO: USER_EMAIL environment variable is not set. Default Outlook account will be used if no source email is specified.", file=sys.stderr)
    
    # Register SQLite-based tools
    logger.info("Registering SQLite-based tools")
    register_tools(mcp)
    
    # Register cleanup function to be called on exit
    import atexit
    atexit.register(sqlite_cleanup)
    
    logger.info("Starting MCP server with stdio transport")
    try:
        mcp.run(transport="stdio")
        logger.info("MCP server stopped normally")
    except Exception:
        logger.exception("Error running MCP server")
        raise
