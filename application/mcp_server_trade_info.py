import logging
import json
import sys
import trade_info
from typing import Dict, Optional, List
from mcp.server.fastmcp import FastMCP 
import uuid
import datetime

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp_server_trade_info")

try:
    mcp = FastMCP(
        name = "trade_info",
        instructions=(
            "You are a helpful assistant that can provide stock information. "
            "You can use tools to get stock information and provide the answer."
        ),
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# Time
######################################
@mcp.tool()
def get_stock_trend(company_name: str = "네이버", period: int = 30) -> str:
    """
    Returns the last ~period days price trend of the given company name as a JSON string.
    company_name: the company name to get stock price trend
    period: the period to get stock trend
    return: the file name of the saved JSON file
    """
    logger.info(f"get_stock_trend --> company_name: {company_name}, period: {period}")

    result_dict = trade_info.get_stock_trend(company_name, period)

    file_name = f"contents/{company_name}.json"
    with open(file_name, "w") as f:
        json.dump(result_dict, f, ensure_ascii=False)

    logger.info(f"result_dict saved to {file_name}")

    return json.dumps(result_dict, ensure_ascii=False)

@mcp.tool()
def draw_stock_trend(company_name: str) -> Dict[str, List[str]]:
    """
    Draw a graph of the given trend.
    trend: the trend of the given company name as a JSON string (the result from get_stock_trend)
    return: dictionary with 'path' key containing a list of image file paths
    """
    logger.info(f"draw_stock_trend --> company_name: {company_name}")

    file_name = f"contents/{company_name}.json"
    with open(file_name, "r") as f:
        trend_dict = json.load(f)
    logger.info(f"trend_dict: {trend_dict}")

    return trade_info.draw_stock_trend(trend_dict)

if __name__ =="__main__":
    print(f"###### main ######")
    mcp.run(transport="stdio")


