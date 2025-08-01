import logging
import sys
import mcp_long_term_memory

from typing import Dict, Optional, Any
from mcp.server.fastmcp import FastMCP 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("memory")

try:
    mcp = FastMCP(
        name = "memory",
        instructions=(
            "You are a helpful assistant. "
            "You can create, retrieve, list, get, and delete memories."
        ),
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# memory
######################################
@mcp.tool()
def agent_core_memory(
    action: str,
    content: Optional[str] = None,
    query: Optional[str] = None,
    memory_record_id: Optional[str] = None,
    max_results: Optional[int] = None,
    next_token: Optional[str] = None,
) -> Dict:
    """
    Work with agent memories - create, search, retrieve, list, and manage memory records.

    This tool helps agents store and access memories, allowing them to remember important
    information across conversations and interactions.

    Key Capabilities:
    - Store new memories (text conversations or structured data)
    - Search for memories using semantic search
    - Browse and list all stored memories
    - Retrieve specific memories by ID
    - Delete unwanted memories

    Supported Actions:
    -----------------
    Memory Management:
    - record: Store a new memory (conversation or data)
        Use this when you need to save information for later recall.

    - retrieve: Find relevant memories using semantic search
        Use this when searching for specific information in memories.
        This is the best action for queries like "find memories about X" or "search for memories related to Y".

    - list: Browse all stored memories
        Use this to see all available memories without filtering.
        This is useful for getting an overview of what's been stored.

    - get: Fetch a specific memory by ID
        Use this when you already know the exact memory ID.

    - delete: Remove a specific memory
        Use this to delete memories that are no longer needed.

    Args:
        action: The memory operation to perform (one of: "record", "retrieve", "list", "get", "delete")
        content: For record action: Simple text string to store as a memory
                    Example: "User prefers vegetarian pizza with extra cheese"
        query: Search terms for finding relevant memories (required for retrieve action)
        memory_record_id: ID of a specific memory (required for get and delete actions)
        max_results: Maximum number of results to return (optional)
        next_token: Pagination token (optional)

    Returns:
        Dict: Response containing the requested memory information or operation status
    """
    logger.info(f"###### agent_core_memory ######")
    logger.info(f"action: {action}")

    return mcp_long_term_memory.agent_core_memory(action, content, query, memory_record_id, max_results, next_token)

if __name__ =="__main__":
    print(f"###### main ######")
    mcp.run(transport="stdio")


