"""
Google Workspace MCP Server (gog CLI)

Exposes gog CLI for Gmail, Calendar, Drive, Contacts, Sheets, and Docs.
Requires: gog auth setup (gog auth credentials, gog auth add, gog auth list)
See: https://gogcli.sh
"""

import logging
import os
import shlex
import subprocess
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)s:%(lineno)d | %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("mcp-server-gog")

try:
    mcp = FastMCP(
        name="gog",
        instructions=(
            "You are a helpful assistant for Google Workspace (Gmail, Calendar, Drive, Contacts, Sheets, Docs). "
            "You use the gog CLI to perform operations. "
            "For read operations, prefer --json and --no-input for scripting. "
            "Confirm before sending mail or creating/updating calendar events."
        ),
    )
    logger.info("MCP server (gog) initialized successfully")
except Exception as e:
    logger.error(f"MCP server init error: {e}")


def _run_gog(
    command: str,
    account: Optional[str] = None,
    env: Optional[dict] = None,
) -> dict:
    """
    Execute a gog CLI command.

    Args:
        command: gog subcommand and args (e.g. "gmail search 'newer_than:7d' --max 10")
        account: Optional GOG_ACCOUNT (or --account) for multi-account
        env: Optional env overrides

    Returns:
        dict with status, stdout, stderr
    """
    # Normalize: accept "gmail search ..." or "gog gmail search ..."
    cmd_str = command.strip()
    if cmd_str.lower().startswith("gog "):
        cmd_str = cmd_str[4:].strip()

    try:
        args = ["gog"] + shlex.split(cmd_str)
    except ValueError as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "message": "Invalid command syntax (check quoting)",
        }

    run_env = os.environ.copy()
    if account:
        run_env["GOG_ACCOUNT"] = account
    if env:
        run_env.update(env)

    logger.info(f"Running: {' '.join(args)}")
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=run_env,
            timeout=60,
        )
        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "Command timed out (60s)",
            "message": "gog command timed out",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "gog not found. Install: https://gogcli.sh",
            "message": "gog CLI not installed",
        }
    except Exception as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "message": f"gog execution failed: {e}",
        }


@mcp.tool()
def gog_run(
    command: str,
    account: Optional[str] = None,
) -> str:
    """
    Run a gog CLI command for Google Workspace (Gmail, Calendar, Drive, Contacts, Sheets, Docs).

    Examples:
    - Gmail search: gmail search 'newer_than:7d' --max 10
    - Gmail messages: gmail messages search "in:inbox from:example.com" --max 20
    - Gmail send: gmail send --to a@b.com --subject "Hi" --body "Hello"
    - Calendar events: calendar events primary --from 2025-03-01 --to 2025-03-31
    - Calendar create: calendar create primary --summary "Meeting" --from 2025-03-15T10:00 --to 2025-03-15T11:00
    - Drive search: drive search "query" --max 10
    - Contacts: contacts list --max 20
    - Sheets get: sheets get <sheetId> "Tab!A1:D10" --json
    - Docs cat: docs cat <docId>

    For read operations, add --json --no-input for machine-readable output.
    Confirm before sending mail or creating events.

    Args:
        command: gog subcommand and arguments (e.g. "gmail search 'newer_than:7d' --max 10")
        account: Optional account email (sets GOG_ACCOUNT) for multi-account use

    Returns:
        Command output (stdout) or error message
    """
    out = _run_gog(command, account=account)
    if out["status"] == "success":
        text = out["stdout"].strip() or "(no output)"
        if out["stderr"]:
            text += f"\n[stderr: {out['stderr'].strip()}]"
        return text
    err = out.get("stderr", "") or out.get("message", "Unknown error")
    return f"Error: {err}"


@mcp.tool()
def gog_gmail_search(
    query: str,
    max_results: int = 10,
    account: Optional[str] = None,
    json_output: bool = True,
) -> str:
    """
    Search Gmail threads by query. Returns one row per thread.

    Args:
        query: Gmail search query (e.g. "newer_than:7d", "in:inbox from:example.com")
        max_results: Maximum number of results (default 10)
        account: Optional account email for multi-account
        json_output: Use --json --no-input for machine-readable output (default True)

    Returns:
        Search results
    """
    extra = " --json --no-input" if json_output else ""
    return gog_run(
        command=f"gmail search {shlex.quote(query)} --max {max_results}{extra}",
        account=account,
    )


