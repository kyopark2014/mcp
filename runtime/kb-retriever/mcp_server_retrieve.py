import logging
import sys
import mcp_retrieve

from mcp.server.fastmcp import FastMCP 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("retrieve-server")

try:
    mcp = FastMCP(
        name = "mcp-retrieve",
        instructions=(
            "You are a helpful assistant. "
            "You retrieve documents in RAG."
        ),
        host="0.0.0.0",
        stateless_http=True
    )
    
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# RAG
######################################
@mcp.tool()
def retrieve(keyword: str) -> str:
    """
    Query the keyword using RAG based on the knowledge base.
    keyword: the keyword to query
    return: the result of query
    """
    logger.info(f"search --> keyword: {keyword}")

    try:
        result = mcp_retrieve.retrieve(keyword)
        logger.info(f"result: {result}")
        
        return result
    except Exception as e:
        logger.error(f"Error in retrieve function: {e}")
        return f"Error retrieving data: {str(e)}"

if __name__ =="__main__":
    print(f"###### main ######")
    mcp.run(transport="streamable-http")


