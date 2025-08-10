import logging
import sys
import datetime

from typing import List, Optional, Any, Dict
import asyncio
import os
from mcp.types import Resource
import aioboto3
import boto3

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-s3")

# Create AWS session safely
def create_aws_session():
    """
    Safely create AWS session.
    Check environment variables or AWS credentials and return appropriate session.
    """
    try:
        # Check AWS credentials
        session = boto3.Session()
        credentials = session.get_credentials()
        
        if credentials is None:
            logger.warning("AWS credentials not found. Please check environment variables or AWS credentials file.")
            return None
            
        # Try to get account ID
        try:
            sts_client = session.client('sts')
            account_info = sts_client.get_caller_identity()
            logger.info(f"AWS Account ID: {account_info.get('Account')}")
            logger.info(f"User ARN: {account_info.get('Arn')}")
        except Exception as e:
            logger.warning(f"Unable to get AWS account information: {str(e)}")
            
        # Create aioboto3 session more safely
        try:
            # Create aioboto3 session with default settings
            aioboto_session = aioboto3.Session()
            return aioboto_session
        except Exception as e:
            logger.error(f"aioboto3 session creation failed: {str(e)}")
            return None
        
    except Exception as e:
        logger.error(f"Error occurred while creating AWS session: {str(e)}")
        return None

session = create_aws_session()

# Function to get AWS account information
async def get_aws_account_info(region: Optional[str] = "us-west-2") -> Dict:
    """
    Get AWS account information.
    
    Returns:
        dict: AWS account information (account ID, user ARN, user ID, etc.)
    """
    try:
        # Get account information synchronously using boto3
        boto_session = boto3.Session()
        sts_client = boto_session.client('sts', region_name=region)
        response = sts_client.get_caller_identity()
        
        return {
            "account_id": response.get('Account'),
            "user_id": response.get('UserId'),
            "arn": response.get('Arn'),
            "region": region
        }
            
    except Exception as e:
        logger.error(f"Error occurred while getting AWS account information: {str(e)}")
        return {"error": str(e)}

def check_aws_credentials() -> Dict:
    """
    Check AWS credentials status.
    
    Returns:
        dict: Credentials status information
    """
    try:
        # Check credentials using boto3 session
        boto_session = boto3.Session()
        credentials = boto_session.get_credentials()
        
        if credentials is None:
            return {
                "status": "error",
                "message": "AWS credentials not found.",
                "suggestions": [
                    "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.",
                    "Configure credentials in ~/.aws/credentials file.",
                    "Use AWS CLI to run 'aws configure'."
                ]
            }
        
        # Check if credentials are expired
        if hasattr(credentials, 'expiry') and credentials.expiry:
            if credentials.expiry.replace(tzinfo=None) < datetime.datetime.utcnow():
                return {
                    "status": "error",
                    "message": "AWS credentials have expired.",
                    "expiry": str(credentials.expiry)
                }
        
        # Try to get account information
        try:
            sts_client = boto_session.client('sts')
            account_info = sts_client.get_caller_identity()
            return {
                "status": "success",
                "account_id": account_info.get('Account'),
                "user_id": account_info.get('UserId'),
                "arn": account_info.get('Arn'),
                "credentials_type": credentials.method
            }
        except Exception as e:
            return {
                "status": "warning",
                "message": f"Credentials exist but unable to get account information: {str(e)}",
                "credentials_type": credentials.method
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error occurred while checking credentials: {str(e)}"
        }

def _get_configured_buckets() -> List[str]:
    """
    Get configured bucket names from environment variables.
    Format in .env file:
    S3_BUCKETS=bucket1,bucket2,bucket3
    or
    S3_BUCKET_1=bucket1
    S3_BUCKET_2=bucket2
    see env.example ############
    """
    # Try comma-separated list first
    bucket_list = os.getenv('S3_BUCKETS')
    if bucket_list:
        return [b.strip() for b in bucket_list.split(',')]

    buckets = []
    i = 1
    while True:
        bucket = os.getenv(f'S3_BUCKET_{i}')
        if not bucket:
            break
        buckets.append(bucket.strip())
        i += 1

    return buckets            

