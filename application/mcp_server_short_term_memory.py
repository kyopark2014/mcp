import logging
import sys
import os
import json
import agentcore_memory
import utils

from typing import Dict, Optional, Any
from mcp.server.fastmcp import FastMCP 
from bedrock_agentcore.memory import MemoryClient

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("short-term memory")

def load_config():
    config = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

bedrock_region = config['region']
accountId = config['accountId']
projectName = config['projectName']

try:
    mcp = FastMCP(
        name = "short-term memory",
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
# short-term memory
######################################
client = MemoryClient(region_name=bedrock_region)

@mcp.tool()
def list_events(
    max_results: Optional[int] = 10
):
    """
    This tool helps agents access memories, allowing them to remember recent information.

    Supported Actions:
    -----------------
    Memory Management:
    - list: List all stored memories
        Use this when you need to retrieve recent information.
    """ 
    logger.info(f"###### list_events ######")

    mcp_env = utils.load_mcp_env()
    user_id = mcp_env['user_id']
    memory_id, actor_id, session_id, namespace = agentcore_memory.load_memory_variables(user_id)
    logger.info(f"memory_id: {memory_id}, user_id: {user_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")    
    
    events = client.list_events(
        memory_id=memory_id,
        actor_id=actor_id,
        session_id=session_id,
        max_results=max_results
    )
    logger.info(f"events: {events}")
    return events

if __name__ =="__main__":
    mcp.run(transport="stdio")


