#!/usr/bin/env python3
"""
AWS Infrastructure Installer using boto3
This script creates AWS infrastructure resources equivalent to the CDK stack.
"""

import boto3
import json
import os
import time
import logging
import argparse
import base64
import ipaddress
from datetime import datetime
from typing import Dict, List, Optional
from botocore.exceptions import ClientError

# Configuration
project_name = "mcp"
region = "us-west-2"

sts_client = boto3.client("sts", region_name=region)
account_id = sts_client.get_caller_identity()["Account"]

vector_index_name = project_name
custom_header_name = "X-Custom-Header"
custom_header_value = f"{project_name}_12dab15e4s31"

# Initialize boto3 clients
s3_client = boto3.client("s3", region_name=region)
iam_client = boto3.client("iam", region_name=region)
secrets_client = boto3.client("secretsmanager", region_name=region)
opensearch_client = boto3.client("opensearchserverless", region_name=region)
ec2_client = boto3.client("ec2", region_name=region)
elbv2_client = boto3.client("elbv2", region_name=region)
cloudfront_client = boto3.client("cloudfront", region_name=region)
lambda_client = boto3.client("lambda", region_name=region)
ssm_client = boto3.client("ssm", region_name=region)

bucket_name = f"storage-for-{project_name}-{account_id}-{region}"

# Configure logging
def setup_logging(log_level=logging.INFO):
    """Setup logging configuration."""
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f"installer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        ]
    )
    
    return logging.getLogger(__name__)


logger = setup_logging()


def create_s3_bucket() -> str:
    """Create S3 bucket with CORS configuration."""
    logger.info(f"[1/9] Creating S3 bucket: {bucket_name}")
    
    try:
        # Create bucket
        logger.debug(f"Creating bucket in region: {region}")
        if region == "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region}
            )
        logger.debug("Bucket created successfully")
        
        # Configure bucket
        logger.debug("Configuring public access block")
        s3_client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True
            }
        )
        
        # Set CORS configuration
        logger.debug("Setting CORS configuration")
        cors_configuration = {
            "CORSRules": [
                {
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET", "POST", "PUT"],
                    "AllowedOrigins": ["*"]
                }
            ]
        }
        s3_client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration=cors_configuration
        )
        
        # Enable versioning (set to false means suspend)
        logger.debug("Configuring versioning")
        s3_client.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={"Status": "Suspended"}
        )
        
        # Create docs folder
        logger.debug("Creating docs folder")
        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key="docs/",
                Body=b""
            )
            logger.debug("docs folder created successfully")
        except ClientError as e:
            logger.warning(f"Failed to create docs folder: {e}")
        
        logger.info(f"✓ S3 bucket created successfully: {bucket_name}")
        return bucket_name
    
    except ClientError as e:
        if e.response["Error"]["Code"] in ["BucketAlreadyExists", "BucketAlreadyOwnedByYou"]:
            logger.warning(f"S3 bucket already exists: {bucket_name}")
            # Create docs folder if bucket already exists
            logger.debug("Creating docs folder in existing bucket")
            try:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key="docs/",
                    Body=b""
                )
                logger.debug("docs folder created successfully")
            except ClientError as folder_error:
                if folder_error.response["Error"]["Code"] != "NoSuchBucket":
                    logger.warning(f"Failed to create docs folder: {folder_error}")
            return bucket_name
        logger.error(f"Failed to create S3 bucket: {e}")
        raise


def create_iam_role(role_name: str, assume_role_policy: Dict, managed_policies: Optional[List[str]] = None) -> str:
    """Create IAM role."""
    logger.debug(f"Creating IAM role: {role_name}")
    
    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description=f"Role for {role_name}"
        )
        role_arn = response["Role"]["Arn"]
        logger.debug(f"Role created: {role_arn}")
        
        if managed_policies:
            logger.debug(f"Attaching {len(managed_policies)} managed policies")
            for policy_arn in managed_policies:
                iam_client.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy_arn
                )
                logger.debug(f"Attached policy: {policy_arn}")
        
        logger.info(f"✓ IAM role created: {role_name}")
        return role_arn
    
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            logger.warning(f"IAM role already exists: {role_name}")
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]
            
            # Update managed policies if provided
            if managed_policies:
                logger.debug(f"Updating managed policies for existing role")
                # Get currently attached managed policies
                try:
                    attached_policies = iam_client.list_attached_role_policies(RoleName=role_name)
                    current_policy_arns = {policy["PolicyArn"] for policy in attached_policies["AttachedPolicies"]}
                    
                    # Attach missing policies
                    for policy_arn in managed_policies:
                        if policy_arn not in current_policy_arns:
                            iam_client.attach_role_policy(
                                RoleName=role_name,
                                PolicyArn=policy_arn
                            )
                            logger.debug(f"Attached missing policy: {policy_arn}")
                except ClientError as policy_error:
                    logger.warning(f"Could not update managed policies: {policy_error}")
            
            return role_arn
        logger.error(f"Failed to create IAM role {role_name}: {e}")
        raise


def attach_inline_policy(role_name: str, policy_name: str, policy_document: Dict):
    """Attach or update inline policy to IAM role."""
    logger.debug(f"Attaching/updating inline policy {policy_name} to {role_name}")
    
    try:
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document)
        )
        logger.debug(f"Policy {policy_name} attached/updated successfully")
    except ClientError as e:
        logger.error(f"Error attaching/updating policy {policy_name}: {e}")
        raise