configured_buckets = _get_configured_buckets()

def is_text_file(key: str) -> bool:
    """Determine if a file is text-based by its extension"""
    text_extensions = {
        '.txt', '.log', '.json', '.xml', '.yml', '.yaml', '.md',
        '.csv', '.ini', '.conf', '.py', '.js', '.html', '.css',
        '.sh', '.bash', '.cfg', '.properties'
    }
    return any(key.lower().endswith(ext) for ext in text_extensions)

async def list_buckets(
    start_after: Optional[str] = None,
    max_buckets: Optional[int] = 5,
    region: Optional[str] = "us-west-2"
) -> List[dict]:
    """
    List S3 buckets using boto3 client with pagination
    """
    try:
        # Get bucket list synchronously using boto3
        boto_session = boto3.Session()
        s3_client = boto_session.client('s3', region_name=region)
        
        if configured_buckets:
            # If buckets are configured, only return those
            response = s3_client.list_buckets()
            all_buckets = response.get('Buckets', [])
            configured_bucket_list = [
                bucket for bucket in all_buckets
                if bucket['Name'] in configured_buckets
            ]

            if start_after:
                configured_bucket_list = [
                    b for b in configured_bucket_list
                    if b['Name'] > start_after
                ]

            return configured_bucket_list[:max_buckets]
        else:
            # Default behavior if no buckets configured
            response = s3_client.list_buckets()
            buckets = response.get('Buckets', [])

            if start_after:
                buckets = [b for b in buckets if b['Name'] > start_after]

            return buckets[:max_buckets]
                
    except Exception as e:
        logger.error(f"Error occurred while getting S3 bucket list: {str(e)}")
        return []

async def list_objects(
    bucket_name: str, 
    prefix: Optional[str] = "", 
    max_keys: Optional[int] = 100,
    region: Optional[str] = "us-west-2"
) -> List[dict]:
    """
    List objects in a specific bucket using boto3 client with pagination
    Args:
        bucket_name: Name of the S3 bucket
        prefix: Object prefix for filtering
        max_keys: Maximum number of keys to return,
        region: Name of the aws region
    """
    try:
        if configured_buckets and bucket_name not in configured_buckets:
            logger.warning(f"Bucket {bucket_name} not in configured bucket list")
            return []

        # Get object list synchronously using boto3
        boto_session = boto3.Session()
        s3_client = boto_session.client('s3', region_name=region)
        
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            MaxKeys=max_keys
        )
        return response.get('Contents', [])
            
    except Exception as e:
        logger.error(f"Error occurred while getting S3 object list: {str(e)}")
        return []
    
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
    resources = []
    logger.debug("Starting to list resources")
    
    logger.debug(f"Configured buckets: {configured_buckets}")

    try:
        # Get limited number of buckets
        buckets = await list_buckets(start_after, max_buckets, region)
        logger.debug(f"Processing {len(buckets)} buckets (max: {max_buckets})")

        # limit concurrent operations
        async def process_bucket(bucket):
            bucket_name = bucket['Name']
            logger.debug(f"Processing bucket: {bucket_name}")

            try:
                # List objects in the bucket with a reasonable limit
                objects = await list_objects(bucket_name, max_keys=100)

                for obj in objects:
                    if 'Key' in obj and not obj['Key'].endswith('/'):
                        object_key = obj['Key']
                        mime_type = "text/plain" if is_text_file(object_key) else "text/markdown"

                        resource = Resource(
                            uri=f"s3://{bucket_name}/{object_key}",
                            name=object_key,
                            mimeType=mime_type
                        )
                        resources.append(resource)
                        logger.debug(f"Added resource: {resource.uri}")

            except Exception as e:
                logger.error(f"Error listing objects in bucket {bucket_name}: {str(e)}")

        # Use semaphore to limit concurrent bucket processing
        semaphore = asyncio.Semaphore(3)  # Limit concurrent bucket processing
        async def process_bucket_with_semaphore(bucket):
            async with semaphore:
                await process_bucket(bucket)

        # Process buckets concurrently
        await asyncio.gather(*[process_bucket_with_semaphore(bucket) for bucket in buckets])

    except Exception as e:
        logger.error(f"Error listing buckets: {str(e)}")
        raise

    logger.info(f"Returning {len(resources)} resources")
    return resources

