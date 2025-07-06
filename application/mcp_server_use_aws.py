import json
import logging
import os
import use_aws as aws_utils
import sys

from mcp.server.fastmcp import FastMCP
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ParamValidationError, ValidationError
from botocore.response import StreamingBody
from colorama import Fore, Style, init
from rich.panel import Panel

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
        name = "tools",
        instructions=(
            "You are a helpful assistant. "
            "You can check the status of Amazon S3 and retrieve insights."
        )
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

MUTATIVE_OPERATIONS = [
    "create",
    "put",
    "delete",
    "update",
    "terminate",
    "revoke",
    "disable",
    "deregister",
    "stop",
    "add",
    "modify",
    "remove",
    "attach",
    "detach",
    "start",
    "enable",
    "register",
    "set",
    "associate",
    "disassociate",
    "allocate",
    "release",
    "cancel",
    "reboot",
    "accept",
]

def get_boto3_client(
    service_name: str,
    region_name: str,
    profile_name: Optional[str] = None,
) -> Any:
    """
    Create an AWS boto3 client for the specified service and region.

    Args:
        service_name: Name of the AWS service (e.g., 's3', 'ec2', 'dynamodb')
        region_name: AWS region name (e.g., 'us-west-2', 'us-east-1')
        profile_name: Optional AWS profile name from ~/.aws/credentials

    Returns:
        A boto3 client object for the specified service
    """
    session = boto3.Session(profile_name=profile_name)
    return session.client(service_name=service_name, region_name=region_name)

