import logging
import sys
import mcp_storage as storage

from typing import Dict, Optional, Any
from mcp.server.fastmcp import FastMCP 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("aws-s3")

try:
    mcp = FastMCP(
        name = "aws_storage",
        instructions=(
            "You are a helpful assistant. "
            "You can check the status of Amazon S3 and retrieve insights."
        )
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# AWS S3
######################################
from typing import List, Optional
from mcp.types import Resource

@mcp.tool()
async def list_buckets(
    start_after: Optional[str] = None,
    max_buckets: Optional[int] = 10,
    region: Optional[str] = "us-west-2"
) -> List[dict]:
    """
    List S3 buckets using async client with pagination
    """
    logger.info(f"list_buckets --> start_after: {start_after}, max_buckets: {max_buckets}, region: {region}")

    return await storage.list_buckets(start_after, max_buckets, region)
    
@mcp.tool()  
async def list_objects(
    bucket_name: str, 
    prefix: Optional[str] = "", 
    max_keys: Optional[int] = 1000,
    region: Optional[str] = "us-west-2"
) -> List[dict]:
    """
    List objects in a specific bucket using async client with pagination
    Args:
        bucket_name: Name of the S3 bucket
        prefix: Object prefix for filtering
        max_keys: Maximum number of keys to return,
        region: Name of the aws region
    """
    logger.info(f"list_objects --> bucket_name: {bucket_name}, prefix: {prefix}, max_keys: {max_keys}, region: {region}")

    return await storage.list_objects(bucket_name, prefix, max_keys, region)

@mcp.tool()    
async def list_resources(
    start_after: Optional[str] = None,
    max_buckets: Optional[int] = 10,
    region: Optional[str] = "us-west-2"
) -> List[Resource]:
    """
    List S3 buckets and their contents as resources with pagination
    Args:
        start_after: Start listing after this bucket name
    """
    logger.info(f"list_resources --> start_after: {start_after}, max_buckets: {max_buckets}, region: {region}")
    
    return await storage.list_resources(start_after, max_buckets, region)

@mcp.tool() 
async def get_total_storage_usage(
    region: Optional[str] = "us-west-2"
) -> dict:
    """
    Calculate total storage usage across all S3 buckets
    
    Returns:
        dict: Dictionary containing total size in bytes, formatted size, and per-bucket breakdown
    """

    return await storage.get_total_storage_usage(region)

@mcp.tool() 
async def get_ebs_volumes_usage(
    region: Optional[str] = "us-west-2",
    filters: Optional[List[Dict]] = None
) -> Dict:
    """
    Get EBS volumes usage information
    
    Args:
        region: AWS region name
        filters: Optional list of filters to apply when retrieving volumes
                Example: [{'Name': 'status', 'Values': ['available']}]
    
    Returns:
        dict: Dictionary containing total EBS storage information and per-volume details
    """
    return await storage.get_ebs_volumes_usage(region, filters)

# @mcp.tool()
# async def get_ebs_snapshots_usage(
#     region: Optional[str] = "us-west-2",
#     owner_ids: Optional[List[str]] = None,
#     filters: Optional[List[Dict]] = None
# ) -> Dict:
#     """
#     Get EBS snapshots usage information
    
#     Args:
#         region: AWS region name
#         owner_ids: Optional list of AWS account IDs that own the snapshots
#         filters: Optional list of filters to apply when retrieving snapshots
#                 Example: [{'Name': 'status', 'Values': ['completed']}]
    
#     Returns:
#         dict: Dictionary containing total EBS snapshots information and per-snapshot details
#     """
#     return await storage.get_ebs_snapshots_usage(region, owner_ids, filters)

@mcp.tool() 
async def get_efs_usage(
    region: Optional[str] = "us-west-2",
    file_system_ids: Optional[List[str]] = None,
    period_hours: int = 24
) -> Dict:
    """
    Get EFS file systems usage information using CloudWatch metrics
    
    Args:
        region: AWS region name
        file_system_ids: Optional list of EFS file system IDs to check
                        If None, all accessible file systems will be checked
        period_hours: Period in hours to check for metrics (default: 24 hours)
    
    Returns:
        dict: Dictionary containing EFS storage information and per-file-system details
    """
    return await storage.get_efs_usage(region, file_system_ids, period_hours)

@mcp.tool()
async def get_aws_account_info(
    region: Optional[str] = "us-west-2"
) -> Dict:
    """
    Get AWS account information.
    
    Args:
        region: AWS region name
    
    Returns:
        dict: AWS account information (account ID, user ARN, user ID, etc.)
    """
    logger.info(f"get_aws_account_info --> region: {region}")
    return await storage.get_aws_account_info(region)

@mcp.tool()
def check_aws_credentials() -> Dict:
    """
    Check AWS credentials status.
    
    Returns:
        dict: Credentials status information and troubleshooting methods
    """
    logger.info("check_aws_credentials called")
    return storage.check_aws_credentials()

######################################
# AWS Logs
######################################

if __name__ =="__main__":
    mcp.run(transport="stdio")


