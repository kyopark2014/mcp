import boto3
import json
import os
from datetime import datetime

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

def load_config():
    config = None    

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)    
        return config
    except FileNotFoundError:
        print(f"Configuration file not found: {config_path}")
        return {}
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

config = load_config()

region = config.get('region')
accountId = config.get('accountId')
if accountId is None:
    session = boto3.Session()
    region = session.region_name
    
    # Get account ID using STS client
    sts_client = session.client('sts')
    accountId = sts_client.get_caller_identity()['Account']

    config['region'] = region
    config['accountId'] = accountId
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

projectName = config.get('projectName')
if not projectName:
    projectName = input("Enter project name: ")
    config['projectName'] = projectName
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        
agent_runtime_role_name = "BedrockAgentCoreMCPRole"+"For"+projectName

def create_bedrock_agentcore_policy():
    """Create IAM policy for Bedrock AgentCore MCP access"""
    
    policy_name = agent_runtime_role_name
    policy_description = f"Policy for accessing Bedrock AgentCore MCP endpoints"
    
    # Comprehensive policy document for Bedrock AgentCore MCP access
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockAgentAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:*"
                ],
                "Resource": [
                    "*"
                ]
            },
            {
                "Sid": "SecretsManagerAccess",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                    "secretsmanager:UpdateSecret"
                ],
                "Resource": [
                    f"arn:aws:secretsmanager:{region}:*:secret:{projectName}/cognito/credentials*"
                ]
            },
            {
                "Sid": "CognitoAccess",
                "Effect": "Allow",
                "Action": [
                    "cognito-idp:*"
                ],
                "Resource": "*"
            },
            {
                "Sid": "ECRAccess",
                "Effect": "Allow",
                "Action": [
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:DescribeRepositories",
                    "ecr:ListImages",
                    "ecr:DescribeImages"
                ],
                "Resource": "*"
            },
            {
                "Sid": "LogsAccess",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:*:log-group:/aws/bedrock-agentcore/*",
                    f"arn:aws:logs:{region}:*:log-group:/aws/bedrock-agentcore/*:log-stream:*"
                ]
            },
            {
                "Sid": "CloudWatchAccess",
                "Effect": "Allow",
                "Action": [
                    'cloudwatch:ListMetrics', 
                    'cloudwatch:GetMetricData',
                    'cloudwatch:GetMetricStatistics',
                    'cloudwatch:GetMetricWidgetImage',
                    'cloudwatch:GetMetricData',
                    'cloudwatch:GetMetricData',
                    'xray:PutTraceSegments',
                    'xray:PutTelemetryRecords',
                    'xray:PutAttributes',
                    'xray:GetTraceSummaries',
                    'logs:CreateLogGroup',
                    'logs:DescribeLogStreams', 
                    'logs:DescribeLogGroups', 
                    'logs:CreateLogStream', 
                    'logs:PutLogEvents'
                ],
                "Resource": "*"
            },
            {
                "Sid": "S3Access",
                "Effect": "Allow",
                "Action": [
                    "s3:*",
                    "bedrock:*"
                ],
                "Resource": "*"
            }
        ]
    }
    
    try:
        iam_client = boto3.client('iam')
        
        # Check if policy already exists
        try:
            existing_policy = iam_client.get_policy(PolicyArn=f"arn:aws:iam::{accountId}:policy/{policy_name}")
            print(f"Existing policy found: {existing_policy['Policy']['Arn']}")
            
            # List all policy versions
            versions_response = iam_client.list_policy_versions(PolicyArn=existing_policy['Policy']['Arn'])
            versions = versions_response['Versions']
            
            # If we have 5 versions, delete the oldest non-default version
            if len(versions) >= 5:
                print(f"Policy has {len(versions)} versions, cleaning up old versions...")
                
                # Find non-default versions to delete
                non_default_versions = [v for v in versions if not v['IsDefaultVersion']]
                
                if non_default_versions:
                    # Delete the oldest non-default version
                    oldest_version = non_default_versions[0]
                    iam_client.delete_policy_version(
                        PolicyArn=existing_policy['Policy']['Arn'],
                        VersionId=oldest_version['VersionId']
                    )
                    print(f"✓ Deleted old policy version: {oldest_version['VersionId']}")
                else:
                    # If all versions are default, we need to set a different version as default first
                    for version in versions[1:]:  # Skip the current default
                        try:
                            iam_client.set_default_policy_version(
                                PolicyArn=existing_policy['Policy']['Arn'],
                                VersionId=version['VersionId']
                            )
                            # Now delete the old default
                            iam_client.delete_policy_version(
                                PolicyArn=existing_policy['Policy']['Arn'],
                                VersionId=versions[0]['VersionId']
                            )
                            print(f"✓ Switched default version and deleted old version: {versions[0]['VersionId']}")
                            break
                        except Exception as e:
                            print(f"Failed to switch version {version['VersionId']}: {e}")
                            continue
            
            # Create policy version
            response = iam_client.create_policy_version(
                PolicyArn=existing_policy['Policy']['Arn'],
                PolicyDocument=json.dumps(policy_document),
                SetAsDefault=True
            )
            print(f"✓ Policy update completed: {response['PolicyVersion']['VersionId']}")
            return existing_policy['Policy']['Arn']
            
        except iam_client.exceptions.NoSuchEntityException:
            # Create new policy
            response = iam_client.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy_document),
                Description=policy_description
            )
            print(f"✓ New policy created: {response['Policy']['Arn']}")
            return response['Policy']['Arn']
            
    except Exception as e:
        print(f"Policy creation failed: {e}")
        return None

def attach_policy_to_role(role_name, policy_arn):
    """Attach policy to IAM role"""
    try:
        iam_client = boto3.client('iam')
        
        # Attach policy to role
        response = iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn=policy_arn
        )
        print(f"✓ Policy attached successfully: {policy_arn}")
        return True
        
    except Exception as e:
        print(f"Policy attachment failed: {e}")
        return False

def create_trust_policy_for_bedrock():
    """Create trust policy for Bedrock AgentCore"""
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            },
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::{accountId}:root"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    return trust_policy

def create_bedrock_agentcore_role():
    """Create IAM role for Bedrock AgentCore MCP access"""
    
    role_name = "BedrockAgentCoreMCPRole"+"For"+projectName
    policy_arn = create_bedrock_agentcore_policy()
    
    if not policy_arn:
        print("Role creation aborted due to policy creation failure")
        return None
    
    try:
        iam_client = boto3.client('iam')
        
        # Check if role already exists
        try:
            existing_role = iam_client.get_role(RoleName=role_name)
            print(f"Existing role found: {existing_role['Role']['Arn']}")
            
            # Update trust policy
            trust_policy = create_trust_policy_for_bedrock()
            iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(trust_policy)
            )
            print("✓ Trust policy updated successfully")
            
            # Attach policy
            attach_policy_to_role(role_name, policy_arn)
            
            return existing_role['Role']['Arn']
            
        except iam_client.exceptions.NoSuchEntityException:
            # Create new role
            trust_policy = create_trust_policy_for_bedrock()
            
            response = iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Role for Bedrock AgentCore MCP access"
            )
            print(f"✓ New role created: {response['Role']['Arn']}")
            
            # Attach policy
            attach_policy_to_role(role_name, policy_arn)
            
            return response['Role']['Arn']
            
    except Exception as e:
        print(f"Role creation failed: {e}")
        return None

def update_agentcore_config(role_arn):
    """Update AgentCore configuration"""
    
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        
        config['agent_runtime_role'] = role_arn
        print(f"✓ AgentCore configuration updated: {role_arn}")
        
        # Save configuration file
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)  
        
        print(f"✓ Configuration file updated: {config_path}")
        
    except FileNotFoundError:
        print(f"Configuration file not found: {config_path}")
    except Exception as e:
        print(f"Configuration update failed: {e}")

def main():
    print("=== AWS Bedrock AgentCore IAM Setup ===\n")
    
    # Create Bedrock AgentCore policy
    print("\n1. Creating Bedrock AgentCore policy...")
    policy_arn = create_bedrock_agentcore_policy()
    
    # Create Bedrock AgentCore role
    print("\n2. Creating Bedrock AgentCore role...")
    role_arn = create_bedrock_agentcore_role()
    
    # Update AgentCore configuration
    print("\n3. Updating AgentCore configuration...")
    update_agentcore_config(role_arn)
    
    print("\n=== Setup Complete ===")
    if role_arn:
        print(f"Created role ARN: {role_arn}")
    else:
        print("Role creation failed")

if __name__ == "__main__":
    main()