@mcp.tool()
def gog_gmail_messages_search(
    query: str,
    max_results: int = 20,
    account: Optional[str] = None,
    json_output: bool = True,
) -> str:
    """
    Search Gmail messages (per email, ignores threading). Use when you need every individual email.

    Args:
        query: Gmail search query (e.g. "in:inbox from:example.com")
        max_results: Maximum number of results (default 20)
        account: Optional account email for multi-account
        json_output: Use --json --no-input for machine-readable output (default True)

    Returns:
        Search results
    """
    extra = " --json --no-input" if json_output else ""
    return gog_run(
        command=f'gmail messages search {shlex.quote(query)} --max {max_results}{extra}',
        account=account,
    )


@mcp.tool()
def gog_calendar_events(
    calendar_id: str,
    from_date: str,
    to_date: str,
    account: Optional[str] = None,
    json_output: bool = True,
) -> str:
    """
    List calendar events for a date range.

    Args:
        calendar_id: Calendar ID (e.g. "primary")
        from_date: Start date in ISO format (e.g. 2025-03-01)
        to_date: End date in ISO format (e.g. 2025-03-31)
        account: Optional account email for multi-account
        json_output: Use --json --no-input for machine-readable output (default True)

    Returns:
        List of events
    """
    extra = " --json --no-input" if json_output else ""
    return gog_run(
        command=f"calendar events {calendar_id} --from {from_date} --to {to_date}{extra}",
        account=account,
    )


@mcp.tool()
def gog_calendar_colors(account: Optional[str] = None) -> str:
    """
    Show available calendar event colors (IDs 1-11).

    Args:
        account: Optional account email for multi-account

    Returns:
        Color list
    """
    return gog_run(command="calendar colors --json --no-input", account=account)


@mcp.tool()
def gog_drive_search(
    query: str,
    max_results: int = 10,
    account: Optional[str] = None,
    json_output: bool = True,
) -> str:
    """
    Search Google Drive files.

    Args:
        query: Search query
        max_results: Maximum number of results (default 10)
        account: Optional account email for multi-account
        json_output: Use --json --no-input for machine-readable output (default True)

    Returns:
        Search results
    """
    extra = " --json --no-input" if json_output else ""
    return gog_run(
        command=f'drive search {shlex.quote(query)} --max {max_results}{extra}',
        account=account,
    )


@mcp.tool()
def gog_contacts_list(
    max_results: int = 20,
    account: Optional[str] = None,
    json_output: bool = True,
) -> str:
    """
    List Google Contacts.

    Args:
        max_results: Maximum number of contacts (default 20)
        account: Optional account email for multi-account
        json_output: Use --json --no-input for machine-readable output (default True)

    Returns:
        Contact list
    """
    extra = " --json --no-input" if json_output else ""
    return gog_run(
        command=f"contacts list --max {max_results}{extra}",
        account=account,
    )


@mcp.tool()
def gog_sheets_get(
    sheet_id: str,
    range_spec: str,
    account: Optional[str] = None,
) -> str:
    """
    Get values from a Google Sheet range.

    Args:
        sheet_id: Google Sheet ID (from URL)
        range_spec: A1 notation (e.g. "Sheet1!A1:D10")
        account: Optional account email for multi-account

    Returns:
        Cell values (JSON)
    """
    return gog_run(
        command=f'sheets get {sheet_id} {shlex.quote(range_spec)} --json --no-input',
        account=account,
    )


@mcp.tool()
def gog_docs_cat(doc_id: str, account: Optional[str] = None) -> str:
    """
    Read Google Docs content as plain text.

    Args:
        doc_id: Google Docs ID (from URL)
        account: Optional account email for multi-account

    Returns:
        Document content
    """
    return gog_run(
        command=f"docs cat {doc_id}",
        account=account,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