def create_knowledge_base_role() -> str:
    """Create Knowledge Base IAM role."""
    logger.info("[2/9] Creating Knowledge Base IAM role")
    role_name = f"role-knowledge-base-for-{project_name}-{region}"
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    role_arn = create_iam_role(role_name, assume_role_policy)
    
    # Always attach/update inline policies (put_role_policy will create or update)
    bedrock_invoke_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["bedrock:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"bedrock-invoke-policy-for-{project_name}", bedrock_invoke_policy)
    
    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"knowledge-base-s3-policy-for-{project_name}", s3_policy)
    
    opensearch_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["aoss:APIAccessAll"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"bedrock-agent-opensearch-policy-for-{project_name}", opensearch_policy)
    
    bedrock_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["bedrock:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"bedrock-agent-bedrock-policy-for-{project_name}", bedrock_policy)
    
    return role_arn


def create_agent_role() -> str:
    """Create Agent IAM role."""
    logger.info("[2/9] Creating Agent IAM role")
    role_name = f"role-agent-for-{project_name}-{region}"
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    role_arn = create_iam_role(role_name, assume_role_policy, ["arn:aws:iam::aws:policy/AWSLambdaExecute"])
    
    # Always attach/update inline policies
    bedrock_retrieve_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["bedrock:Retrieve"],
                "Resource": [f"arn:aws:bedrock:{region}:{account_id}:knowledge-base/*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"bedrock-retrieve-policy-for-{project_name}", bedrock_retrieve_policy)
    
    inference_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:GetInferenceProfile",
                    "bedrock:GetFoundationModel"
                ],
                "Resource": [
                    f"arn:aws:bedrock:{region}:{account_id}:inference-profile/*",
                    "arn:aws:bedrock:*::foundation-model/*"
                ]
            }
        ]
    }
    attach_inline_policy(role_name, f"agent-inference-policy-for-{project_name}", inference_policy)
    
    lambda_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction", "cloudwatch:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"lambda-invoke-policy-for-{project_name}", lambda_policy)
    
    bedrock_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["bedrock:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"bedrock-policy-agent-for-{project_name}", bedrock_policy)
    
    return role_arn


def create_ec2_role(knowledge_base_role_arn: str) -> str:
    """Create EC2 IAM role."""
    logger.info("[2/9] Creating EC2 IAM role")
    role_name = f"role-ec2-for-{project_name}-{region}"
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": ["ec2.amazonaws.com", "bedrock.amazonaws.com"]
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    managed_policies = [
        "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
        "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    ]
    role_arn = create_iam_role(role_name, assume_role_policy, managed_policies)
    
    # Attach inline policies
    policies = [
        {
            "name": f"secret-manager-policy-ec2-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"pvre-policy-ec2-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["ssm:*", "ssmmessages:*", "ec2messages:*", "tag:*"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"bedrock-policy-ec2-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock:*"],
                        "Resource": ["*"]
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "bedrock:InvokeModel",
                            "bedrock:InvokeModelWithResponseStream"
                        ],
                        "Resource": [
                            "arn:aws:bedrock:*:*:inference-profile/*",
                            "arn:aws:bedrock:us-west-2:*:foundation-model/*",
                            "arn:aws:bedrock:us-east-1:*:foundation-model/*",
                            "arn:aws:bedrock:us-east-2:*:foundation-model/*"
                        ]
                    }
                ]
            }
        },
        {
            "name": f"cost-explorer-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["ce:GetCostAndUsage"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"ec2-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["ec2:*"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"lambda-invoke-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["lambda:InvokeFunction"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"efs-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["ec2:DescribeFileSystems", "elasticfilesystem:DescribeFileSystems"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"cognito-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "cognito-idp:ListUserPools",
                            "cognito-idp:DescribeUserPool",
                            "cognito-idp:ListUserPoolClients",
                            "cognito-idp:DescribeUserPoolClient"
                        ],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"bedrock-agentcore-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock-agentcore:*"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"pass-role-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["iam:PassRole"],
                        "Resource": [knowledge_base_role_arn]
                    }
                ]
            }
        },
        {
            "name": f"aoss-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["aoss:*"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"getRole-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["iam:GetRole"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"s3-bucket-access-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:*"],
                        "Resource": ["*"]
                    }
                ]
            }
        },
        {
            "name": f"cloudwatch-logs-policy-for-{project_name}",
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "logs:DescribeLogGroups",
                            "logs:DescribeLogStreams",
                            "logs:GetLogEvents",
                            "logs:FilterLogEvents",
                            "logs:GetLogGroupFields",
                            "logs:GetLogRecord",
                            "logs:GetQueryResults",
                            "logs:StartQuery",
                            "logs:StopQuery"
                        ],
                        "Resource": ["*"]
                    }
                ]
            }
        }
    ]
    
    for policy in policies:
        attach_inline_policy(role_name, policy["name"], policy["document"])
    
    # Create instance profile
    instance_profile_name = f"instance-profile-{project_name}-{region}"
    try:
        iam_client.create_instance_profile(InstanceProfileName=instance_profile_name)
        iam_client.add_role_to_instance_profile(
            InstanceProfileName=instance_profile_name,
            RoleName=role_name
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
    
    return role_arn


def create_secrets() -> Dict[str, str]:
    """Create Secrets Manager secrets."""
    logger.info("[3/9] Creating Secrets Manager secrets")
    logger.info("Please enter API keys when prompted (press Enter to skip and leave empty):")
    
    secrets = {
        "weather": {
            "name": f"openweathermap-{project_name}",
            "description": "secret for weather api key",
            "secret_value": {
                "project_name": project_name,
                "weather_api_key": ""
            }
        },
        "langsmith": {
            "name": f"langsmithapikey-{project_name}",
            "description": "secret for lamgsmith api key",
            "secret_value": {
                "langchain_project": project_name,
                "langsmith_api_key": ""
            }
        },
        "tavily": {
            "name": f"tavilyapikey-{project_name}",
            "description": "secret for tavily api key",
            "secret_value": {
                "project_name": project_name,
                "tavily_api_key": ""
            }
        },
        "perplexity": {
            "name": f"perplexityapikey-{project_name}",
            "description": "secret for perflexity api key",
            "secret_value": {
                "project_name": project_name,
                "perplexity_api_key": ""
            }
        },
        "firecrawl": {
            "name": f"firecrawlapikey-{project_name}",
            "description": "secret for firecrawl api key",
            "secret_value": {
                "project_name": project_name,
                "firecrawl_api_key": ""
            }
        },
        "nova_act": {
            "name": f"novaactapikey-{project_name}",
            "description": "secret for nova act api key",
            "secret_value": {
                "project_name": project_name,
                "nova_act_api_key": ""
            }
        },
        "notion": {
            "name": f"notionapikey-{project_name}",
            "description": "secret for notion api key",
            "secret_value": {
                "project_name": project_name,
                "notion_api_key": ""
            }
        }
    }
    
    secret_arns = {}
    
    for key, secret_config in secrets.items():
        # Check if secret already exists before prompting for input
        try:
            response = secrets_client.describe_secret(SecretId=secret_config["name"])
            secret_arns[key] = response["ARN"]
            logger.warning(f"  Secret already exists: {secret_config['name']}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                # Secret doesn't exist, prompt for API key and create it
                if key == "weather":
                    logger.info(f"Enter credential of {secret_config['name']} (Weather API Key - OpenWeatherMap):")
                    api_key = input(f"Creating {secret_config['name']} - Weather API Key (OpenWeatherMap): ").strip()
                    secret_config["secret_value"]["weather_api_key"] = api_key
                elif key == "langsmith":
                    logger.info(f"Enter credential of {secret_config['name']} (LangSmith API Key):")
                    api_key = input(f"Creating {secret_config['name']} - LangSmith API Key: ").strip()
                    secret_config["secret_value"]["langsmith_api_key"] = api_key
                elif key == "tavily":
                    logger.info(f"Enter credential of {secret_config['name']} (Tavily API Key):")
                    api_key = input(f"Creating {secret_config['name']} - Tavily API Key: ").strip()
                    secret_config["secret_value"]["tavily_api_key"] = api_key
                elif key == "perplexity":
                    logger.info(f"Enter credential of {secret_config['name']} (Perplexity API Key):")
                    api_key = input(f"Creating {secret_config['name']} - Perplexity API Key: ").strip()
                    secret_config["secret_value"]["perplexity_api_key"] = api_key
                elif key == "firecrawl":
                    logger.info(f"Enter credential of {secret_config['name']} (Firecrawl API Key):")
                    api_key = input(f"Creating {secret_config['name']} - Firecrawl API Key: ").strip()
                    secret_config["secret_value"]["firecrawl_api_key"] = api_key
                elif key == "nova_act":
                    logger.info(f"Enter credential of {secret_config['name']} (Nova Act API Key):")
                    api_key = input(f"Creating {secret_config['name']} - Nova Act API Key: ").strip()
                    secret_config["secret_value"]["nova_act_api_key"] = api_key
                elif key == "notion":
                    logger.info(f"Enter credential of {secret_config['name']} (Notion API Key):")
                    api_key = input(f"Creating {secret_config['name']} - Notion API Key: ").strip()
                    secret_config["secret_value"]["notion_api_key"] = api_key
                
                # Create the secret
                try:
                    response = secrets_client.create_secret(
                        Name=secret_config["name"],
                        Description=secret_config["description"],
                        SecretString=json.dumps(secret_config["secret_value"])
                    )
                    secret_arns[key] = response["ARN"]
                    logger.info(f"  ✓ Created secret: {secret_config['name']}")
                except ClientError as create_error:
                    logger.error(f"  Failed to create secret {secret_config['name']}: {create_error}")
                    raise
            else:
                logger.error(f"  Failed to check secret {secret_config['name']}: {e}")
                raise
    
    logger.info(f"✓ Created {len(secret_arns)} secrets")
    
    return secret_arns


def create_opensearch_collection(ec2_role_arn: str = None, knowledge_base_role_arn: str = None) -> Dict[str, str]:
    """Create OpenSearch Serverless collection and policies."""
    logger.info("[4/9] Creating OpenSearch Serverless collection")
    
    collection_name = vector_index_name
    enc_policy_name = f"encription-{project_name}-{region}"
    net_policy_name = f"network-{project_name}-{region}"
    data_policy_name = f"data-{project_name}"
    
    # Check if collection already exists first
    try:
        existing_collections = opensearch_client.list_collections()
        for collection in existing_collections.get("collectionSummaries", []):
            if collection["name"] == collection_name and collection["status"] == "ACTIVE":
                logger.warning(f"OpenSearch collection already exists: {collection['name']}")
                collection_arn = collection["arn"]
                collection_id = collection["id"]
                
                # Get collection endpoint
                collection_details = opensearch_client.batch_get_collection(names=[collection_name])
                collection_endpoint = collection_details["collectionDetails"][0].get("collectionEndpoint", "")
                
                # Update data access policy to include roles if needed
                try:
                    policy_detail = opensearch_client.get_access_policy(
                        name=data_policy_name,
                        type="data"
                    )
                    current_policy = policy_detail["accessPolicyDetail"]["policy"]
                    
                    # Check if roles are already in principals and update if needed
                    needs_update = False
                    roles_to_add = []
                    if ec2_role_arn:
                        roles_to_add.append(("EC2", ec2_role_arn))
                    if knowledge_base_role_arn:
                        roles_to_add.append(("Knowledge Base", knowledge_base_role_arn))
                    
                    for rule in current_policy:
                        if "Principal" in rule:
                            current_principals = rule["Principal"]
                            if not isinstance(current_principals, list):
                                current_principals = [current_principals]
                            
                            for role_type, role_arn in roles_to_add:
                                if role_arn and role_arn not in current_principals:
                                    current_principals.append(role_arn)
                                    needs_update = True
                                    logger.debug(f"Adding {role_type} role to data access policy: {role_arn}")
                            
                            rule["Principal"] = current_principals
                    
                    # Update policy if needed
                    if needs_update:
                        opensearch_client.update_access_policy(
                            name=data_policy_name,
                            type="data",
                            policy=json.dumps(current_policy),
                            policyVersion=policy_detail["accessPolicyDetail"]["policyVersion"]
                        )
                        logger.info(f"Updated data access policy to include roles")
                    else:
                        logger.debug("All roles already present in data access policy")
                except Exception as update_error:
                    logger.warning(f"Could not update existing data access policy: {update_error}")
                
                return {
                    "arn": collection_arn,
                    "endpoint": collection_endpoint
                }
    except Exception as e:
        logger.debug(f"Error checking existing collections: {e}")
    
    # Create encryption policy
    enc_policy = {
        "Rules": [
            {
                "ResourceType": "collection",
                "Resource": [f"collection/{collection_name}"]
            }
        ],
        "AWSOwnedKey": True
    }
    
    try:
        opensearch_client.create_security_policy(
            name=enc_policy_name,
            type="encryption",
            description=f"opensearch encryption policy for {project_name}",
            policy=json.dumps(enc_policy)
        )
        logger.debug(f"Created encryption policy: {enc_policy_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            logger.warning(f"Encryption policy already exists: {enc_policy_name}")
        else:
            logger.error(f"Failed to create encryption policy: {e}")
            raise
    
    # Create network policy
    net_policy = [
        {
            "Rules": [
                {
                    "ResourceType": "dashboard",
                    "Resource": [f"collection/{collection_name}"]
                },
                {
                    "ResourceType": "collection",
                    "Resource": [f"collection/{collection_name}"]
                }
            ],
            "AllowFromPublic": True
        }
    ]
    
    try:
        opensearch_client.create_security_policy(
            name=net_policy_name,
            type="network",
            description=f"opensearch network policy for {project_name}",
            policy=json.dumps(net_policy)
        )
        logger.debug(f"Created network policy: {net_policy_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            logger.warning(f"Network policy already exists: {net_policy_name}")
        else:
            logger.error(f"Failed to create network policy: {e}")
            raise
    
    # Create data access policy
    account_arn = f"arn:aws:iam::{account_id}:root"
    principals = [account_arn]
    
    # Add EC2 role to principals if provided
    if ec2_role_arn:
        principals.append(ec2_role_arn)
        logger.debug(f"Adding EC2 role to data access policy: {ec2_role_arn}")
    
    # Add Knowledge Base role to principals if provided
    if knowledge_base_role_arn:
        principals.append(knowledge_base_role_arn)
        logger.debug(f"Adding Knowledge Base role to data access policy: {knowledge_base_role_arn}")
    
    data_policy = [
        {
            "Rules": [
                {
                    "Resource": [f"collection/{collection_name}"],
                    "Permission": [
                        "aoss:CreateCollectionItems",
                        "aoss:DeleteCollectionItems",
                        "aoss:UpdateCollectionItems",
                        "aoss:DescribeCollectionItems"
                    ],
                    "ResourceType": "collection"
                },
                {
                    "Resource": [f"index/{collection_name}/*"],
                    "Permission": [
                        "aoss:CreateIndex",
                        "aoss:DeleteIndex",
                        "aoss:UpdateIndex",
                        "aoss:DescribeIndex",
                        "aoss:ReadDocument",
                        "aoss:WriteDocument"
                    ],
                    "ResourceType": "index"
                }
            ],
            "Principal": principals
        }
    ]
    
    try:
        opensearch_client.create_access_policy(
            name=data_policy_name,
            type="data",
            policy=json.dumps(data_policy)
        )
        logger.debug(f"Created data access policy: {data_policy_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            logger.warning(f"Data access policy already exists: {data_policy_name}")
            # Try to update existing policy to include roles
            try:
                # Get current policy version
                policy_detail = opensearch_client.get_access_policy(
                    name=data_policy_name,
                    type="data"
                )
                current_policy = policy_detail["accessPolicyDetail"]["policy"]
                
                # Check if roles are already in principals and update if needed
                needs_update = False
                roles_to_add = []
                if ec2_role_arn:
                    roles_to_add.append(("EC2", ec2_role_arn))
                if knowledge_base_role_arn:
                    roles_to_add.append(("Knowledge Base", knowledge_base_role_arn))
                
                for rule in current_policy:
                    if "Principal" in rule:
                        current_principals = rule["Principal"]
                        if not isinstance(current_principals, list):
                            current_principals = [current_principals]
                        
                        for role_type, role_arn in roles_to_add:
                            if role_arn and role_arn not in current_principals:
                                current_principals.append(role_arn)
                                needs_update = True
                                logger.debug(f"Adding {role_type} role to data access policy: {role_arn}")
                        
                        rule["Principal"] = current_principals
                
                # Update policy if needed
                if needs_update:
                    opensearch_client.update_access_policy(
                        name=data_policy_name,
                        type="data",
                        policy=json.dumps(current_policy),
                        policyVersion=policy_detail["accessPolicyDetail"]["policyVersion"]
                    )
                    logger.info(f"Updated data access policy to include roles")
                else:
                    logger.debug("All roles already present in data access policy")
            except Exception as update_error:
                logger.warning(f"Could not update existing data access policy: {update_error}")
                if ec2_role_arn:
                    logger.warning(f"Please manually add EC2 role {ec2_role_arn} to the data access policy")
                if knowledge_base_role_arn:
                    logger.warning(f"Please manually add Knowledge Base role {knowledge_base_role_arn} to the data access policy")
        else:
            logger.error(f"Failed to create data access policy: {e}")
            raise
    
    # Wait for policies to be ready
    logger.debug("Waiting for policies to be ready...")
    time.sleep(5)
    
    # Create collection
    try:
        response = opensearch_client.create_collection(
            name=collection_name,
            description=f"opensearch correction for {project_name}",
            type="VECTORSEARCH"
        )
        collection_detail = response["createCollectionDetail"]
        collection_arn = collection_detail["arn"]
        
        # Wait for collection to be active and get endpoint
        logger.info("  Waiting for collection to be active (this may take a few minutes)...")
        collection_endpoint = None
        wait_count = 0
        while True:
            response = opensearch_client.batch_get_collection(
                names=[collection_name]
            )
            collection_detail = response["collectionDetails"][0]
            status = collection_detail["status"]
            wait_count += 1
            if wait_count % 6 == 0:  # Log every minute
                logger.debug(f"  Collection status: {status} (waited {wait_count * 10} seconds)")
            
            # Check if endpoint is available
            if "collectionEndpoint" in collection_detail:
                collection_endpoint = collection_detail["collectionEndpoint"]
                if status == "ACTIVE":
                    break
            time.sleep(10)

        # Wait for opensearch correction to be ready
        logger.debug("Waiting for opensearch correction to be ready...")
        time.sleep(30)
            
        logger.info(f"✓ OpenSearch collection created: {collection_name}")
        logger.info(f"  Endpoint: {collection_endpoint}")
        return {
            "arn": collection_arn,
            "endpoint": collection_endpoint
        }
    
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            logger.warning(f"OpenSearch collection already exists: {collection_name}")
            response = opensearch_client.batch_get_collection(names=[collection_name])
            collection_detail = response["collectionDetails"][0]
            return {
                "arn": collection_detail["arn"],
                "endpoint": collection_detail.get("collectionEndpoint", "")
            }
        logger.error(f"Failed to create OpenSearch collection: {e}")
        raise


def get_available_cidr_block() -> str:
    """Get an available CIDR block that doesn't conflict with existing VPCs."""
    # Candidate CIDR blocks to try
    candidate_cidrs = [
        "10.20.0.0/16",
        "10.21.0.0/16", 
        "10.22.0.0/16",
        "10.23.0.0/16",
        "10.24.0.0/16",
        "172.16.0.0/16",
        "172.17.0.0/16",
        "172.18.0.0/16",
        "192.168.0.0/16"
    ]
    
    # Get all existing VPC CIDR blocks
    existing_cidrs = set()
    try:
        vpcs = ec2_client.describe_vpcs()
        for vpc in vpcs["Vpcs"]:
            existing_cidrs.add(vpc["CidrBlock"])
            # Also check additional CIDR blocks
            for cidr_assoc in vpc.get("CidrBlockAssociationSet", []):
                existing_cidrs.add(cidr_assoc["CidrBlock"])
    except Exception as e:
        logger.warning(f"Could not check existing VPCs: {e}")
    
    # Find first available CIDR
    for cidr in candidate_cidrs:
        if cidr not in existing_cidrs:
            logger.info(f"Using CIDR block: {cidr}")
            return cidr
    
    # Fallback - this should rarely happen
    logger.warning("All candidate CIDR blocks are in use, using 10.25.0.0/16")
    return "10.25.0.0/16"


def get_or_create_internet_gateway(vpc_id: str) -> str:
    """Get existing Internet Gateway or create a new one for the VPC."""
    igws = ec2_client.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
    )
    
    if igws["InternetGateways"]:
        igw_id = igws["InternetGateways"][0]["InternetGatewayId"]
        logger.debug(f"Found existing Internet Gateway: {igw_id}")
        return igw_id
    
    # Create Internet Gateway if it doesn't exist
    logger.info("  No Internet Gateway found. Creating Internet Gateway...")
    igw_response = ec2_client.create_internet_gateway(
        TagSpecifications=[
            {
                "ResourceType": "internet-gateway",
                "Tags": [{"Key": "Name", "Value": f"igw-{project_name}"}]
            }
        ]
    )
    igw_id = igw_response["InternetGateway"]["InternetGatewayId"]
    ec2_client.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
    logger.info(f"  Created and attached Internet Gateway: {igw_id}")
    return igw_id


def wait_for_nat_gateway(nat_gateway_id: str, log_interval: int = 6) -> None:
    """Wait for NAT Gateway to become available."""
    wait_count = 0
    while True:
        response = ec2_client.describe_nat_gateways(NatGatewayIds=[nat_gateway_id])
        state = response["NatGateways"][0]["State"]
        wait_count += 1
        if wait_count % log_interval == 0:
            logger.debug(f"  NAT Gateway status: {state} (waited {wait_count * 10} seconds)")
        if state == "available":
            break
        time.sleep(10)
    logger.debug(f"NAT Gateway is available: {nat_gateway_id}")


def get_or_create_nat_gateway(vpc_id: str, public_subnet_id: str) -> str:
    """Get existing NAT Gateway or create a new one in the public subnet."""
    # Check for existing NAT Gateway by VPC ID
    nat_gateways = ec2_client.describe_nat_gateways(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "state", "Values": ["available", "pending"]}
        ]
    )
    
    # Check if there's a NAT Gateway with our project name tag
    nat_gateway_id = None
    for nat_gw in nat_gateways.get("NatGateways", []):
        # Get tags for this NAT Gateway
        try:
            tags_response = ec2_client.describe_tags(
                Filters=[
                    {"Name": "resource-id", "Values": [nat_gw["NatGatewayId"]]},
                    {"Name": "resource-type", "Values": ["nat-gateway"]}
                ]
            )
            tags = {tag["Key"]: tag["Value"] for tag in tags_response.get("Tags", [])}
            
            # Check if it has our project name tag
            if tags.get("Name") == f"nat-{project_name}":
                nat_gateway_id = nat_gw["NatGatewayId"]
                logger.warning(f"  NAT Gateway already exists: {nat_gateway_id}")
                # Wait if it's still pending
                if nat_gw["State"] == "pending":
                    logger.info("  Waiting for existing NAT Gateway to be available...")
                    wait_for_nat_gateway(nat_gateway_id)
                return nat_gateway_id
        except Exception as e:
            logger.debug(f"  Could not check tags for NAT Gateway {nat_gw['NatGatewayId']}: {e}")
        
        # If no name tag match but there's an available NAT Gateway, use it
        if not nat_gateway_id and nat_gw["State"] == "available":
            nat_gateway_id = nat_gw["NatGatewayId"]
            logger.warning(f"  Found existing NAT Gateway: {nat_gateway_id}")
            return nat_gateway_id
    
    # Create NAT Gateway if it doesn't exist
    logger.info("  Allocating Elastic IP for NAT Gateway...")
    eip_response = ec2_client.allocate_address(Domain="vpc")
    eip_allocation_id = eip_response["AllocationId"]
    
    logger.info("  Creating NAT Gateway (this may take a few minutes)...")
    nat_response = ec2_client.create_nat_gateway(
        SubnetId=public_subnet_id,
        AllocationId=eip_allocation_id
    )
    nat_gateway_id = nat_response["NatGateway"]["NatGatewayId"]
    
    # Tag NAT Gateway
    ec2_client.create_tags(
        Resources=[nat_gateway_id],
        Tags=[{"Key": "Name", "Value": f"nat-{project_name}"}]
    )
    
    # Wait for NAT Gateway to be available
    logger.info("  Waiting for NAT Gateway to be available...")
    wait_for_nat_gateway(nat_gateway_id)
    
    return nat_gateway_id


def create_vpc() -> Dict[str, str]:
    """Create VPC with subnets and security groups."""
    logger.info("[5/9] Creating VPC and networking resources")
    
    vpc_name = f"vpc-for-{project_name}"
    cidr_block = get_available_cidr_block()
    
    # Check if VPC already exists
    vpcs = ec2_client.describe_vpcs(
        Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
    )
    if vpcs["Vpcs"]:
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        logger.warning(f"VPC already exists: {vpc_id}")
        
        try:
            # Get existing resources
            subnets = ec2_client.describe_subnets(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            public_subnets = []
            private_subnets = []
            for subnet in subnets["Subnets"]:
                subnet_name = ""
                for tag in subnet.get("Tags", []):
                    if tag["Key"] == "Name":
                        subnet_name = tag["Value"]
                        break
                
                if "public" in subnet_name.lower():
                    public_subnets.append(subnet["SubnetId"])
                elif "private" in subnet_name.lower():
                    private_subnets.append(subnet["SubnetId"])
                else:
                    # If no clear naming, use route table to determine
                    route_tables = ec2_client.describe_route_tables(
                        Filters=[{"Name": "association.subnet-id", "Values": [subnet["SubnetId"]]}]
                    )
                    is_public = False
                    for rt in route_tables["RouteTables"]:
                        for route in rt["Routes"]:
                            if route.get("GatewayId", "").startswith("igw-"):
                                is_public = True
                                break
                    
                    if is_public:
                        public_subnets.append(subnet["SubnetId"])
                    else:
                        private_subnets.append(subnet["SubnetId"])
            
            # If no private subnets found, create them automatically
            if not private_subnets:
                logger.info("  No private subnets found. Creating private subnets for EC2 deployment...")
                
                # Get VPC CIDR and availability zones
                vpc_detail = ec2_client.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]
                vpc_cidr = vpc_detail["CidrBlock"]
                
                # Get availability zones
                azs = ec2_client.describe_availability_zones()["AvailabilityZones"][:2]
                az_names = [az["ZoneName"] for az in azs]
                
                # Get existing subnet CIDRs to avoid conflicts
                existing_cidrs = set()
                for subnet in subnets["Subnets"]:
                    existing_cidrs.add(subnet["CidrBlock"])
                
                # Parse VPC CIDR to determine subnet CIDRs
                vpc_network = ipaddress.ip_network(vpc_cidr)
                base_octets = str(vpc_network.network_address).split('.')
                
                # Get NAT Gateway (create if needed)
                if not public_subnets:
                    raise ValueError(
                        "Cannot create private subnets without public subnets for NAT Gateway. "
                        "Please ensure your VPC has at least one public subnet."
                    )
                nat_gateway_id = get_or_create_nat_gateway(vpc_id, public_subnets[0])
                
                # Create private subnets
                for i, az in enumerate(az_names):
                    # Use offset +2 to avoid overlap with public subnets (0,1)
                    subnet_cidr = f"{base_octets[0]}.{base_octets[1]}.{i+2}.0/24"
                    
                    # Check if CIDR conflicts
                    if subnet_cidr in existing_cidrs:
                        # Try alternative offsets
                        for offset in range(10, 20):
                            alt_cidr = f"{base_octets[0]}.{base_octets[1]}.{offset}.0/24"
                            if alt_cidr not in existing_cidrs:
                                subnet_cidr = alt_cidr
                                break
                    
                    try:
                        subnet_response = ec2_client.create_subnet(
                            VpcId=vpc_id,
                            CidrBlock=subnet_cidr,
                            AvailabilityZone=az,
                            TagSpecifications=[
                                {
                                    "ResourceType": "subnet",
                                    "Tags": [
                                        {"Key": "Name", "Value": f"private-subnet-for-{project_name}-{i+1}"},
                                        {"Key": "aws-cdk:subnet-type", "Value": "Private"},
                                        {"Key": "aws-cdk:subnet-name", "Value": f"private-subnet-for-{project_name}"}
                                    ]
                                }
                            ]
                        )
                        new_subnet_id = subnet_response["Subnet"]["SubnetId"]
                        private_subnets.append(new_subnet_id)
                        logger.info(f"  Created private subnet: {new_subnet_id} in {az} with CIDR {subnet_cidr}")
                        
                        # Find or create private route table
                        route_tables = ec2_client.describe_route_tables(
                            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                        )
                        private_rt_id = None
                        for rt in route_tables["RouteTables"]:
                            # Check if route table has NAT Gateway route
                            for route in rt["Routes"]:
                                if route.get("NatGatewayId") == nat_gateway_id:
                                    private_rt_id = rt["RouteTableId"]
                                    break
                            if private_rt_id:
                                break
                        
                        if not private_rt_id:
                            # Create private route table
                            private_rt_response = ec2_client.create_route_table(
                                VpcId=vpc_id,
                                TagSpecifications=[
                                    {
                                        "ResourceType": "route-table",
                                        "Tags": [{"Key": "Name", "Value": f"private-rt-{project_name}"}]
                                    }
                                ]
                            )
                            private_rt_id = private_rt_response["RouteTable"]["RouteTableId"]
                            ec2_client.create_route(
                                RouteTableId=private_rt_id,
                                DestinationCidrBlock="0.0.0.0/0",
                                NatGatewayId=nat_gateway_id
                            )
                            logger.info(f"  Created private route table: {private_rt_id}")
                        
                        # Associate subnet with private route table
                        ec2_client.associate_route_table(
                            RouteTableId=private_rt_id,
                            SubnetId=new_subnet_id
                        )
                        
                    except ClientError as e:
                        if e.response["Error"]["Code"] == "InvalidSubnet.Overlap":
                            logger.warning(f"  Subnet CIDR {subnet_cidr} overlaps, trying alternative...")
                            continue
                        else:
                            logger.error(f"  Failed to create private subnet: {e}")
                            raise
                
                if not private_subnets:
                    raise ValueError(
                        "Failed to create private subnets. "
                        "Please ensure your VPC has available CIDR space and try again."
                    )
                
                logger.info(f"  ✓ Created {len(private_subnets)} private subnet(s) for EC2 deployment")
            
            # Check if we need to create additional public subnets for ALB
            if len(public_subnets) < 2:
                logger.info(f"  Found only {len(public_subnets)} public subnet(s). Creating additional public subnets for ALB...")
                
                # Get VPC CIDR and availability zones
                vpc_detail = ec2_client.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]
                vpc_cidr = vpc_detail["CidrBlock"]
                
                # Get availability zones
                azs = ec2_client.describe_availability_zones()["AvailabilityZones"][:2]
                az_names = [az["ZoneName"] for az in azs]
                
                # Get existing subnet CIDRs to avoid conflicts
                existing_cidrs = set()
                for subnet in subnets["Subnets"]:
                    existing_cidrs.add(subnet["CidrBlock"])
                
                # Get or create Internet Gateway
                igw_id = get_or_create_internet_gateway(vpc_id)
                
                # Find or create public route table
                route_tables = ec2_client.describe_route_tables(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                public_rt_id = None
                for rt in route_tables["RouteTables"]:
                    for route in rt["Routes"]:
                        if route.get("GatewayId", "") == igw_id:
                            public_rt_id = rt["RouteTableId"]
                            break
                    if public_rt_id:
                        break
                
                if not public_rt_id and igw_id:
                    # Create public route table
                    public_rt_response = ec2_client.create_route_table(
                        VpcId=vpc_id,
                        TagSpecifications=[
                            {
                                "ResourceType": "route-table",
                                "Tags": [{"Key": "Name", "Value": f"public-rt-{project_name}"}]
                            }
                        ]
                    )
                    public_rt_id = public_rt_response["RouteTable"]["RouteTableId"]
                    ec2_client.create_route(
                        RouteTableId=public_rt_id,
                        DestinationCidrBlock="0.0.0.0/0",
                        GatewayId=igw_id
                    )
                    logger.info(f"  Created public route table: {public_rt_id}")
                
                # Parse VPC CIDR to determine subnet CIDRs
                vpc_network = ipaddress.ip_network(vpc_cidr)
                base_octets = str(vpc_network.network_address).split('.')
                
                # Create public subnets in different AZs
                for i, az in enumerate(az_names):
                    if len(public_subnets) >= 2:
                        break
                    
                    # Try different CIDR blocks starting from offset 0
                    for offset in range(20):  # Try up to 20 different offsets
                        try:
                            # Calculate subnet CIDR (using /24 subnets)
                            subnet_networks = list(vpc_network.subnets(new_prefix=24))
                            if offset < len(subnet_networks):
                                subnet_network = subnet_networks[offset]
                                subnet_cidr = str(subnet_network)
                                
                                if subnet_cidr not in existing_cidrs:
                                    subnet_response = ec2_client.create_subnet(
                                        VpcId=vpc_id,
                                        CidrBlock=subnet_cidr,
                                        AvailabilityZone=az,
                                        TagSpecifications=[
                                            {
                                                "ResourceType": "subnet",
                                                "Tags": [{"Key": "Name", "Value": f"public-subnet-for-{project_name}-{len(public_subnets)+1}"}]
                                            }
                                        ]
                                    )
                                    new_subnet_id = subnet_response["Subnet"]["SubnetId"]
                                    public_subnets.append(new_subnet_id)
                                    logger.info(f"  Created public subnet: {new_subnet_id} in {az} with CIDR {subnet_cidr}")
                                    
                                    # Associate with public route table
                                    if public_rt_id:
                                        ec2_client.associate_route_table(
                                            RouteTableId=public_rt_id,
                                            SubnetId=new_subnet_id
                                        )
                                    
                                    break
                        except (ClientError, ValueError) as e:
                            error_msg = str(e).lower()
                            if "already exists" not in error_msg and "overlaps" not in error_msg and "invalid" not in error_msg:
                                logger.debug(f"  Could not create subnet with offset {offset}: {e}")
                            continue
                
                if len(public_subnets) < 2:
                    raise ValueError(
                        f"Could not create enough public subnets. Found {len(public_subnets)} public subnet(s), "
                        f"but ALB requires at least 2 subnets in different availability zones. "
                        f"Please manually create additional public subnets or delete and recreate the VPC."
                    )
            
            # Check availability zones for public subnets
            if len(public_subnets) >= 2:
                subnet_details = ec2_client.describe_subnets(SubnetIds=public_subnets)
                azs = {subnet["AvailabilityZone"] for subnet in subnet_details["Subnets"]}
                if len(azs) < 2:
                    logger.warning(
                        f"  Warning: Public subnets are only in {len(azs)} availability zone(s): {azs}. "
                        f"ALB requires subnets in at least 2 different availability zones."
                    )
            
            # Get security groups
            sgs = ec2_client.describe_security_groups(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            alb_sg_id = None
            ec2_sg_id = None
            for sg in sgs["SecurityGroups"]:
                if sg["GroupName"] != "default":
                    for tag in sg.get("Tags", []):
                        if tag["Key"] == "Name":
                            if f"alb-sg-for-{project_name}" in tag["Value"]:
                                alb_sg_id = sg["GroupId"]
                            elif f"ec2-sg-for-{project_name}" in tag["Value"]:
                                ec2_sg_id = sg["GroupId"]
            
            # If security groups not found, create them
            if not alb_sg_id or not ec2_sg_id:
                logger.info("  Creating missing security groups...")
                if not alb_sg_id:
                    alb_sg_response = ec2_client.create_security_group(
                        GroupName=f"alb-sg-for-{project_name}",
                        Description="security group for alb",
                        VpcId=vpc_id,
                        TagSpecifications=[
                            {
                                "ResourceType": "security-group",
                                "Tags": [{"Key": "Name", "Value": f"alb-sg-for-{project_name}"}]
                            }
                        ]
                    )
                    alb_sg_id = alb_sg_response["GroupId"]
                    
                    # Allow HTTP traffic to ALB
                    ec2_client.authorize_security_group_ingress(
                        GroupId=alb_sg_id,
                        IpPermissions=[
                            {
                                "IpProtocol": "tcp",
                                "FromPort": 80,
                                "ToPort": 80,
                                "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
                            }
                        ]
                    )
                
                if not ec2_sg_id:
                    ec2_sg_response = ec2_client.create_security_group(
                        GroupName=f"ec2-sg-for-{project_name}",
                        Description="Security group for ec2",
                        VpcId=vpc_id,
                        TagSpecifications=[
                            {
                                "ResourceType": "security-group",
                                "Tags": [{"Key": "Name", "Value": f"ec2-sg-for-{project_name}"}]
                            }
                        ]
                    )
                    ec2_sg_id = ec2_sg_response["GroupId"]
                    
                    # Allow traffic from ALB to EC2 (port 8501)
                    ec2_client.authorize_security_group_ingress(
                        GroupId=ec2_sg_id,
                        IpPermissions=[
                            {
                                "IpProtocol": "tcp",
                                "FromPort": 8501,
                                "ToPort": 8501,
                                "UserIdGroupPairs": [{"GroupId": alb_sg_id}]
                            }
                        ]
                    )
            
            # Get VPC endpoint
            endpoints = ec2_client.describe_vpc_endpoints(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            vpc_endpoint_id = endpoints["VpcEndpoints"][0]["VpcEndpointId"] if endpoints["VpcEndpoints"] else None
            
            # Check and fix routing table for internet access
            logger.debug("Checking routing table for internet access")
            route_tables = ec2_client.describe_route_tables(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            
            # Find main route table and check for internet gateway route
            main_rt_id = None
            has_igw_route = False
            
            for rt in route_tables["RouteTables"]:
                for assoc in rt.get("Associations", []):
                    if assoc.get("Main", False):
                        main_rt_id = rt["RouteTableId"]
                        # Check if IGW route exists
                        for route in rt["Routes"]:
                            if route.get("DestinationCidrBlock") == "0.0.0.0/0" and route.get("GatewayId", "").startswith("igw-"):
                                has_igw_route = True
                                break
                        break
            
            # Check and create Internet Gateway if missing
            igw_id = get_or_create_internet_gateway(vpc_id)
            
            # Add IGW route if missing
            if main_rt_id and not has_igw_route and igw_id:
                try:
                    ec2_client.create_route(
                        RouteTableId=main_rt_id,
                        DestinationCidrBlock="0.0.0.0/0",
                        GatewayId=igw_id
                    )
                    logger.info(f"  Added internet gateway route to main route table: {main_rt_id}")
                except ClientError as e:
                    if e.response["Error"]["Code"] != "RouteAlreadyExists":
                        logger.warning(f"Failed to add IGW route: {e}")
            
            return {
                "vpc_id": vpc_id,
                "public_subnets": public_subnets,
                "private_subnets": private_subnets,
                "alb_sg_id": alb_sg_id,
                "ec2_sg_id": ec2_sg_id,
                "vpc_endpoint_id": vpc_endpoint_id
            }
        except Exception as e:
            # If there's an error processing existing VPC, log warning but still return what we have
            logger.warning(f"Error processing existing VPC {vpc_id}: {e}")
            logger.warning("Returning existing VPC with minimal configuration. Some resources may need manual setup.")
            
            # Try to get at least subnet information even if there was an error
            if 'public_subnets' not in locals() or not public_subnets:
                try:
                    subnets = ec2_client.describe_subnets(
                        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                    )
                    public_subnets = []
                    private_subnets = []
                    for subnet in subnets["Subnets"]:
                        subnet_name = ""
                        for tag in subnet.get("Tags", []):
                            if tag["Key"] == "Name":
                                subnet_name = tag["Value"]
                                break
                        
                        if "public" in subnet_name.lower():
                            public_subnets.append(subnet["SubnetId"])
                        elif "private" in subnet_name.lower():
                            private_subnets.append(subnet["SubnetId"])
                        else:
                            # If no clear naming, use route table to determine
                            try:
                                route_tables = ec2_client.describe_route_tables(
                                    Filters=[{"Name": "association.subnet-id", "Values": [subnet["SubnetId"]]}]
                                )
                                is_public = False
                                for rt in route_tables["RouteTables"]:
                                    for route in rt["Routes"]:
                                        if route.get("GatewayId", "").startswith("igw-"):
                                            is_public = True
                                            break
                                
                                if is_public:
                                    public_subnets.append(subnet["SubnetId"])
                                else:
                                    private_subnets.append(subnet["SubnetId"])
                            except:
                                # If we can't determine, assume private
                                private_subnets.append(subnet["SubnetId"])
                except Exception as subnet_error:
                    logger.warning(f"Could not retrieve subnet information: {subnet_error}")
                    public_subnets = public_subnets if 'public_subnets' in locals() else []
                    private_subnets = private_subnets if 'private_subnets' in locals() else []
            
            # Return minimal configuration with existing VPC
            return {
                "vpc_id": vpc_id,
                "public_subnets": public_subnets if 'public_subnets' in locals() else [],
                "private_subnets": private_subnets if 'private_subnets' in locals() else [],
                "alb_sg_id": alb_sg_id if 'alb_sg_id' in locals() else None,
                "ec2_sg_id": ec2_sg_id if 'ec2_sg_id' in locals() else None,
                "vpc_endpoint_id": vpc_endpoint_id if 'vpc_endpoint_id' in locals() else None
            }
    
    # No existing VPC found, create new one
    logger.info("No existing VPC found, creating new VPC...")
    
    # Create VPC
    logger.debug(f"Creating VPC: {vpc_name} with CIDR {cidr_block}")
    response = ec2_client.create_vpc(
        CidrBlock=cidr_block,
        TagSpecifications=[
            {
                "ResourceType": "vpc",
                "Tags": [{"Key": "Name", "Value": vpc_name}]
            }
        ]
    )
    vpc_id = response["Vpc"]["VpcId"]
    logger.debug(f"VPC created: {vpc_id}")
    
    # Enable DNS hostnames and DNS resolution
    logger.debug("Enabling DNS hostnames and DNS support")
    ec2_client.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
    ec2_client.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
    
    # Get availability zones
    logger.debug("Getting availability zones")
    azs = ec2_client.describe_availability_zones()["AvailabilityZones"][:2]
    az_names = [az["ZoneName"] for az in azs]
    logger.debug(f"Using availability zones: {az_names}")
    
    # Parse CIDR to get base network for subnet creation
    vpc_network = ipaddress.ip_network(cidr_block)
    base_octets = str(vpc_network.network_address).split('.')
    
    # Create Internet Gateway
    logger.debug("Creating Internet Gateway")
    igw_id = get_or_create_internet_gateway(vpc_id)
    
    # Create public subnets
    logger.debug("Creating public subnets")
    public_subnets = []
    for i, az in enumerate(az_names):
        subnet_cidr = f"{base_octets[0]}.{base_octets[1]}.{i}.0/24"
        subnet_response = ec2_client.create_subnet(
            VpcId=vpc_id,
            CidrBlock=subnet_cidr,
            AvailabilityZone=az,
            TagSpecifications=[
                {
                    "ResourceType": "subnet",
                    "Tags": [
                        {"Key": "Name", "Value": f"public-subnet-for-{project_name}-{i+1}"},
                        {"Key": "aws-cdk:subnet-type", "Value": "Public"},
                        {"Key": "aws-cdk:subnet-name", "Value": f"public-subnet-for-{project_name}"}
                    ]
                }
            ]
        )
        public_subnets.append(subnet_response["Subnet"]["SubnetId"])
        logger.debug(f"Created public subnet: {subnet_response['Subnet']['SubnetId']} in {az}")
        
        # Enable auto-assign public IP for public subnets
        ec2_client.modify_subnet_attribute(
            SubnetId=subnet_response["Subnet"]["SubnetId"],
            MapPublicIpOnLaunch={"Value": True}
        )
    
    # Create NAT Gateway in first public subnet
    logger.debug("Creating NAT Gateway")
    nat_gateway_id = get_or_create_nat_gateway(vpc_id, public_subnets[0])
    
    # Create private subnets
    logger.debug("Creating private subnets")
    private_subnets = []
    for i, az in enumerate(az_names):
        subnet_cidr = f"{base_octets[0]}.{base_octets[1]}.{i+2}.0/24"  # Use +2 to avoid overlap with public subnets (0,1)
        subnet_response = ec2_client.create_subnet(
            VpcId=vpc_id,
            CidrBlock=subnet_cidr,
            AvailabilityZone=az,
            TagSpecifications=[
                {
                    "ResourceType": "subnet",
                    "Tags": [
                        {"Key": "Name", "Value": f"private-subnet-for-{project_name}-{i+1}"},
                        {"Key": "aws-cdk:subnet-type", "Value": "Private"},
                        {"Key": "aws-cdk:subnet-name", "Value": f"private-subnet-for-{project_name}"}
                    ]
                }
            ]
        )
        private_subnets.append(subnet_response["Subnet"]["SubnetId"])
        logger.debug(f"Created private subnet: {subnet_response['Subnet']['SubnetId']} in {az}")
    
    # Create route tables
    logger.debug("Creating route tables")
    public_rt_response = ec2_client.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "route-table",
                "Tags": [{"Key": "Name", "Value": f"public-rt-{project_name}"}]
            }
        ]
    )
    public_rt_id = public_rt_response["RouteTable"]["RouteTableId"]
    
    # Add route to Internet Gateway
    ec2_client.create_route(
        RouteTableId=public_rt_id,
        DestinationCidrBlock="0.0.0.0/0",
        GatewayId=igw_id
    )
    
    # Associate public subnets with public route table
    for subnet_id in public_subnets:
        ec2_client.associate_route_table(
            RouteTableId=public_rt_id,
            SubnetId=subnet_id
        )
    
    private_rt_response = ec2_client.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "route-table",
                "Tags": [{"Key": "Name", "Value": f"private-rt-{project_name}"}]
            }
        ]
    )
    private_rt_id = private_rt_response["RouteTable"]["RouteTableId"]
    
    # Add route to NAT Gateway
    ec2_client.create_route(
        RouteTableId=private_rt_id,
        DestinationCidrBlock="0.0.0.0/0",
        NatGatewayId=nat_gateway_id
    )
    
    # Associate private subnets with private route table
    for subnet_id in private_subnets:
        ec2_client.associate_route_table(
            RouteTableId=private_rt_id,
            SubnetId=subnet_id
        )
    
    # Create security groups first (needed for VPC endpoints)
    logger.debug("Creating security groups")
    alb_sg_response = ec2_client.create_security_group(
        GroupName=f"alb-sg-for-{project_name}",
        Description="security group for alb",
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "security-group",
                "Tags": [{"Key": "Name", "Value": f"alb-sg-for-{project_name}"}]
            }
        ]
    )
    alb_sg_id = alb_sg_response["GroupId"]
    
    # Allow HTTP traffic to ALB
    ec2_client.authorize_security_group_ingress(
        GroupId=alb_sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 80,
                "ToPort": 80,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
            }
        ]
    )
    logger.debug(f"ALB security group created: {alb_sg_id}")
    
    ec2_sg_response = ec2_client.create_security_group(
        GroupName=f"ec2-sg-for-{project_name}",
        Description="Security group for ec2",
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "security-group",
                "Tags": [{"Key": "Name", "Value": f"ec2-sg-for-{project_name}"}]
            }
        ]
    )
    ec2_sg_id = ec2_sg_response["GroupId"]
    
    # Allow traffic from ALB to EC2 (port 8501)
    ec2_client.authorize_security_group_ingress(
        GroupId=ec2_sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 8501,
                "ToPort": 8501,
                "UserIdGroupPairs": [{"GroupId": alb_sg_id}]
            }
        ]
    )
    
    # Allow HTTPS traffic for VPC endpoints
    try:
        ec2_client.authorize_security_group_ingress(
            GroupId=ec2_sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "IpRanges": [{"CidrIp": cidr_block}]
                }
            ]
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
            logger.warning(f"Failed to add HTTPS rule: {e}")
    
    logger.debug(f"EC2 security group created: {ec2_sg_id}")
    
    # Create VPC endpoints for Bedrock and SSM
    logger.debug("Creating VPC endpoints")
    
    # Bedrock endpoint
    vpc_endpoint_response = ec2_client.create_vpc_endpoint(
        VpcId=vpc_id,
        ServiceName=f"com.amazonaws.{region}.bedrock-runtime",
        VpcEndpointType="Interface",
        SubnetIds=private_subnets,
        SecurityGroupIds=[ec2_sg_id],
        PrivateDnsEnabled=True,
        TagSpecifications=[
            {
                "ResourceType": "vpc-endpoint",
                "Tags": [{"Key": "Name", "Value": f"bedrock-endpoint-{project_name}"}]
            }
        ]
    )
    vpc_endpoint_id = vpc_endpoint_response["VpcEndpoint"]["VpcEndpointId"]
    
    # SSM endpoints for Session Manager
    ssm_endpoints = [
        f"com.amazonaws.{region}.ssm",
        f"com.amazonaws.{region}.ssmmessages", 
        f"com.amazonaws.{region}.ec2messages"
    ]
    
    for service in ssm_endpoints:
        try:
            ec2_client.create_vpc_endpoint(
                VpcId=vpc_id,
                ServiceName=service,
                VpcEndpointType="Interface",
                SubnetIds=private_subnets,
                SecurityGroupIds=[ec2_sg_id],
                PrivateDnsEnabled=True
            )
            logger.debug(f"Created VPC endpoint for {service}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "RouteAlreadyExists":
                logger.warning(f"Failed to create endpoint for {service}: {e}")
    
    logger.debug(f"VPC endpoints created")
    
    logger.info(f"✓ VPC created: {vpc_id}")
    
    return {
        "vpc_id": vpc_id,
        "public_subnets": public_subnets,
        "private_subnets": private_subnets,
        "alb_sg_id": alb_sg_id,
        "ec2_sg_id": ec2_sg_id,
        "vpc_endpoint_id": vpc_endpoint_id
    }


def create_alb(vpc_info: Dict[str, str]) -> Dict[str, str]:
    """Create Application Load Balancer."""
    logger.info("[6/9] Creating Application Load Balancer")
    alb_name = f"alb-for-{project_name}"
    
    # Check if ALB already exists
    try:
        albs = elbv2_client.describe_load_balancers(Names=[alb_name])
        if albs["LoadBalancers"]:
            alb = albs["LoadBalancers"][0]
            logger.warning(f"ALB already exists: {alb['DNSName']}")
            return {
                "arn": alb["LoadBalancerArn"],
                "dns": alb["DNSName"]
            }
    except ClientError as e:
        if e.response["Error"]["Code"] != "LoadBalancerNotFound":
            raise
    
    # Validate that we have at least 2 subnets in different availability zones
    public_subnets = vpc_info["public_subnets"]
    
    # If no public subnets provided, try to find them from VPC
    if not public_subnets:
        logger.warning("  No public subnets found in vpc_info. Attempting to find public subnets from VPC...")
        try:
            subnets = ec2_client.describe_subnets(
                Filters=[{"Name": "vpc-id", "Values": [vpc_info["vpc_id"]]}]
            )
            all_subnets = []
            public_subnets = []
            private_subnets = []
            
            for subnet in subnets["Subnets"]:
                subnet_name = ""
                for tag in subnet.get("Tags", []):
                    if tag["Key"] == "Name":
                        subnet_name = tag["Value"]
                        break
                
                subnet_info = {
                    "id": subnet["SubnetId"],
                    "name": subnet_name,
                    "az": subnet["AvailabilityZone"],
                    "cidr": subnet["CidrBlock"]
                }
                all_subnets.append(subnet_info)
                
                if "public" in subnet_name.lower():
                    public_subnets.append(subnet["SubnetId"])
                elif "private" in subnet_name.lower():
                    private_subnets.append(subnet["SubnetId"])
                else:
                    # Check route table to determine if public
                    try:
                        route_tables = ec2_client.describe_route_tables(
                            Filters=[{"Name": "association.subnet-id", "Values": [subnet["SubnetId"]]}]
                        )
                        is_public = False
                        for rt in route_tables["RouteTables"]:
                            for route in rt["Routes"]:
                                if route.get("GatewayId", "").startswith("igw-"):
                                    is_public = True
                                    public_subnets.append(subnet["SubnetId"])
                                    break
                            if is_public:
                                break
                        if not is_public:
                            private_subnets.append(subnet["SubnetId"])
                    except Exception as rt_error:
                        logger.debug(f"  Could not check route table for subnet {subnet['SubnetId']}: {rt_error}")
                        private_subnets.append(subnet["SubnetId"])
            
            # Log all subnets found for debugging
            if all_subnets:
                logger.info(f"  Found {len(all_subnets)} subnet(s) in VPC:")
                for subnet_info in all_subnets:
                    logger.info(f"    - {subnet_info['id']}: {subnet_info['name']} ({subnet_info['az']}, {subnet_info['cidr']})")
                logger.info(f"  Identified {len(public_subnets)} public subnet(s) and {len(private_subnets)} private subnet(s)")
            else:
                logger.warning(f"  No subnets found in VPC {vpc_info['vpc_id']}")
                
        except Exception as e:
            logger.error(f"  Could not retrieve subnets from VPC: {e}")
            raise
    
    # Create public subnets if we don't have enough
    if len(public_subnets) < 2:
        logger.info(f"  Found only {len(public_subnets)} public subnet(s). Creating additional public subnets for ALB...")
        
        vpc_id = vpc_info["vpc_id"]
        
        # Get VPC CIDR and availability zones
        vpc_detail = ec2_client.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]
        vpc_cidr = vpc_detail["CidrBlock"]
        
        # Get availability zones
        azs = ec2_client.describe_availability_zones()["AvailabilityZones"][:2]
        az_names = [az["ZoneName"] for az in azs]
        
        # Get existing subnet CIDRs to avoid conflicts
        existing_cidrs = set()
        subnets_response = ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        for subnet in subnets_response["Subnets"]:
            existing_cidrs.add(subnet["CidrBlock"])
        
        # Get or create Internet Gateway
        igw_id = get_or_create_internet_gateway(vpc_id)
        
        # Find or create public route table
        route_tables = ec2_client.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        public_rt_id = None
        for rt in route_tables["RouteTables"]:
            for route in rt["Routes"]:
                if route.get("GatewayId", "") == igw_id:
                    public_rt_id = rt["RouteTableId"]
                    break
            if public_rt_id:
                break
        
        if not public_rt_id and igw_id:
            # Create public route table
            public_rt_response = ec2_client.create_route_table(
                VpcId=vpc_id,
                TagSpecifications=[
                    {
                        "ResourceType": "route-table",
                        "Tags": [{"Key": "Name", "Value": f"public-rt-{project_name}"}]
                    }
                ]
            )
            public_rt_id = public_rt_response["RouteTable"]["RouteTableId"]
            ec2_client.create_route(
                RouteTableId=public_rt_id,
                DestinationCidrBlock="0.0.0.0/0",
                GatewayId=igw_id
            )
            logger.info(f"  Created public route table: {public_rt_id}")
        
        # Parse VPC CIDR to determine subnet CIDRs
        vpc_network = ipaddress.ip_network(vpc_cidr)
        
        # Create public subnets in different AZs
        for i, az in enumerate(az_names):
            if len(public_subnets) >= 2:
                break
            
            subnet_name = f"public-subnet-for-{project_name}-{len(public_subnets)+1}"
            
            # Check if subnet with this name already exists
            existing_subnet_names = set()
            for subnet in subnets_response["Subnets"]:
                for tag in subnet.get("Tags", []):
                    if tag["Key"] == "Name":
                        existing_subnet_names.add(tag["Value"])
                        break
            
            if subnet_name in existing_subnet_names:
                logger.info(f"  Subnet '{subnet_name}' already exists, skipping creation")
                # Find and add existing subnet to public_subnets list
                for subnet in subnets_response["Subnets"]:
                    for tag in subnet.get("Tags", []):
                        if tag["Key"] == "Name" and tag["Value"] == subnet_name:
                            public_subnets.append(subnet["SubnetId"])
                            logger.debug(f"  Found existing public subnet: {subnet['SubnetId']}")
                            break
                continue
            
            # Try different CIDR blocks starting from offset 0
            for offset in range(20):  # Try up to 20 different offsets
                try:
                    # Calculate subnet CIDR (using /24 subnets)
                    subnet_networks = list(vpc_network.subnets(new_prefix=24))
                    if offset < len(subnet_networks):
                        subnet_network = subnet_networks[offset]
                        subnet_cidr = str(subnet_network)
                        
                        if subnet_cidr not in existing_cidrs:
                            subnet_response = ec2_client.create_subnet(
                                VpcId=vpc_id,
                                CidrBlock=subnet_cidr,
                                AvailabilityZone=az,
                                TagSpecifications=[
                                    {
                                        "ResourceType": "subnet",
                                        "Tags": [
                                            {"Key": "Name", "Value": subnet_name},
                                            {"Key": "aws-cdk:subnet-type", "Value": "Public"},
                                            {"Key": "aws-cdk:subnet-name", "Value": f"public-subnet-for-{project_name}"}
                                        ]
                                    }
                                ]
                            )
                            new_subnet_id = subnet_response["Subnet"]["SubnetId"]
                            public_subnets.append(new_subnet_id)
                            logger.info(f"  Created public subnet: {new_subnet_id} in {az} with CIDR {subnet_cidr}")
                            
                            # Enable auto-assign public IP for public subnets
                            ec2_client.modify_subnet_attribute(
                                SubnetId=new_subnet_id,
                                MapPublicIpOnLaunch={"Value": True}
                            )
                            
                            # Associate with public route table
                            if public_rt_id:
                                ec2_client.associate_route_table(
                                    RouteTableId=public_rt_id,
                                    SubnetId=new_subnet_id
                                )
                            
                            # Update existing_cidrs to avoid conflicts in next iteration
                            existing_cidrs.add(subnet_cidr)
                            break
                except (ClientError, ValueError) as e:
                    error_msg = str(e).lower()
                    if "already exists" not in error_msg and "overlaps" not in error_msg and "invalid" not in error_msg:
                        logger.debug(f"  Could not create subnet with offset {offset}: {e}")
                    continue
        
        if len(public_subnets) < 2:
            error_msg = (
                f"Could not create enough public subnets. Found {len(public_subnets)} public subnet(s), "
                f"but ALB requires at least 2 subnets in different availability zones. "
                f"Please manually create additional public subnets or delete and recreate the VPC."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    # Check that subnets are in different availability zones
    subnet_details = ec2_client.describe_subnets(SubnetIds=public_subnets)
    azs = {subnet["AvailabilityZone"] for subnet in subnet_details["Subnets"]}
    if len(azs) < 2:
        raise ValueError(
            f"ALB requires subnets in at least 2 different availability zones. "
            f"Found subnets only in {len(azs)} availability zone(s): {azs}. "
            f"Please ensure your VPC has public subnets in at least 2 different availability zones."
        )
    
    # Ensure ALB security group exists
    alb_sg_id = vpc_info.get("alb_sg_id")
    if not alb_sg_id:
        logger.info("  ALB security group not found. Creating ALB security group...")
        vpc_id = vpc_info["vpc_id"]
        try:
            alb_sg_response = ec2_client.create_security_group(
                GroupName=f"alb-sg-for-{project_name}",
                Description="security group for alb",
                VpcId=vpc_id,
                TagSpecifications=[
                    {
                        "ResourceType": "security-group",
                        "Tags": [{"Key": "Name", "Value": f"alb-sg-for-{project_name}"}]
                    }
                ]
            )
            alb_sg_id = alb_sg_response["GroupId"]
            
            # Allow HTTP traffic to ALB
            ec2_client.authorize_security_group_ingress(
                GroupId=alb_sg_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 80,
                        "ToPort": 80,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
                    }
                ]
            )
            logger.info(f"  ✓ Created ALB security group: {alb_sg_id}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidGroup.Duplicate":
                # Security group already exists, try to find it
                sgs = ec2_client.describe_security_groups(
                    Filters=[
                        {"Name": "vpc-id", "Values": [vpc_id]},
                        {"Name": "group-name", "Values": [f"alb-sg-for-{project_name}"]}
                    ]
                )
                if sgs["SecurityGroups"]:
                    alb_sg_id = sgs["SecurityGroups"][0]["GroupId"]
                    logger.info(f"  Found existing ALB security group: {alb_sg_id}")
                else:
                    raise
            else:
                raise
    
    logger.debug(f"Creating ALB: {alb_name} with {len(public_subnets)} subnets in {len(azs)} availability zones")
    response = elbv2_client.create_load_balancer(
        Name=alb_name,
        Subnets=public_subnets,
        SecurityGroups=[alb_sg_id],
        Scheme="internet-facing",
        Type="application",
        Tags=[
            {"Key": "Name", "Value": alb_name}
        ]
    )
    
    alb_arn = response["LoadBalancers"][0]["LoadBalancerArn"]
    alb_dns = response["LoadBalancers"][0]["DNSName"]
    
    logger.info(f"✓ ALB created: {alb_dns}")
    
    return {
        "arn": alb_arn,
        "dns": alb_dns
    }


def create_lambda_role() -> str:
    """Create Lambda RAG IAM role."""
    logger.info("[2/9] Creating Lambda RAG IAM role")
    role_name = f"role-lambda-rag-for-{project_name}-{region}"
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": ["lambda.amazonaws.com", "bedrock.amazonaws.com"]
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    role_arn = create_iam_role(role_name, assume_role_policy)
    
    # Attach inline policies
    create_log_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup"],
                "Resource": [f"arn:aws:logs:{region}:{account_id}:*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"create-log-policy-lambda-rag-for-{project_name}", create_log_policy)
    
    create_log_stream_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [f"arn:aws:logs:{region}:{account_id}:log-group:/aws/lambda/*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"create-stream-log-policy-lambda-rag-for-{project_name}", create_log_stream_policy)
    
    bedrock_invoke_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["bedrock:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"tool-bedrock-invoke-policy-for-{project_name}", bedrock_invoke_policy)
    
    opensearch_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["aoss:APIAccessAll"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"tool-bedrock-agent-opensearch-policy-for-{project_name}", opensearch_policy)
    
    bedrock_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["bedrock:*"],
                "Resource": ["*"]
            }
        ]
    }
    attach_inline_policy(role_name, f"tool-bedrock-agent-bedrock-policy-for-{project_name}", bedrock_policy)
    
    return role_arn


def delete_knowledge_base(knowledge_base_id: str) -> None:
    """Delete Knowledge Base and its data sources."""
    bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)
    
    try:
        # Delete all data sources first
        try:
            data_sources = bedrock_agent_client.list_data_sources(
                knowledgeBaseId=knowledge_base_id,
                maxResults=100
            )
            for ds in data_sources.get("dataSourceSummaries", []):
                try:
                    bedrock_agent_client.delete_data_source(
                        knowledgeBaseId=knowledge_base_id,
                        dataSourceId=ds["dataSourceId"]
                    )
                    logger.debug(f"Deleted data source: {ds['dataSourceId']}")
                except Exception as e:
                    logger.warning(f"Failed to delete data source {ds['dataSourceId']}: {e}")
        except Exception as e:
            logger.debug(f"Error listing/deleting data sources: {e}")
        
        # Delete the knowledge base
        bedrock_agent_client.delete_knowledge_base(knowledgeBaseId=knowledge_base_id)
        logger.info(f"Deleted Knowledge Base: {knowledge_base_id}")
        
        # Wait for deletion to complete
        logger.debug("Waiting for Knowledge Base deletion to complete...")
        max_wait = 60  # Wait up to 60 seconds
        waited = 0
        while waited < max_wait:
            try:
                kb_response = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=knowledge_base_id)
                status = kb_response["knowledgeBase"]["status"]
                if status == "DELETED":
                    break
                time.sleep(5)
                waited += 5
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.debug("Knowledge Base deletion confirmed")
                    break
                raise
        
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.debug(f"Knowledge Base {knowledge_base_id} already deleted")
        else:
            logger.error(f"Failed to delete Knowledge Base {knowledge_base_id}: {e}")
            raise


