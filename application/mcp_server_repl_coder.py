import logging
import sys
import mcp_repl_coder as coder

from typing import Dict, Optional, Any
from mcp.server.fastmcp import FastMCP 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("coder")

try:
    mcp = FastMCP(
        name = "coder",
        instructions=(
            "You are a helpful assistant. "
            "You can generate a code or draw a graph using python code"
        )
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# Code Interpreter
######################################

@mcp.tool()
def repl_coder(code):
    """
    Use this to execute python code and do math. 
    If you want to see the output of a value, you should print it out with `print(...)`. This is visible to the user.
    code: the Python code was written in English
    """
    logger.info(f"repl_coder --> code:\n {code}")

    return coder.repl_coder(code)

@mcp.tool()
def repl_drawer(code):
    """
    Execute a Python script for draw a graph.
    Since Python runtime cannot use external APIs, necessary data must be included in the code.
    The graph should use English exclusively for all textual elements.
    Do not save pictures locally bacause the runtime does not have filesystem.
    When a comparison is made, all arrays must be of the same length.
    code: the Python code was written in English
    return: the url of graph
    """ 
    logger.info(f"repl_drawer --> code:\n {code}")
    
    return coder.repl_drawer(code)
    
if __name__ =="__main__":
    mcp.run(transport="stdio")


