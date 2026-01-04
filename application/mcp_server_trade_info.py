import logging
import json
import sys
import trade_info
from typing import Dict, Optional, List
from mcp.server.fastmcp import FastMCP 

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

stocks = {}

######################################
# Time
######################################
@mcp.tool()
def retrieve_stock_trend(company_name: str = "네이버", period: int = 30) -> str:
    """
    Returns the last ~period days price trend of the given company name as a JSON string.
    company_name: the company name to get stock price trend
    period: the period to get stock trend
    return: the file name of the saved JSON file
    """
    logger.info(f"get_stock_trend --> company_name: {company_name}, period: {period}")

    result_dict = trade_info.get_stock_trend(company_name, period)

    stocks[f"{company_name}_{period}"] = result_dict

    return json.dumps(result_dict, ensure_ascii=False)

@mcp.tool()
def draw_stock_trend(company_name: str = "네이버", period: int = 30) -> Dict[str, List[str]]:
    """
    Draw a graph of the given trend.
    trend: the trend of the given company name as a JSON string (the result from get_stock_trend)
    return: dictionary with 'path' key containing a list of image file paths
    """
    logger.info(f"draw_stock_trend --> company_name: {company_name}, period: {period}")

    trend_dict = stocks.get(f"{company_name}_{period}")
    if trend_dict is None:
        logger.error(f"Trend not found for {company_name}_{period}")
        trend_dict = trade_info.get_stock_trend(company_name, period)
        stocks[f"{company_name}_{period}"] = trend_dict

    logger.info(f"trend_dict: {trend_dict}")

    return trade_info.draw_stock_trend(trend_dict)

if __name__ =="__main__":
    mcp.run(transport="stdio")