def create_vector_index_in_opensearch(collection_endpoint: str, index_name: str) -> bool:
    """Create vector index in OpenSearch Serverless collection."""
    try:
        # Try to import required packages, install if missing
        try:
            import requests
            from requests_aws4auth import AWS4Auth
        except ImportError:
            logger.info("  Installing required packages for OpenSearch index creation...")
            import subprocess
            import sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "requests-aws4auth"])
            import requests
            from requests_aws4auth import AWS4Auth
        
        # Get AWS credentials
        session = boto3.Session()
        credentials = session.get_credentials()
        awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, region, 'aoss', session_token=credentials.token)
        
        # Check if index already exists
        url = f"{collection_endpoint}/{index_name}"
        response = requests.get(url, auth=awsauth, timeout=30)
        if response.status_code == 200:
            logger.debug(f"Vector index '{index_name}' already exists")
            return True
        
        # Index mapping for vector search
        index_mapping = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 512
                }
            },
            "mappings": {
                "properties": {
                    "vector_field": {
                        "type": "knn_vector",
                        "dimension": 1024,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "faiss",
                            "parameters": {
                                "ef_construction": 512,
                                "m": 16
                            }
                        }
                    },
                    "AMAZON_BEDROCK_TEXT": {
                        "type": "text"
                    },
                    "AMAZON_BEDROCK_METADATA": {
                        "type": "text"
                    }
                }
            }
        }
        
        # Create index
        headers = {"Content-Type": "application/json"}
        response = requests.put(
            url,
            auth=awsauth,
            headers=headers,
            data=json.dumps(index_mapping),
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            logger.info(f"  ✓ Vector index '{index_name}' created successfully")
            logger.info("  Waiting for index to be ready...")
            time.sleep(30)  # Wait for index to be ready
            return True
        else:
            logger.error(f"  Failed to create vector index: {response.status_code} - {response.text}")
            return False
            
    except ImportError:
        logger.error("  requests-aws4auth package is required. Install with: pip install requests-aws4auth")
        return False
    except Exception as e:
        logger.error(f"  Error creating vector index: {e}")
        return False


def create_knowledge_base_with_opensearch(opensearch_info: Dict[str, str], knowledge_base_role_arn: str, s3_bucket_name: str) -> str:
    """Create Knowledge Base with correct OpenSearch collection."""
    logger.info("[4.5/9] Creating Knowledge Base with OpenSearch collection")
    
    # Create vector index first
    logger.info("  Creating vector index in OpenSearch collection...")
    if not create_vector_index_in_opensearch(opensearch_info["endpoint"], vector_index_name):
        raise Exception("Failed to create vector index in OpenSearch collection")
    
    bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)
    
    # Check if Knowledge Base already exists
    try:
        logger.info("  Checking if Knowledge Base already exists...")
        kb_list = bedrock_agent_client.list_knowledge_bases()
        for kb in kb_list.get("knowledgeBaseSummaries", []):
            if kb["name"] == project_name:
                logger.warning(f"Knowledge Base already exists: {kb['knowledgeBaseId']}")
                
                # Verify it's using the correct OpenSearch collection
                kb_details = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=kb["knowledgeBaseId"])
                kb_collection_arn = kb_details["knowledgeBase"]["storageConfiguration"]["opensearchServerlessConfiguration"]["collectionArn"]
                
                if kb_collection_arn != opensearch_info["arn"]:
                    logger.warning(f"Knowledge Base is using wrong OpenSearch collection:")
                    logger.warning(f"  Current: {kb_collection_arn}")
                    logger.warning(f"  Expected: {opensearch_info['arn']}")

                    delete_knowledge_base(kb["knowledgeBaseId"])
                    break                    
                else:
                    logger.info(f"Knowledge Base is using correct OpenSearch collection")                
                    return kb["knowledgeBaseId"]
        logger.info("  Knowledge Base does not exist. Creating new one...")
    except Exception as e:
        logger.debug(f"Error checking existing Knowledge Base: {e}")
    
    # Create Knowledge Base
    logger.debug(f"Creating Knowledge Base with OpenSearch collection: {opensearch_info['arn']}")
    response = bedrock_agent_client.create_knowledge_base(
        name=project_name,
        description="Knowledge base based on OpenSearch",
        roleArn=knowledge_base_role_arn,
        tags={
            project_name: 'true'
        },
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0",
                "embeddingModelConfiguration": {
                    "bedrockEmbeddingModelConfiguration": {
                        "dimensions": 1024
                    }
                }
            }
        },
        storageConfiguration={
            "type": "OPENSEARCH_SERVERLESS",
            "opensearchServerlessConfiguration": {
                "collectionArn": opensearch_info["arn"],
                "fieldMapping": {
                    "metadataField": "AMAZON_BEDROCK_METADATA",
                    "textField": "AMAZON_BEDROCK_TEXT",
                    "vectorField": "vector_field"
                },
                "vectorIndexName": vector_index_name
            }
        }
    )
    
    knowledge_base_id = response["knowledgeBase"]["knowledgeBaseId"]
    logger.info(f"✓ Knowledge Base created: {knowledge_base_id}")
    
    # Wait for Knowledge Base to be active
    logger.info("  Waiting for Knowledge Base to be active...")
    while True:
        kb_response = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=knowledge_base_id)
        status = kb_response["knowledgeBase"]["status"]
        
        if status == "ACTIVE":
            logger.info("  Knowledge Base is now active")
            break
        elif status == "FAILED":
            raise Exception("Knowledge Base creation failed")
        
        logger.debug(f"  Knowledge Base status: {status} (waiting...)")
        time.sleep(10)
    
    # Create data source
    logger.info("  Creating data source...")
    data_source_response = bedrock_agent_client.create_data_source(
        knowledgeBaseId=knowledge_base_id,
        name=s3_bucket_name,
        description=f"S3 data source: {s3_bucket_name}",
        dataDeletionPolicy='RETAIN',
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{s3_bucket_name}",
                "inclusionPrefixes": ["docs/"]
            }
        },
        vectorIngestionConfiguration={
            "chunkingConfiguration": {
                "chunkingStrategy": "HIERARCHICAL",
                "hierarchicalChunkingConfiguration": {
                    "levelConfigurations": [
                        {"maxTokens": 1500},
                        {"maxTokens": 300}
                    ],
                    "overlapTokens": 60
                }
            },
            "parsingConfiguration": {
                "parsingStrategy": "BEDROCK_FOUNDATION_MODEL",
                "bedrockFoundationModelConfiguration": {
                    "modelArn": f"arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
                }
            }
        }
    )
    
    data_source_id = data_source_response["dataSource"]["dataSourceId"]
    logger.info(f"  ✓ Data source created: {data_source_id}")
    
    return knowledge_base_id


