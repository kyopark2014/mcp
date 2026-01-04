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
from datetime import datetime
from typing import Dict, List, Optional
from botocore.exceptions import ClientError

# Configuration
project_name = "mcp"
region = os.environ.get("CDK_DEFAULT_REGION", "us-west-2")
account_id = os.environ.get("CDK_DEFAULT_ACCOUNT", "")
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
sts_client = boto3.client("sts", region_name=region)
ssm_client = boto3.client("ssm", region_name=region)

# Get account ID if not set
if not account_id:
    account_id = sts_client.get_caller_identity()["Account"]

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
        
        logger.info(f"✓ S3 bucket created successfully: {bucket_name}")
        return bucket_name
    
    except ClientError as e:
        if e.response["Error"]["Code"] in ["BucketAlreadyExists", "BucketAlreadyOwnedByYou"]:
            logger.warning(f"S3 bucket already exists: {bucket_name}")
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
        
        
        # Wait for collection to be active
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


def create_vpc() -> Dict[str, str]:
    """Create VPC with subnets and security groups."""
    logger.info("[5/9] Creating VPC and networking resources")
    
    vpc_name = f"vpc-for-{project_name}"
    cidr_block = "10.20.0.0/16"
    
    # Check if VPC already exists
    try:
        vpcs = ec2_client.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
        )
        if vpcs["Vpcs"]:
            vpc_id = vpcs["Vpcs"][0]["VpcId"]
            logger.warning(f"VPC already exists: {vpc_id}")
            
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
            
            # If no private subnets found, use public subnets
            if not private_subnets and public_subnets:
                private_subnets = public_subnets.copy()
                logger.warning("  No private subnets found, using public subnets for EC2")
            
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
            
            # Add IGW route if missing
            if main_rt_id and not has_igw_route:
                # Get Internet Gateway
                igws = ec2_client.describe_internet_gateways(
                    Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
                )
                if igws["InternetGateways"]:
                    igw_id = igws["InternetGateways"][0]["InternetGatewayId"]
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
        logger.debug(f"No existing VPC found, creating new one: {e}")
    
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
    
    # Create Internet Gateway
    logger.debug("Creating Internet Gateway")
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
    logger.debug(f"Internet Gateway created and attached: {igw_id}")
    
    # Create public subnets
    logger.debug("Creating public subnets")
    public_subnets = []
    for i, az in enumerate(az_names):
        subnet_cidr = f"10.20.{i}.0/24"
        subnet_response = ec2_client.create_subnet(
            VpcId=vpc_id,
            CidrBlock=subnet_cidr,
            AvailabilityZone=az,
            TagSpecifications=[
                {
                    "ResourceType": "subnet",
                    "Tags": [{"Key": "Name", "Value": f"public-subnet-for-{project_name}-{i+1}"}]
                }
            ]
        )
        public_subnets.append(subnet_response["Subnet"]["SubnetId"])
        logger.debug(f"Created public subnet: {subnet_response['Subnet']['SubnetId']} in {az}")
    
    # Create NAT Gateway in first public subnet
    logger.debug("Allocating Elastic IP for NAT Gateway")
    eip_response = ec2_client.allocate_address(Domain="vpc")
    eip_allocation_id = eip_response["AllocationId"]
    
    logger.debug("Creating NAT Gateway (this may take a few minutes)...")
    nat_response = ec2_client.create_nat_gateway(
        SubnetId=public_subnets[0],
        AllocationId=eip_allocation_id
    )
    nat_gateway_id = nat_response["NatGateway"]["NatGatewayId"]
    
    # Tag NAT Gateway after creation
    ec2_client.create_tags(
        Resources=[nat_gateway_id],
        Tags=[{"Key": "Name", "Value": f"nat-{project_name}"}]
    )
    
    # Wait for NAT Gateway to be available
    logger.info("  Waiting for NAT Gateway to be available (this may take a few minutes)...")
    wait_count = 0
    while True:
        response = ec2_client.describe_nat_gateways(NatGatewayIds=[nat_gateway_id])
        state = response["NatGateways"][0]["State"]
        wait_count += 1
        if wait_count % 6 == 0:  # Log every minute
            logger.debug(f"  NAT Gateway status: {state} (waited {wait_count * 10} seconds)")
        if state == "available":
            break
        time.sleep(10)
    logger.debug(f"NAT Gateway is available: {nat_gateway_id}")
    
    # Create private subnets
    logger.debug("Creating private subnets")
    private_subnets = []
    for i, az in enumerate(az_names):
        subnet_cidr = f"10.20.{i+10}.0/24"
        subnet_response = ec2_client.create_subnet(
            VpcId=vpc_id,
            CidrBlock=subnet_cidr,
            AvailabilityZone=az,
            TagSpecifications=[
                {
                    "ResourceType": "subnet",
                    "Tags": [{"Key": "Name", "Value": f"private-subnet-for-{project_name}-{i+1}"}]
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
    
    logger.debug(f"Creating ALB: {alb_name}")
    response = elbv2_client.create_load_balancer(
        Name=alb_name,
        Subnets=vpc_info["public_subnets"],
        SecurityGroups=[vpc_info["alb_sg_id"]],
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
                       agentcore_memory_role_arn: str) -> str:
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
    logger.info(f"  Instance type: m5.large")
    logger.info(f"  User data script configured for application deployment")
    
    return instance_id


def create_alb_target_group_and_listener(alb_info: Dict[str, str], instance_id: str, vpc_info: Dict[str, str]) -> Dict[str, str]:
    """Create ALB target group and listener."""
    logger.info("[9/9] Creating ALB target group and listener")
    
    target_port = 8501
    
    # Create target group
    logger.debug(f"Creating target group on port {target_port}")
    tg_response = elbv2_client.create_target_group(
        Name=f"TG-for-{project_name}",
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
    
    # Register EC2 instance
    logger.debug(f"Waiting for EC2 instance {instance_id} to be running...")
    waiter = ec2_client.get_waiter('instance_running')
    waiter.wait(InstanceIds=[instance_id])
    
    logger.debug(f"Registering EC2 instance {instance_id} to target group")
    elbv2_client.register_targets(
        TargetGroupArn=tg_arn,
        Targets=[{"Id": instance_id, "Port": target_port}]
    )
    
    # Create listener
    logger.debug("Creating ALB listener on port 80")
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
    
    # Add rule for custom header
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
    
    args = parser.parse_args()
    
    # If --run-setup flag is provided, run setup script via SSM
    if args.run_setup is not None:
        instance_id = args.run_setup if args.run_setup else None
        run_setup_on_existing_instance(instance_id)
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
            agentcore_memory_role_arn
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
        logger.info(f"  ALB DNS: http://{alb_info['dns']}/")
        logger.info(f"  CloudFront Domain: https://{cloudfront_info['domain']}")
        logger.info(f"  EC2 Instance ID: {instance_id}")
        logger.info(f"  OpenSearch Endpoint: {opensearch_info['endpoint']}")
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
            "knowledge_base_role": knowledge_base_role_arn,
            "collectionArn": opensearch_info["arn"],
            "opensearch_url": opensearch_info["endpoint"],
            "s3_bucket": s3_bucket_name,
            "s3_arn": f"arn:aws:s3:::{s3_bucket_name}",
            "sharing_url": f"https://{cloudfront_info['domain']}",
            "agentcore_memory_role": agentcore_memory_role_arn
        })
        
        try:
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            logger.info(f"✓ Updated {config_path}")
        except Exception as e:
            logger.warning(f"Could not update {config_path}: {e}")
        
        logger.info("="*60)
        logger.info("")
        logger.info("="*60)
        logger.info("⚠️  IMPORTANT: CloudFront Domain Address")
        logger.info("="*60)
        logger.info(f"🌐 CloudFront URL: https://{cloudfront_info['domain']}")
        logger.info("")
        logger.info("Note: CloudFront distribution may take 15-20 minutes to fully deploy")
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

