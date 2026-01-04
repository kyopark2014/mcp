import logging
import sys
import mcp_rag as rag

from typing import Dict, Optional, Any
from mcp.server.fastmcp import FastMCP 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("rag")

try:
    mcp = FastMCP(
        name = "rag",
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
def rag_search(keyword: str) -> str:
    """
    Search the knowledge base with the given keyword.
    keyword: the keyword to search
    return: the result of search
    """
    logger.info(f"search --> keyword: {keyword}")

    return rag.retrieve_knowledge_base(keyword)

if __name__ =="__main__":
    mcp.run(transport="stdio")