def create_agentcore_memory_role() -> str:
    """Create AgentCore Memory IAM role."""
    logger.info("[2/9] Creating AgentCore Memory IAM role")
    role_name = f"role-agentcore-memory-for-{project_name}-{region}"
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    role_arn = create_iam_role(role_name, assume_role_policy)
    
    memory_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:ListMemories",
                    "bedrock:CreateMemory",
                    "bedrock:DeleteMemory",
                    "bedrock:DescribeMemory",
                    "bedrock:UpdateMemory",
                    "bedrock:ListMemoryRecords",
                    "bedrock:CreateMemoryRecord",
                    "bedrock:DeleteMemoryRecord",
                    "bedrock:DescribeMemoryRecord",
                    "bedrock:UpdateMemoryRecord"
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/*",
                    "arn:aws:bedrock:*:*:inference-profile/*"
                ]
            }
        ]
    }
    attach_inline_policy(role_name, f"agentcore-memory-policy-for-{project_name}", memory_policy)
    
    return role_arn


def create_cloudfront_distribution(alb_info: Dict[str, str], s3_bucket_name: str) -> Dict[str, str]:
    """Create CloudFront distribution."""
    logger.info("[7/9] Creating CloudFront distribution")
    
    # Check if CloudFront distribution already exists
    try:
        distributions = cloudfront_client.list_distributions()
        for dist in distributions.get("DistributionList", {}).get("Items", []):
            if (f"CloudFront-for-{project_name}" in dist.get("Comment", "") and 
                dist.get("Enabled", False)):
                logger.warning(f"CloudFront distribution already exists: {dist['DomainName']}")
                return {
                    "id": dist["Id"],
                    "domain": dist["DomainName"]
                }
    except Exception as e:
        logger.debug(f"Error checking existing distributions: {e}")
    
    # Get existing CloudFront distribution configuration
    reference_distribution_id = "E13W1RC3R4P3U2"
    try:
        reference_config = cloudfront_client.get_distribution_config(Id=reference_distribution_id)
        existing_config = reference_config["DistributionConfig"]
        
        # Create new distribution config based on existing one
        distribution_config = {
            "CallerReference": f"{project_name}-{int(time.time())}",
            "Comment": f"CloudFront-for-{project_name}",
            "DefaultCacheBehavior": existing_config["DefaultCacheBehavior"].copy(),
            "Origins": {
                "Quantity": 2,
                "Items": [
                    {
                        "Id": f"alb-{project_name}",
                        "DomainName": alb_info["dns"],
                        "CustomOriginConfig": {
                            "HTTPPort": 80,
                            "HTTPSPort": 443,
                            "OriginProtocolPolicy": "http-only",
                            "OriginSslProtocols": {
                                "Quantity": 1,
                                "Items": ["TLSv1.2"]
                            }
                        },
                        "CustomHeaders": {
                            "Quantity": 1,
                            "Items": [
                                {
                                    "HeaderName": custom_header_name,
                                    "HeaderValue": custom_header_value
                                }
                            ]
                        }
                    },
                    {
                        "Id": f"s3-{project_name}",
                        "DomainName": f"{s3_bucket_name}.s3.{region}.amazonaws.com",
                        "S3OriginConfig": {
                            "OriginAccessIdentity": ""
                        }
                    }
                ]
            },
            "Enabled": True,
            "PriceClass": existing_config.get("PriceClass", "PriceClass_200")
        }
        
        # Update target origin ID
        distribution_config["DefaultCacheBehavior"]["TargetOriginId"] = f"alb-{project_name}"
        
    except Exception as e:
        logger.warning(f"Could not get reference distribution config: {e}")
        # Fallback to simple configuration
        distribution_config = {
            "CallerReference": f"{project_name}-{int(time.time())}",
            "Comment": f"CloudFront-for-{project_name}",
            "DefaultCacheBehavior": {
                "TargetOriginId": f"alb-{project_name}",
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": {
                    "Quantity": 7,
                    "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                    "CachedMethods": {
                        "Quantity": 2,
                        "Items": ["GET", "HEAD"]
                    }
                },
                "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
                "Compress": True
            },
            "Origins": {
                "Quantity": 1,
                "Items": [
                    {
                        "Id": f"alb-{project_name}",
                        "DomainName": alb_info["dns"],
                        "CustomOriginConfig": {
                            "HTTPPort": 80,
                            "HTTPSPort": 443,
                            "OriginProtocolPolicy": "http-only"
                        }
                    }
                ]
            },
            "Enabled": True,
            "PriceClass": "PriceClass_200"
        }
    
    try:
        response = cloudfront_client.create_distribution(DistributionConfig=distribution_config)
        distribution_id = response["Distribution"]["Id"]
        distribution_domain = response["Distribution"]["DomainName"]
        
        logger.info(f"✓ CloudFront distribution created: {distribution_domain}")
        logger.info(f"  Distribution ID: {distribution_id}")
        logger.warning("  Note: CloudFront distribution may take 15-20 minutes to deploy")
        return {
            "id": distribution_id,
            "domain": distribution_domain
        }
    except ClientError as e:
        logger.error(f"Error creating CloudFront distribution: {e}")
        raise


def get_setup_script(environment: Dict[str, str], git_name: str = "mcp") -> str:
    """Generate setup script for EC2 instance."""
    return f"""#!/bin/bash
exec > >(tee /var/log/user-data.log) 2>&1
set -x

# Update system
yum update -y

# Install packages
yum install -y git docker

# Start docker
systemctl start docker
systemctl enable docker
usermod -aG docker ssm-user

# Restart docker to ensure clean state
systemctl restart docker
sleep 10

# Create ssm-user home if not exists
mkdir -p /home/ssm-user
chown ssm-user:ssm-user /home/ssm-user

# Clone repository
cd /home/ssm-user
rm -rf {git_name}
git clone https://github.com/kyopark2014/{git_name}
chown -R ssm-user:ssm-user {git_name}

# Create config.json
mkdir -p /home/ssm-user/{git_name}/application
cat > /home/ssm-user/{git_name}/application/config.json << 'EOF'
{json.dumps(environment)}
EOF
chown -R ssm-user:ssm-user /home/ssm-user/{git_name}

# Build and run docker with volume mount for config.json
cd /home/ssm-user/{git_name}
docker build -f Dockerfile -t streamlit-app .
docker run -d --restart=always -p 8501:8501 -v $(pwd)/application/config.json:/app/application/config.json --name mcp-app streamlit-app

# Make update.sh executable for manual execution via SSM
chmod a+rx update.sh

echo "Setup completed successfully" >> /var/log/user-data.log
"""


def run_setup_script_via_ssm(instance_id: str, environment: Dict[str, str], git_name: str = "mcp") -> Dict[str, str]:
    """Run setup script on existing EC2 instance using SSM Run Command."""
    logger.info(f"Running setup script on EC2 instance {instance_id} via SSM")
    
    # Wait for SSM agent to be ready
    logger.debug("Waiting for SSM agent to be ready...")
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            response = ssm_client.describe_instance_information(
                Filters=[
                    {
                        "Key": "InstanceIds",
                        "Values": [instance_id]
                    }
                ]
            )
            if response.get("InstanceInformationList"):
                logger.debug("SSM agent is ready")
                break
        except Exception as e:
            logger.debug(f"SSM agent not ready yet (attempt {attempt + 1}/{max_attempts}): {e}")
        
        if attempt < max_attempts - 1:
            time.sleep(10)
        else:
            raise Exception(f"SSM agent not ready after {max_attempts * 10} seconds")
    
    # Get setup script
    script = get_setup_script(environment, git_name)
    
    # Run command via SSM
    try:
        logger.debug("Sending command via SSM Run Command...")
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": [script],
                "workingDirectory": ["/"]
            },
            TimeoutSeconds=3600,
            Comment=f"Setup script for {project_name}"
        )
        
        command_id = response["Command"]["CommandId"]
        logger.info(f"✓ Command sent via SSM: {command_id}")
        
        # Wait for command to complete
        logger.info("Waiting for command to complete (this may take several minutes)...")
        while True:
            time.sleep(10)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            status = result["Status"]
            
            if status in ["Success", "Failed", "Cancelled", "TimedOut"]:
                if status == "Success":
                    logger.info(f"✓ Setup script completed successfully")
                    logger.debug(f"Output: {result.get('StandardOutputContent', '')}")
                else:
                    error_output = result.get("StandardErrorContent", "")
                    logger.error(f"Setup script failed with status: {status}")
                    logger.error(f"Error output: {error_output}")
                    raise Exception(f"Setup script failed: {status}\n{error_output}")
                break
            
            logger.debug(f"Command status: {status} (waiting...)")
        
        return {
            "command_id": command_id,
            "status": status,
            "output": result.get("StandardOutputContent", ""),
            "error": result.get("StandardErrorContent", "")
        }
    
    except ClientError as e:
        logger.error(f"Failed to run setup script via SSM: {e}")
        raise


def create_ec2_instance(vpc_info: Dict[str, str], ec2_role_arn: str, 
                       knowledge_base_role_arn: str, opensearch_info: Dict[str, str],
                       s3_bucket_name: str, cloudfront_domain: str,
                       agentcore_memory_role_arn: str, knowledge_base_id: str) -> str:
    """Create EC2 instance."""
    logger.info("[8/9] Creating EC2 instance")
    
    instance_name = f"app-for-{project_name}"
    
    # Check if EC2 instance already exists
    try:
        instances = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [instance_name]},
                {"Name": "instance-state-name", "Values": ["running", "pending", "stopping", "stopped"]}
            ]
        )
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                logger.warning(f"EC2 instance already exists: {instance['InstanceId']}")
                return instance["InstanceId"]
    except Exception as e:
        logger.debug(f"No existing EC2 instance found: {e}")
    
    # Get latest Amazon Linux 2023 AMI
    logger.debug("Finding latest Amazon Linux 2023 AMI")
    amis = ec2_client.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": ["al2023-ami-*-x86_64"]},
            {"Name": "state", "Values": ["available"]}
        ]
    )
    latest_ami = sorted(amis["Images"], key=lambda x: x["CreationDate"], reverse=True)[0]
    ami_id = latest_ami["ImageId"]
    logger.debug(f"Using AMI: {ami_id}")
    
    # Prepare user data
    environment = {
        "projectName": project_name,
        "accountId": account_id,
        "region": region,
        "knowledge_base_id": knowledge_base_id,
        "knowledge_base_role": knowledge_base_role_arn,
        "collectionArn": opensearch_info["arn"],
        "opensearch_url": opensearch_info["endpoint"],
        "s3_bucket": s3_bucket_name,
        "s3_arn": f"arn:aws:s3:::{s3_bucket_name}",
        "sharing_url": f"https://{cloudfront_domain}",
        "agentcore_memory_role": agentcore_memory_role_arn
    }
    
    git_name = "mcp"
    user_data_script = get_setup_script(environment, git_name)
    
    # Get instance profile name
    instance_profile_name = f"instance-profile-{project_name}-{region}"
    
    # Create EC2 instance
    logger.debug(f"Launching EC2 instance: t3.medium in subnet {vpc_info['private_subnets'][0]}")
    response = ec2_client.run_instances(
        ImageId=ami_id,
        InstanceType="t3.medium",
        MinCount=1,
        MaxCount=1,
        IamInstanceProfile={"Name": instance_profile_name},
        UserData=base64.b64encode(user_data_script.encode('utf-8')).decode('utf-8'),
        NetworkInterfaces=[
            {
                "DeviceIndex": 0,
                "SubnetId": vpc_info["private_subnets"][0],
                "Groups": [vpc_info["ec2_sg_id"]],
                "AssociatePublicIpAddress": False,
                "DeleteOnTermination": True
            }
        ],
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/xvda",
                "Ebs": {
                    "VolumeSize": 80,
                    "DeleteOnTermination": True,
                    "Encrypted": True,
                    "VolumeType": "gp3"
                }
            }
        ],
        Monitoring={"Enabled": True},
        InstanceInitiatedShutdownBehavior="terminate",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": instance_name}]
            }
        ]
    )
    
    instance_id = response["Instances"][0]["InstanceId"]
    logger.info(f"✓ EC2 instance created: {instance_id}")
    logger.info(f"  Instance type: t3.medium")
    logger.info(f"  Deployed in private subnet: {vpc_info['private_subnets'][0]}")
    logger.info(f"  User data script configured for application deployment")
    
    return instance_id


def create_alb_target_group_and_listener(alb_info: Dict[str, str], instance_id: str, vpc_info: Dict[str, str]) -> Dict[str, str]:
    """Create ALB target group and listener."""
    logger.info("[9/9] Creating ALB target group and listener")
    
    target_port = 8501
    target_group_name = f"TG-for-{project_name}"
    
    # Check if target group already exists
    tg_arn = None
    try:
        tgs = elbv2_client.describe_target_groups(Names=[target_group_name])
        if tgs["TargetGroups"]:
            tg_arn = tgs["TargetGroups"][0]["TargetGroupArn"]
            logger.warning(f"  Target group already exists: {tg_arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "TargetGroupNotFound":
            logger.warning(f"  Error checking existing target group: {e}")
    
    # Create target group if it doesn't exist
    if not tg_arn:
        logger.debug(f"Creating target group on port {target_port}")
        try:
            tg_response = elbv2_client.create_target_group(
                Name=target_group_name,
                Protocol="HTTP",
                Port=target_port,
                VpcId=vpc_info["vpc_id"],
                HealthCheckProtocol="HTTP",
                HealthCheckPath="/",
                HealthCheckIntervalSeconds=30,
                HealthCheckTimeoutSeconds=5,
                HealthyThresholdCount=2,
                UnhealthyThresholdCount=3,
                TargetType="instance"
            )
            tg_arn = tg_response["TargetGroups"][0]["TargetGroupArn"]
            logger.debug(f"Target group created: {tg_arn}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "DuplicateTargetGroupName":
                # Try to get the existing target group again
                tgs = elbv2_client.describe_target_groups(Names=[target_group_name])
                if tgs["TargetGroups"]:
                    tg_arn = tgs["TargetGroups"][0]["TargetGroupArn"]
                    logger.warning(f"  Target group already exists: {tg_arn}")
            else:
                raise
    
    # Check if EC2 instance is already registered in target group
    instance_registered = False
    try:
        targets = elbv2_client.describe_target_health(TargetGroupArn=tg_arn)
        for target in targets.get("TargetHealthDescriptions", []):
            if target["Target"]["Id"] == instance_id and target["Target"]["Port"] == target_port:
                instance_registered = True
                logger.warning(f"  EC2 instance {instance_id} is already registered in target group")
                break
    except ClientError as e:
        logger.debug(f"  Error checking registered targets: {e}")
    
    # Register EC2 instance if not already registered
    if not instance_registered:
        logger.debug(f"Waiting for EC2 instance {instance_id} to be running...")
        waiter = ec2_client.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])
        
        logger.debug(f"Registering EC2 instance {instance_id} to target group")
        try:
            elbv2_client.register_targets(
                TargetGroupArn=tg_arn,
                Targets=[{"Id": instance_id, "Port": target_port}]
            )
            logger.info(f"  ✓ Registered EC2 instance {instance_id} to target group")
        except ClientError as e:
            if e.response["Error"]["Code"] == "DuplicateTarget":
                logger.warning(f"  EC2 instance {instance_id} is already registered in target group")
            else:
                raise
    
    # Check if listener already exists
    listener_arn = None
    try:
        listeners = elbv2_client.describe_listeners(LoadBalancerArn=alb_info["arn"])
        for listener in listeners.get("Listeners", []):
            if listener["Port"] == 80 and listener["Protocol"] == "HTTP":
                listener_arn = listener["ListenerArn"]
                logger.warning(f"  Listener already exists on port 80: {listener_arn}")
                break
    except ClientError as e:
        logger.warning(f"  Error checking existing listeners: {e}")
    
    # Create listener if it doesn't exist
    if not listener_arn:
        logger.debug("Creating ALB listener on port 80")
        try:
            listener_response = elbv2_client.create_listener(
                LoadBalancerArn=alb_info["arn"],
                Protocol="HTTP",
                Port=80,
                DefaultActions=[
                    {
                        "Type": "forward",
                        "TargetGroupArn": tg_arn
                    }
                ]
            )
            listener_arn = listener_response["Listeners"][0]["ListenerArn"]
            logger.debug(f"Listener created: {listener_arn}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "DuplicateListener":
                # Try to get the existing listener again
                listeners = elbv2_client.describe_listeners(LoadBalancerArn=alb_info["arn"])
                for listener in listeners.get("Listeners", []):
                    if listener["Port"] == 80 and listener["Protocol"] == "HTTP":
                        listener_arn = listener["ListenerArn"]
                        logger.warning(f"  Listener already exists on port 80: {listener_arn}")
                        break
            else:
                raise
    
    # Check if rule already exists for custom header
    rule_exists = False
    try:
        rules = elbv2_client.describe_rules(ListenerArn=listener_arn)
        for rule in rules.get("Rules", []):
            # Check if rule has Priority 10 and matches our custom header condition
            if rule.get("Priority") == "10":
                for condition in rule.get("Conditions", []):
                    if (condition.get("Field") == "http-header" and 
                        condition.get("HttpHeaderConfig", {}).get("HttpHeaderName") == custom_header_name):
                        rule_exists = True
                        logger.warning(f"  Rule with Priority 10 for custom header already exists: {rule['RuleArn']}")
                        break
                if rule_exists:
                    break
    except ClientError as e:
        logger.debug(f"  Error checking existing rules: {e}")
    
    # Add rule for custom header if it doesn't exist
    if not rule_exists:
        logger.debug("Creating rule for custom header")
        try:
            elbv2_client.create_rule(
                ListenerArn=listener_arn,
                Priority=10,
                Conditions=[
                    {
                        "Field": "http-header",
                        "HttpHeaderConfig": {
                            "HttpHeaderName": custom_header_name,
                            "Values": [custom_header_value]
                        }
                    }
                ],
                Actions=[
                    {
                        "Type": "forward",
                        "TargetGroupArn": tg_arn
                    }
                ]
            )
            logger.info(f"  ✓ Created rule for custom header")
        except ClientError as e:
            if e.response["Error"]["Code"] in ["PriorityInUse", "RuleAlreadyExists"]:
                logger.warning(f"  Rule with Priority 10 already exists")
            else:
                raise
    
    logger.info(f"✓ ALB target group and listener created")
    logger.info(f"  Target group: {tg_arn}")
    logger.info(f"  Listener: {listener_arn}")
    
    return {
        "target_group_arn": tg_arn,
        "listener_arn": listener_arn
    }


def run_setup_on_existing_instance(instance_id: Optional[str] = None):
    """Run setup script on existing EC2 instance via SSM."""
    instance_name = f"app-for-{project_name}"
    
    # Find instance if not provided
    if not instance_id:
        logger.info(f"Finding EC2 instance with name: {instance_name}")
        instances = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [instance_name]},
                {"Name": "instance-state-name", "Values": ["running"]}
            ]
        )
        
        found_instance = None
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                found_instance = instance["InstanceId"]
                break
        
        if not found_instance:
            raise Exception(f"No running EC2 instance found with name: {instance_name}")
        
        instance_id = found_instance
        logger.info(f"Found instance: {instance_id}")
    
    # Get infrastructure info from config or describe resources
    logger.info("Gathering infrastructure information...")
    
    # Try to read from config.json first
    config_path = "application/config.json"
    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)
            environment = {
                "projectName": config_data.get("projectName", project_name),
                "accountId": config_data.get("accountId", account_id),
                "region": config_data.get("region", region),
                "knowledge_base_role": config_data.get("knowledge_base_role", ""),
                "collectionArn": config_data.get("collectionArn", ""),
                "opensearch_url": config_data.get("opensearch_url", ""),
                "s3_bucket": config_data.get("s3_bucket", ""),
                "s3_arn": config_data.get("s3_arn", ""),
                "sharing_url": config_data.get("sharing_url", ""),
                "agentcore_memory_role": config_data.get("agentcore_memory_role", "")
            }
            logger.info("Using configuration from config.json")
    except Exception as e:
        logger.warning(f"Could not read config.json: {e}")
        logger.info("Using default configuration")
        environment = {
            "projectName": project_name,
            "accountId": account_id,
            "region": region,
            "knowledge_base_role": "",
            "collectionArn": "",
            "opensearch_url": "",
            "s3_bucket": "",
            "s3_arn": "",
            "sharing_url": "",
            "agentcore_memory_role": ""
        }
    
    # Run setup script via SSM
    result = run_setup_script_via_ssm(instance_id, environment)
    
    logger.info("="*60)
    logger.info("Setup Script Execution Completed")
    logger.info("="*60)
    logger.info(f"Instance ID: {instance_id}")
    logger.info(f"Command ID: {result['command_id']}")
    logger.info(f"Status: {result['status']}")
    if result.get('output'):
        logger.info(f"Output: {result['output'][:500]}...")  # First 500 chars
    logger.info("="*60)
    
    return result


def verify_ec2_subnet_deployment():
    """Verify that existing EC2 instances are deployed in private subnets."""
    logger.info("Verifying EC2 subnet deployment...")
    
    instance_name = f"app-for-{project_name}"
    
    try:
        instances = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [instance_name]},
                {"Name": "instance-state-name", "Values": ["running", "pending", "stopping", "stopped"]}
            ]
        )
        
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                instance_id = instance["InstanceId"]
                subnet_id = instance["SubnetId"]
                has_public_ip = instance.get("PublicIpAddress") is not None
                
                # Check subnet type
                subnet_details = ec2_client.describe_subnets(SubnetIds=[subnet_id])
                subnet = subnet_details["Subnets"][0]
                
                # Determine if subnet is private or public
                is_private_subnet = False
                for tag in subnet.get("Tags", []):
                    if tag["Key"] == "aws-cdk:subnet-type" and tag["Value"] == "Private":
                        is_private_subnet = True
                        break
                
                # If no explicit tag, check route table for internet gateway
                if not is_private_subnet:
                    route_tables = ec2_client.describe_route_tables(
                        Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
                    )
                    for rt in route_tables["RouteTables"]:
                        for route in rt["Routes"]:
                            if route.get("GatewayId", "").startswith("igw-") and route.get("DestinationCidrBlock") == "0.0.0.0/0":
                                # This subnet has direct internet gateway route, so it's public
                                break
                        else:
                            continue
                        break
                    else:
                        # No direct internet gateway route found, likely private
                        is_private_subnet = True
                
                logger.info(f"  Instance {instance_id}:")
                logger.info(f"    Subnet: {subnet_id} ({subnet['CidrBlock']})")
                logger.info(f"    Subnet Type: {'Private' if is_private_subnet else 'Public'}")
                logger.info(f"    Has Public IP: {has_public_ip}")
                logger.info(f"    Private IP: {instance['PrivateIpAddress']}")
                
                if is_private_subnet and not has_public_ip:
                    logger.info(f"    ✓ Correctly deployed in private subnet")
                elif not is_private_subnet:
                    logger.warning(f"    WARNING: Instance is deployed in a PUBLIC subnet!")
                    logger.warning(f"    This is not recommended for production environments.")
                elif has_public_ip:
                    logger.warning(f"    WARNING: Instance has a public IP address!")
                
    except Exception as e:
        logger.debug(f"Could not verify EC2 deployment: {e}")


def main():
    """Main function to create all infrastructure."""
    parser = argparse.ArgumentParser(description="AWS Infrastructure Installer")
    parser.add_argument(
        "--run-setup",
        metavar="INSTANCE_ID",
        nargs="?",
        const="",
        help="Run setup script on existing EC2 instance via SSM. If INSTANCE_ID is not provided, will find instance by name."
    )
    parser.add_argument(
        "--verify-deployment",
        action="store_true",
        help="Verify that existing EC2 instances are properly deployed in private subnets"
    )
    
    args = parser.parse_args()
    
    # If --run-setup flag is provided, run setup script via SSM
    if args.run_setup is not None:
        instance_id = args.run_setup if args.run_setup else None
        run_setup_on_existing_instance(instance_id)
        return
    
    # If --verify-deployment flag is provided, verify EC2 subnet deployment
    if args.verify_deployment:
        verify_ec2_subnet_deployment()
        return
    
    logger.info("="*60)
    logger.info("Starting AWS Infrastructure Deployment")
    logger.info("="*60)
    logger.info(f"Project: {project_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Account ID: {account_id}")
    logger.info(f"Bucket Name: {bucket_name}")
    logger.info("="*60)
    
    start_time = time.time()
    
    try:
        # 1. Create S3 bucket
        s3_bucket_name = create_s3_bucket()
        
        # 2. Create IAM roles
        knowledge_base_role_arn = create_knowledge_base_role()
        agent_role_arn = create_agent_role()
        ec2_role_arn = create_ec2_role(knowledge_base_role_arn)
        lambda_role_arn = create_lambda_role()
        agentcore_memory_role_arn = create_agentcore_memory_role()
        
        # 3. Create secrets
        secret_arns = create_secrets()
        
        # 4. Create OpenSearch collection (with EC2 and Knowledge Base roles for data access)
        opensearch_info = create_opensearch_collection(ec2_role_arn, knowledge_base_role_arn)
        logger.info(f"OpenSearch collection created: {opensearch_info}")
        
        # 4.5. Create Knowledge Base with correct OpenSearch collection        
        knowledge_base_id = create_knowledge_base_with_opensearch(opensearch_info, knowledge_base_role_arn, s3_bucket_name)
        
        # 5. Create VPC
        vpc_info = create_vpc()
        
        # 6. Create ALB
        alb_info = create_alb(vpc_info)
        
        # 7. Create CloudFront distribution
        cloudfront_info = create_cloudfront_distribution(alb_info, s3_bucket_name)
        
        # 8. Create EC2 instance
        instance_id = create_ec2_instance(
            vpc_info, ec2_role_arn, knowledge_base_role_arn,
            opensearch_info, s3_bucket_name, cloudfront_info["domain"],
            agentcore_memory_role_arn, knowledge_base_id
        )
        
        # 9. Create ALB target group and listener
        alb_listener_info = create_alb_target_group_and_listener(alb_info, instance_id, vpc_info)
        
        # Output summary
        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("="*60)
        logger.info("Infrastructure Deployment Completed Successfully!")
        logger.info("="*60)
        logger.info("Summary:")
        logger.info(f"  S3 Bucket: {s3_bucket_name}")
        logger.info(f"  VPC ID: {vpc_info['vpc_id']}")
        logger.info(f"  Public Subnets: {', '.join(vpc_info['public_subnets'])}")
        logger.info(f"  Private Subnets: {', '.join(vpc_info['private_subnets'])}")
        logger.info(f"  ALB DNS: http://{alb_info['dns']}/")
        logger.info(f"  CloudFront Domain: https://{cloudfront_info['domain']}")
        logger.info(f"  EC2 Instance ID: {instance_id} (deployed in private subnet)")
        logger.info(f"  OpenSearch Endpoint: {opensearch_info['endpoint']}")
        logger.info(f"  Knowledge Base ID: {knowledge_base_id}")
        logger.info(f"  Knowledge Base Role: {knowledge_base_role_arn}")
        logger.info(f"  AgentCore Memory Role: {agentcore_memory_role_arn}")
        logger.info("")
        logger.info(f"Total deployment time: {elapsed_time/60:.2f} minutes")
        logger.info("="*60)
        logger.info("Note: CloudFront distribution may take 15-20 minutes to fully deploy")
        logger.info("Note: EC2 instance user data script will install and start the application")
        logger.info("="*60)
        
        # Update application/config.json
        config_path = "application/config.json"
        config_data = {}
        
        # Read existing config if it exists
        try:
            with open(config_path, 'r') as f:
                config_data = json.load(f)
        except FileNotFoundError:
            logger.info(f"Creating new {config_path}")
        except Exception as e:
            logger.warning(f"Could not read existing {config_path}: {e}")
        
        # Update only necessary fields
        config_data.update({
            "projectName": project_name,
            "accountId": account_id,
            "region": region,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_role": knowledge_base_role_arn,
            "collectionArn": opensearch_info["arn"],
            "opensearch_url": opensearch_info["endpoint"],
            "s3_bucket": s3_bucket_name,
            "s3_arn": f"arn:aws:s3:::{s3_bucket_name}",
            "sharing_url": f"https://{cloudfront_info['domain']}",
            "agentcore_memory_role": agentcore_memory_role_arn
        })
        
        # Log the OpenSearch collection ARN for verification
        logger.info(f"OpenSearch Collection ARN: {opensearch_info['arn']}")
        logger.info(f"OpenSearch Collection Endpoint: {opensearch_info['endpoint']}")
        
        try:
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            logger.info(f"✓ Updated {config_path}")
        except Exception as e:
            logger.warning(f"Could not update {config_path}: {e}")
        
        logger.info("="*60)
        logger.info("")
        logger.info("="*60)
        logger.info("  IMPORTANT: CloudFront Domain Address")
        logger.info("="*60)
        logger.info(f" CloudFront URL: https://{cloudfront_info['domain']}")
        logger.info("")
        logger.info("Note: CloudFront distribution and agent application on EC2 instance may take 15-20 minutes to fully deploy")
        logger.info("      Once deployed, you can access your application at the URL above")
        logger.info("="*60)
        logger.info("")
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("")
        logger.error("="*60)
        logger.error("Deployment Failed!")
        logger.error("="*60)
        logger.error(f"Error: {e}")
        logger.error(f"Deployment time before failure: {elapsed_time/60:.2f} minutes")
        logger.error("="*60)
        import traceback
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()

