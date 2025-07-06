
import json
import boto3
import logging
import sys
import os
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-log")

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

async def list_groups(
    prefix: Optional[str] = None,
    region: Optional[str] = 'us-west-2'
) -> str:
    """List available CloudWatch log groups."""

    try:
        if aws_access_key and aws_secret_key:
            log_client = boto3.client(
                service_name='logs',
                region_name=region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                aws_session_token=aws_session_token,
            )
        else:
            log_client = boto3.client(
                service_name='logs',
                region_name=region
            )

        kwargs = {}
        if prefix:
            kwargs["logGroupNamePrefix"] = prefix

        response = log_client.describe_log_groups(**kwargs)
        log_groups = response.get("logGroups", [])

        # Format the response
        formatted_groups = []
        for group in log_groups:
            creation_time = group.get("creationTime")
            if creation_time:
                try:
                    creation_time = datetime.fromtimestamp(creation_time / 1000).isoformat()
                except Exception:
                    creation_time = str(creation_time)
                    
            formatted_groups.append(
                {
                    "logGroupName": group.get("logGroupName"),
                    "creationTime": creation_time,
                    "storedBytes": group.get("storedBytes"),
                }
            )

        result = {
            "status": "success",
            "groups": formatted_groups,
            "count": len(formatted_groups)
        }
        response_json = json.dumps(result, ensure_ascii=True, default=str)
        logger.info(f"response: {response_json}")

        return response_json
        
    except Exception as e:
        error_message = f"Error listing log groups: {str(e)}"
        logger.error(error_message)
        result = {
            "status": "error",
            "error": error_message
        }
        return json.dumps(result, ensure_ascii=True)

def _parse_relative_time(time_str: str) -> Optional[int]:
    """Parse a relative time string into a timestamp."""
    if not time_str:
        return None

    logger.debug(f"Parsing time string: {time_str}")

    # Check if it's an ISO format date
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        timestamp = int(dt.timestamp() * 1000)
        logger.debug(f"Parsed ISO format date: {dt.isoformat()}, timestamp: {timestamp}")
        return timestamp
    except ValueError:
        logger.debug(f"Not an ISO format date, trying relative time format")
        pass

    # Parse relative time
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if time_str[-1] in units and time_str[:-1].isdigit():
        value = int(time_str[:-1])
        unit = time_str[-1]
        seconds = value * units[unit]
        dt = datetime.now() - timedelta(seconds=seconds)
        timestamp = int(dt.timestamp() * 1000)
        logger.debug(f"Parsed relative time: {value}{unit}, timestamp: {timestamp}")
        return timestamp

    error_msg = f"Invalid time format: {time_str}"
    logger.error(error_msg)
    raise ValueError(error_msg)

async def get_logs(
    logGroupName: str,
    logStreamName: Optional[str] = None,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    filterPattern: Optional[str] = None,
    region: Optional[str] = 'us-west-2'
) -> str:
    """Get CloudWatch logs from a specific log group and stream."""
    logger.info(
        f"Getting CloudWatch logs for group: {logGroupName}, stream: {logStreamName}, "
        f"startTime: {startTime}, endTime: {endTime}, filterPattern: {filterPattern}, "
        f"region: {region}"
    )

    if aws_access_key and aws_secret_key:
        log_client = boto3.client(
            service_name='logs',
            region_name=region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
        )
    else:
        log_client = boto3.client(
            service_name='logs',
            region_name=region
        )

    # First, check if the log group exists
    try:
        log_groups = log_client.describe_log_groups(logGroupNamePrefix=logGroupName)
        log_group_exists = False
        for group in log_groups.get('logGroups', []):
            if group.get('logGroupName') == logGroupName:
                log_group_exists = True
                break
        
        if not log_group_exists:
            error_message = f"Log group '{logGroupName}' does not exist"
            logger.error(error_message)
            return json.dumps({
                "error": error_message,
                "status": "error",
                "code": "ResourceNotFoundException"
            })
    except Exception as e:
        logger.error(f"Error checking log group existence: {str(e)}")
        return json.dumps({
            "error": f"Error checking log group: {str(e)}",
            "status": "error"
        })

    # Parse start and end times
    start_time_ms = None
    if startTime:
        try:
            start_time_ms = _parse_relative_time(startTime)
        except ValueError as e:
            error_message = f"Invalid startTime format: {str(e)}"
            logger.error(error_message)
            return json.dumps({
                "error": error_message,
                "status": "error"
            })

    end_time_ms = None
    if endTime:
        try:
            end_time_ms = _parse_relative_time(endTime)
        except ValueError as e:
            error_message = f"Invalid endTime format: {str(e)}"
            logger.error(error_message)
            return json.dumps({
                "error": error_message,
                "status": "error"
            })

    # Get logs
    kwargs = {
        "logGroupName": logGroupName,
    }

    if logStreamName:
        kwargs["logStreamNames"] = [logStreamName]

    if filterPattern:
        kwargs["filterPattern"] = filterPattern

    if start_time_ms:
        kwargs["startTime"] = start_time_ms

    if end_time_ms:
        kwargs["endTime"] = end_time_ms

    # Use filter_log_events for more flexible querying
    try:
        response = log_client.filter_log_events(**kwargs)
        events = response.get("events", [])
    except log_client.exceptions.ResourceNotFoundException:
        error_message = f"Log group '{logGroupName}' or stream '{logStreamName}' does not exist"
        logger.error(error_message)
        return json.dumps({
            "error": error_message,
            "status": "error",
            "code": "ResourceNotFoundException"
        })
    except Exception as e:
        error_message = f"Error retrieving logs: {str(e)}"
        logger.error(error_message)
        return json.dumps({
            "error": error_message,
            "status": "error"
        })

    # Format the response
    formatted_events = []
    for event in events:
        timestamp = event.get("timestamp")
        if timestamp:
            try:
                timestamp = datetime.fromtimestamp(timestamp / 1000).isoformat()
            except Exception:
                timestamp = str(timestamp)

        formatted_events.append(
            {
                "timestamp": timestamp,
                "message": event.get("message"),
                "logStreamName": event.get("logStreamName"),
            }
        )    

    response = {
        "status": "success",
        "events": formatted_events,
        "count": len(formatted_events)
    }
    response_json = json.dumps(response, ensure_ascii=False, default=str)
    logger.info(f"response: {response_json}")
    return response_json[:1000]