def handle_streaming_body(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process streaming body responses from AWS into regular Python objects.

    Some AWS APIs return StreamingBody objects that need special handling to
    convert them into regular Python dictionaries or strings for proper JSON serialization.

    Args:
        response: AWS API response that may contain StreamingBody objects

    Returns:
        Processed response with StreamingBody objects converted to Python objects
    """
    for key, value in response.items():
        if isinstance(value, StreamingBody):
            content = value.read()
            try:
                response[key] = json.loads(content.decode("utf-8"))
            except json.JSONDecodeError:
                response[key] = content.decode("utf-8")
    return response


def get_available_services() -> List[str]:
    """
    Get a list of all available AWS services supported by boto3.

    Returns:
        List of service names as strings
    """
    services = boto3.Session().get_available_services()
    return list(services)


def get_available_operations(service_name: str) -> List[str]:
    """
    Get a list of all available operations for a specific AWS service.

    Args:
        service_name: Name of the AWS service (e.g., 's3', 'ec2')

    Returns:
        List of operation names as strings
    """

    aws_region = os.environ.get("AWS_REGION", "us-west-2")
    try:
        if aws_access_key and aws_secret_key:
            client = boto3.client(
                service_name, 
                region_name=aws_region, 
                aws_access_key_id=aws_access_key, 
                aws_secret_access_key=aws_secret_key, 
                aws_session_token=aws_session_token
            )
        else:
            client = boto3.client(
                service_name, 
                region_name=aws_region
            )
        return [op for op in dir(client) if not op.startswith("_")]
    except Exception as e:
        logger.error(f"Error getting operations for service {service_name}: {str(e)}")
        return []


TOOL_SPEC = {
    "name": "use_aws",
    "description": (
        "Make a boto3 client call with the specified service, operation, and parameters. "
        "Boto3 operations are snake_case."
    ),
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "The name of the AWS service",
                },
                "operation_name": {
                    "type": "string",
                    "description": "The name of the operation to perform",
                },
                "parameters": {
                    "type": "object",
                    "description": "The parameters for the operation",
                },
                "region": {
                    "type": "string",
                    "description": "Region name for calling the operation on AWS boto3",
                },
                "label": {
                    "type": "string",
                    "description": (
                        "Label of AWS API operations human readable explanation. "
                        "This is useful for communicating with human."
                    ),
                },
                "profile_name": {
                    "type": "string",
                    "description": (
                        "Optional: AWS profile name to use from ~/.aws/credentials. "
                        "Defaults to default profile if not specified."
                    ),
                },
            },
            "required": [
                "region",
                "service_name",
                "operation_name",
                "parameters",
                "label",
            ],
        }
    },
}

from typing_extensions import TypedDict
class ToolUse(TypedDict):
    """A request from the model to use a specific tool with the provided input.

    Attributes:
        input: The input parameters for the tool.
            Can be any JSON-serializable type.
        name: The name of the tool to invoke.
    """
    input: Any
    name: str

from strands.types.tools import ToolResult, ToolUse

@mcp.tool()
def use_aws(
    service_name: str,
    operation_name: str,
    parameters: Dict[str, Any],
    region: Optional[str] = None,
    label: str = "AWS Operation Details",
    profile_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute AWS service operations using boto3 with comprehensive error handling and validation.

    This tool provides a universal interface to AWS services, allowing you to execute
    any operation supported by boto3. It handles authentication, parameter validation,
    response formatting, and provides helpful error messages with schema recommendations
    when invalid parameters are provided.

    How It Works:
    ------------
    1. The tool validates the provided service and operation names against available APIs
    2. For potentially disruptive operations (create, delete, etc.), it prompts for confirmation
    3. It sets up a boto3 client with appropriate region and credentials
    4. The requested operation is executed with the provided parameters
    5. Responses are processed to handle special data types (e.g., streaming bodies)
    6. If errors occur, helpful messages and expected parameter schemas are returned

    Common Usage Scenarios:
    ---------------------
    - Resource Management: Create, list, modify or delete AWS resources
    - Data Operations: Store, retrieve, or process data in AWS services
    - Configuration: Update settings or permissions for AWS services
    - Monitoring: Retrieve metrics, logs or status information
    - Security Operations: Manage IAM roles, policies or security settings

    Args:
        service_name: AWS service name (e.g., 's3', 'ec2', 'dynamodb')
        operation_name: Operation to perform in snake_case (e.g., 'list_buckets')
        parameters: Dictionary of parameters for the operation
        region: AWS region (e.g., 'us-west-2')
        label: Human-readable description of the operation
        profile_name: Optional AWS profile name for credentials

    Returns:
        ToolResult dictionary with:
        - status: 'success' or 'error'
        - content: List of content dictionaries with response text

    Notes:
        - Mutative operations (create, delete, etc.) require user confirmation in non-dev environments
        - You can disable confirmation by setting the environment variable BYPASS_TOOL_CONSENT=true
        - The tool automatically handles special response types like streaming bodies
        - For validation errors, the tool attempts to generate the correct input schema
        - All datetime objects are automatically converted to strings for proper JSON serialization
    """
    if region is None:
        region = aws_region

    console = aws_utils.create()

    # Create a panel for AWS Operation Details
    operation_details = f"{Fore.CYAN}Service:{Style.RESET_ALL} {service_name}\n"
    operation_details += f"{Fore.CYAN}Operation:{Style.RESET_ALL} {operation_name}\n"
    operation_details += f"{Fore.CYAN}Parameters:{Style.RESET_ALL}\n"
    for key, value in parameters.items():
        operation_details += f"  - {key}: {value}\n"

    console.print(Panel(operation_details, title=label, expand=False))

    logger.debug(
        "Invoking: service_name = %s, operation_name = %s, parameters = %s" % (service_name, operation_name, parameters)
    )
    
    # Check AWS service
    available_services = get_available_services()
    logger.info(f"Available services: {available_services}")

    if service_name not in available_services:
        logger.debug(f"{Fore.RED}Invalid AWS service: {service_name}{Style.RESET_ALL}")
        return {
            "status": "error",
            "content": [
                {"text": f"Invalid AWS service: {service_name}\nAvailable services: {str(available_services)}"}
            ],
        }

    # Check AWS operation
    available_operations = get_available_operations(service_name)
    if operation_name not in available_operations:
        logger.debug(f"{Fore.RED}Invalid AWS operation: {operation_name}{Style.RESET_ALL}")
        return {
            "status": "error",
            "content": [
                {"text": f"Invalid AWS operation: {operation_name}, Available operations:\n{available_operations}\n"}
            ],
        }

    # Set up the boto3 client
    client = get_boto3_client(service_name, region, profile_name)
    operation_method = getattr(client, operation_name)

    try:
        response = operation_method(**parameters)
        response = handle_streaming_body(response)
        response = aws_utils.convert_datetime_to_str(response)

        return {
            "status": "success",
            "content": [{"text": f"Success: {str(response)}"}],
        }
    except (ValidationError, ParamValidationError) as val_ex:
        # Handle validation errors with schema
        try:
            schema = aws_utils.generate_input_schema(service_name, operation_name)
            logger.info(f"Schema: {schema}")

            return {
                "status": "error",
                "content": [
                    {"text": f"Validation error: {str(val_ex)}"},
                    {"text": f"Expected input schema for {operation_name}:"},
                    {"text": json.dumps(schema, indent=2)},
                ],
            }
        except Exception as schema_ex:
            logger.error(f"Failed to generate schema: {str(schema_ex)}")
            return {
                "status": "error",
                "content": [{"text": f"Validation error: {str(val_ex)}"}],
            }
    except Exception as ex:
        logger.warning(f"AWS call threw exception: {type(ex).__name__}")
        return {
            "status": "error",
            "content": [{"text": f"AWS call threw exception: {str(ex)}"}],
        }
    
if __name__ =="__main__":
    print(f"###### main ######")
    mcp.run(transport="stdio")    