async def get_total_storage_usage(
    region: Optional[str] = "us-west-2"
) -> dict:
    """
    Calculate total storage usage across all S3 buckets
    
    Returns:
        dict: Dictionary containing total size in bytes, formatted size, and per-bucket breakdown
    """
    logger.info("Calculating total S3 storage usage")
    total_size_bytes = 0
    bucket_stats = {}
    
    try:
        # Get all buckets to analyze
        buckets = await list_buckets(max_buckets=100, region=region)
        logger.info(f"Analyzing storage for {len(buckets)} buckets")
        
        # Process each bucket to get storage information
        semaphore = asyncio.Semaphore(5)  # Limit concurrent operations
        
        def process_bucket_storage(bucket):
            bucket_name = bucket['Name']
            bucket_size = 0
            object_count = 0
            
            try:
                # Calculate storage synchronously using boto3
                boto_session = boto3.Session()
                s3_client = boto_session.client('s3', region_name=region)
                
                # We need to handle pagination for buckets with many objects
                continuation_token = None
                while True:
                    # Create parameters for list_objects_v2
                    params = {
                        'Bucket': bucket_name,
                        'MaxKeys': 500  # Maximum allowed by API
                    }
                    
                    if continuation_token:
                        params['ContinuationToken'] = continuation_token
                    
                    response = s3_client.list_objects_v2(**params)
                    
                    # Process objects in this page
                    for obj in response.get('Contents', []):
                        if 'Size' in obj:
                            bucket_size += obj['Size']
                            object_count += 1
                    
                    # Check if there are more objects to fetch
                    if response.get('IsTruncated', False):
                        continuation_token = response.get('NextContinuationToken')
                    else:
                        break
                
                return bucket_name, bucket_size, object_count
                
            except Exception as e:
                logger.error(f"Error calculating storage for bucket {bucket_name}: {str(e)}")
                return bucket_name, 0, 0
        
        # Process all buckets sequentially since we're using boto3 now
        results = []
        for bucket in buckets:
            results.append(process_bucket_storage(bucket))
        
        # Compile results
        for bucket_name, size, count in results:
            total_size_bytes += size
            bucket_stats[bucket_name] = {
                'size_bytes': size,
                'size_formatted': format_size(size),
                'object_count': count
            }
        
        # Format the total size for human readability
        total_size_formatted = format_size(total_size_bytes)
        
        return {
            'total_size_bytes': total_size_bytes,
            'total_size_formatted': total_size_formatted,
            'bucket_count': len(buckets),
            'buckets': bucket_stats
        }
        
    except Exception as e:
        logger.error(f"Error calculating total storage usage: {str(e)}")
        raise

