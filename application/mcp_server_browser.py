import logging
import sys
import mcp_browser as browser

from typing import Dict, Optional, Any
from mcp.server.fastmcp import FastMCP 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-server-browser")

try:
    mcp = FastMCP(
        name = "mcp-server-browser",
        instructions=(
            "You are a helpful assistant. "
            "You retrieve documents in RAG."
        ),
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# RAG
######################################
@mcp.tool()
def browser_search(keyword: str) -> str:
    """
    Search web site with the given keyword.
    keyword: the keyword to search
    return: the result of search
    """
    logger.info(f"browser --> keyword: {keyword}")

    return browser.live_view_with_nova_act(keyword)

if __name__ =="__main__":
    print(f"###### main ######")
    mcp.run(transport="stdio")


