import logging
import sys
import mcp_repl_coder as coder
from pydantic import Field

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
def repl_coder(code: str = ""):
    """
    Execute Python code to perform calculations or data processing. You MUST provide the 'code' parameter.
    
    Args:
        code (str): Required. The complete Python code to execute.
    
    Rules:
    - If you want to see the output of a value, you should print it out with `print(...)`. This is visible to the user.
    - The code should be written in English.
    
    Example usage: repl_coder(code="result = 2 + 2\\nprint(result)")
    """
    if not code or not code.strip():
        return "Error: 'code' parameter is required. Please provide Python code to execute. Example: repl_coder(code='print(1+1)')"
    
    logger.info(f"repl_coder --> code:\n {code}")

    return coder.repl_coder(code)

@mcp.tool()
def repl_drawer(code: str = ""):
    """
    Execute a Python script to draw a graph. You MUST provide the 'code' parameter.
    
    Args:
        code (str): Required. The complete Python code to execute for drawing a graph.
    
    Rules:
    - Since Python runtime cannot use external APIs, necessary data must be included in the code.
    - The graph should use English exclusively for all textual elements.
    - Do not save pictures locally because the runtime does not have filesystem.
    - When a comparison is made, all arrays must be of the same length.
    
    Returns:
        str: The URL of the generated graph image.
    
    Example usage: repl_drawer(code="import matplotlib.pyplot as plt\\nplt.plot([1,2,3])\\nplt.show()")
    """ 
    if not code or not code.strip():
        return "Error: 'code' parameter is required. Please provide Python code to draw a graph. Example: repl_drawer(code='import matplotlib.pyplot as plt\\nplt.plot([1,2,3])\\nplt.show()')"
    
    logger.info(f"repl_drawer --> code:\n {code}")
    
    return coder.repl_drawer(code)
    
if __name__ =="__main__":
    mcp.run(transport="stdio")


