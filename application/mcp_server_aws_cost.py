import logging
import sys
import mcp_cost as cost

from mcp.server.fastmcp import FastMCP 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-server-aws-cost")

try:
    mcp = FastMCP(
        name = "AWS_Cost",
        instructions=(
            "You are a helpful assistant. "
            "You can retrieve AWS Cost and provide insights."
        ),
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# AWS Cost
######################################

@mcp.tool()
def get_daily_cost(days: int=30, region: str='us-west-2'):
    """
    Get AWS daily cost data
    Parameters:
        days: the period of the data, e.g., 30
        region: The region of aws infrastructure, e.g., us-west-2
    Returns:
        DataFrame containing daily costs
    """
    return cost.get_daily_cost(days=days, region=region)

@mcp.tool()
def get_region_cost(days: int=30, region: str='us-west-2'):
    """
    Get AWS region cost data
    Parameters:
        days: the period of the data, e.g., 30
        region: The region of aws infrastructure, e.g., us-west-2
    Returns:
        DataFrame containing region costs
    """
    return cost.get_region_cost(days=days, region=region)

@mcp.tool()
def get_service_cost(start_date: str, end_date: str, granularity: str = "MONTHLY", region: str="us-west-2"):
    """
    Get AWS service cost data
    Parameters:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        granularity: Granularity of the cost data (DAILY, MONTHLY, HOURLY)
        region: The region of aws infrastructure, e.g., us-west-2
    Returns:
        JSON containing service costs
    """
    return cost.get_service_cost(start_date=start_date, end_date=end_date, granularity=granularity, region=region)

@mcp.tool()
def create_daily_cost_visualizations() -> list:
    """
    create a graph to show daily aws cost 
    """

    return cost.create_daily_cost_visualizations()

@mcp.tool()
def create_region_cost_visualizations() -> list:
    """
    create a graph to show region aws cost
    """

    return cost.create_region_cost_visualizations()


@mcp.tool()
def generate_cost_insights(question: str) -> str:
    """
    generate cost report only when the user clearly requests
    question: the question to ask
    """

    return cost.ask_cost_insights(question)

######################################
# AWS Logs
######################################

if __name__ =="__main__":
    mcp.run(transport="stdio")