def format_size(size_bytes):
    """
    Format bytes into human-readable format
    """
    if size_bytes == 0:
        return "0 B"
    
    size_names = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024
        i += 1
    
    return f"{size_bytes:.2f} {size_names[i]}"

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
    logger.info("Retrieving EBS volumes usage information")
    
    total_size_gb = 0
    total_size_bytes = 0
    volumes_info = []
    
    try:
        # Use boto3 for EBS volumes
        boto_session = boto3.Session()
        ec2_client = boto_session.client('ec2', region_name=region)
        
        # Prepare parameters for describe_volumes
        params = {}
        if filters:
            params['Filters'] = filters
            
        # Handle pagination for large number of volumes
        paginator = ec2_client.get_paginator('describe_volumes')
        page_iterator = paginator.paginate(**params)
        
        for page in page_iterator:
                volumes = page.get('Volumes', [])
                
                for volume in volumes:
                    volume_id = volume.get('VolumeId')
                    volume_size_gb = volume.get('Size', 0)  # Size in GiB
                    volume_size_bytes = volume_size_gb * 1024 * 1024 * 1024  # Convert GiB to bytes
                    
                    # Get volume state and other details
                    volume_state = volume.get('State', 'unknown')
                    volume_type = volume.get('VolumeType', 'unknown')
                    availability_zone = volume.get('AvailabilityZone', 'unknown')
                    
                    # Get attached instance information if available
                    attachments = volume.get('Attachments', [])
                    attached_instances = []
                    
                    for attachment in attachments:
                        instance_id = attachment.get('InstanceId')
                        if instance_id:
                            attached_instances.append({
                                'instance_id': instance_id,
                                'device': attachment.get('Device', 'unknown'),
                                'state': attachment.get('State', 'unknown')
                            })
                    
                    # Add volume information to the list
                    volumes_info.append({
                        'volume_id': volume_id,
                        'size_gb': volume_size_gb,
                        'size_bytes': volume_size_bytes,
                        'size_formatted': format_size(volume_size_bytes),
                        'state': volume_state,
                        'type': volume_type,
                        'availability_zone': availability_zone,
                        'attached_instances': attached_instances,
                        'encrypted': volume.get('Encrypted', False),
                        'create_time': str(volume.get('CreateTime', ''))
                    })
                    
                    # Add to total size
                    total_size_gb += volume_size_gb
                    total_size_bytes += volume_size_bytes
    
        # Calculate summary information
        total_size_formatted = format_size(total_size_bytes)
        
        # Group volumes by state
        volumes_by_state = {}
        for volume in volumes_info:
            state = volume['state']
            if state not in volumes_by_state:
                volumes_by_state[state] = {
                    'count': 0,
                    'total_size_gb': 0
                }
            volumes_by_state[state]['count'] += 1
            volumes_by_state[state]['total_size_gb'] += volume['size_gb']
        
        # Group volumes by type
        volumes_by_type = {}
        for volume in volumes_info:
            vol_type = volume['type']
            if vol_type not in volumes_by_type:
                volumes_by_type[vol_type] = {
                    'count': 0,
                    'total_size_gb': 0
                }
            volumes_by_type[vol_type]['count'] += 1
            volumes_by_type[vol_type]['total_size_gb'] += volume['size_gb']
        
        return {
            'total_volumes': len(volumes_info),
            'total_size_gb': total_size_gb,
            'total_size_bytes': total_size_bytes,
            'total_size_formatted': total_size_formatted,
            'volumes_by_state': volumes_by_state,
            'volumes_by_type': volumes_by_type,
            'volumes': volumes_info
        }
        
    except Exception as e:
        logger.error(f"Error retrieving EBS volumes information: {str(e)}")
        raise

async def get_ebs_snapshots_usage(
    region: Optional[str] = "us-west-2",
    owner_ids: Optional[List[str]] = None,
    filters: Optional[List[Dict]] = None
) -> Dict:
    """
    Get EBS snapshots usage information
    
    Args:
        region: AWS region name
        owner_ids: Optional list of AWS account IDs that own the snapshots
        filters: Optional list of filters to apply when retrieving snapshots
                Example: [{'Name': 'status', 'Values': ['completed']}]
    
    Returns:
        dict: Dictionary containing total EBS snapshots information and per-snapshot details
    """
    logger.info("Retrieving EBS snapshots usage information")
    
    total_size_bytes = 0
    snapshots_info = []
    
    try:
        # Use boto3 for EBS snapshots
        boto_session = boto3.Session()
        ec2_client = boto_session.client('ec2', region_name=region)
        
        # Prepare parameters for describe_snapshots
        params = {}
        if owner_ids:
            params['OwnerIds'] = owner_ids
        if filters:
            params['Filters'] = filters
            
        # Handle pagination for large number of snapshots
        paginator = ec2_client.get_paginator('describe_snapshots')
        page_iterator = paginator.paginate(**params)
        
        for page in page_iterator:
                snapshots = page.get('Snapshots', [])
                
                for snapshot in snapshots:
                    snapshot_id = snapshot.get('SnapshotId')
                    volume_id = snapshot.get('VolumeId')
                    volume_size_gb = snapshot.get('VolumeSize', 0)  # Size in GiB
                    volume_size_bytes = volume_size_gb * 1024 * 1024 * 1024  # Convert GiB to bytes
                    
                    # Get snapshot state and other details
                    snapshot_state = snapshot.get('State', 'unknown')
                    start_time = snapshot.get('StartTime', '')
                    description = snapshot.get('Description', '')
                    
                    # Add snapshot information to the list
                    snapshots_info.append({
                        'snapshot_id': snapshot_id,
                        'volume_id': volume_id,
                        'size_gb': volume_size_gb,
                        'size_bytes': volume_size_bytes,
                        'size_formatted': format_size(volume_size_bytes),
                        'state': snapshot_state,
                        'start_time': str(start_time),
                        'description': description,
                        'encrypted': snapshot.get('Encrypted', False),
                        'owner_id': snapshot.get('OwnerId', '')
                    })
                    
                    # Add to total size
                    total_size_bytes += volume_size_bytes
    
        # Calculate summary information
        total_size_formatted = format_size(total_size_bytes)
        
        # Group snapshots by state
        snapshots_by_state = {}
        for snapshot in snapshots_info:
            state = snapshot['state']
            if state not in snapshots_by_state:
                snapshots_by_state[state] = {
                    'count': 0,
                    'total_size_gb': 0
                }
            snapshots_by_state[state]['count'] += 1
            snapshots_by_state[state]['total_size_gb'] += snapshot['size_gb']
        
        return {
            'total_snapshots': len(snapshots_info),
            'total_size_bytes': total_size_bytes,
            'total_size_formatted': total_size_formatted,
            'snapshots_by_state': snapshots_by_state,
            'snapshots': snapshots_info
        }
        
    except Exception as e:
        logger.error(f"Error retrieving EBS snapshots information: {str(e)}")
        raise

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
    logger.info("Retrieving EFS usage information")
    
    total_size_bytes = 0
    file_systems_info = []
    
    try:
        # First, get all EFS file systems using boto3
        boto_session = boto3.Session()
        efs_client = boto_session.client('efs', region_name=region)
        file_systems = []
        
        if file_system_ids:
            # If specific file system IDs are provided, get only those
            for fs_id in file_system_ids:
                try:
                    response = efs_client.describe_file_systems(FileSystemId=fs_id)
                    if 'FileSystems' in response:
                        file_systems.extend(response['FileSystems'])
                except Exception as e:
                    logger.error(f"Error retrieving EFS file system {fs_id}: {str(e)}")
        else:
            # Otherwise, get all file systems
            paginator = efs_client.get_paginator('describe_file_systems')
            page_iterator = paginator.paginate()
            
            for page in page_iterator:
                file_systems.extend(page.get('FileSystems', []))
        
        logger.info(f"Found {len(file_systems)} EFS file systems")
        
        # Now get CloudWatch metrics for each file system
        cloudwatch_client = boto_session.client('cloudwatch', region_name=region)
        # Calculate time range for metrics
        end_time = datetime.datetime.utcnow()
        start_time = end_time - datetime.timedelta(hours=period_hours)
        
        for fs in file_systems:
            fs_id = fs.get('FileSystemId')
            name = fs.get('Name', '')
            creation_time = fs.get('CreationTime', '')
            lifecycle_state = fs.get('LifeCycleState', '')
            performance_mode = fs.get('PerformanceMode', '')
            throughput_mode = fs.get('ThroughputMode', '')
            encrypted = fs.get('Encrypted', False)
            
            # Get the current size metric
            try:
                # Get the most recent StorageBytes metric
                response = cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/EFS',
                    MetricName='StorageBytes',
                    Dimensions=[
                        {
                            'Name': 'FileSystemId',
                            'Value': fs_id
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=3600,  # 1 hour
                    Statistics=['Average'],
                    Unit='Bytes'
                )
                        
                # Get the most recent data point
                datapoints = response.get('Datapoints', [])
                if datapoints:
                    # Sort by timestamp to get the most recent
                    datapoints.sort(key=lambda x: x['Timestamp'], reverse=True)
                    size_bytes = datapoints[0].get('Average', 0)
                else:
                    # If no datapoints, use the SizeInBytes from describe_file_systems
                    size_bytes = fs.get('SizeInBytes', {}).get('Value', 0)
                
                # Add to total size
                total_size_bytes += size_bytes
                
                # Get additional metrics: burst credit balance, IO operations
                burst_credit_response = cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/EFS',
                    MetricName='BurstCreditBalance',
                    Dimensions=[
                        {
                            'Name': 'FileSystemId',
                            'Value': fs_id
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=3600,  # 1 hour
                    Statistics=['Average'],
                    Unit='Bytes'
                )
                
                burst_credits = 0
                if burst_credit_response.get('Datapoints'):
                    burst_credit_datapoints = burst_credit_response['Datapoints']
                    burst_credit_datapoints.sort(key=lambda x: x['Timestamp'], reverse=True)
                    burst_credits = burst_credit_datapoints[0].get('Average', 0)
                
                # Add file system information to the list
                file_systems_info.append({
                    'file_system_id': fs_id,
                    'name': name,
                    'size_bytes': size_bytes,
                    'size_formatted': format_size(size_bytes),
                    'lifecycle_state': lifecycle_state,
                    'performance_mode': performance_mode,
                    'throughput_mode': throughput_mode,
                    'encrypted': encrypted,
                    'creation_time': str(creation_time),
                    'burst_credit_balance': burst_credits,
                    'burst_credit_balance_formatted': format_size(burst_credits)
                })
                
            except Exception as e:
                logger.error(f"Error retrieving CloudWatch metrics for EFS {fs_id}: {str(e)}")
                # Still add the file system to the list with available information
                file_systems_info.append({
                    'file_system_id': fs_id,
                    'name': name,
                    'size_bytes': 0,
                    'size_formatted': '0 B',
                    'lifecycle_state': lifecycle_state,
                    'performance_mode': performance_mode,
                    'throughput_mode': throughput_mode,
                    'encrypted': encrypted,
                    'creation_time': str(creation_time),
                    'error': str(e)
                })
        
        # Calculate summary information
        total_size_formatted = format_size(total_size_bytes)
        
        # Group file systems by lifecycle state
        fs_by_state = {}
        for fs in file_systems_info:
            state = fs['lifecycle_state']
            if state not in fs_by_state:
                fs_by_state[state] = {
                    'count': 0,
                    'total_size_bytes': 0
                }
            fs_by_state[state]['count'] += 1
            fs_by_state[state]['total_size_bytes'] += fs['size_bytes']
        
        # Group file systems by performance mode
        fs_by_performance = {}
        for fs in file_systems_info:
            perf_mode = fs['performance_mode']
            if perf_mode not in fs_by_performance:
                fs_by_performance[perf_mode] = {
                    'count': 0,
                    'total_size_bytes': 0
                }
            fs_by_performance[perf_mode]['count'] += 1
            fs_by_performance[perf_mode]['total_size_bytes'] += fs['size_bytes']
        
        return {
            'total_file_systems': len(file_systems_info),
            'total_size_bytes': total_size_bytes,
            'total_size_formatted': total_size_formatted,
            'file_systems_by_state': fs_by_state,
            'file_systems_by_performance': fs_by_performance,
            'file_systems': file_systems_info
        }
        
    except Exception as e:
        logger.error(f"Error retrieving EFS usage information: {str(e)}")
        raise
