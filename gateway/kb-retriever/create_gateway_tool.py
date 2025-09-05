import os
import boto3
import json
import zipfile
import time 

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

def load_config():
    config = None    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)    
    return config
config = load_config()

current_path = os.path.basename(script_dir)
current_folder_name = current_path.split('/')[-1]
targetname = current_folder_name
projectName = config.get('projectName')
region = config.get('region')
accountId = config.get('accountId')

def create_user_pool(user_pool_name: str):
    cognito_client = boto3.client('cognito-idp', region_name=region)   

    print("Creating new Cognito User Pool...")
    response = cognito_client.create_user_pool(
        PoolName=user_pool_name,
        Policies={
            'PasswordPolicy': {
                'MinimumLength': 8,
                'RequireUppercase': True,
                'RequireLowercase': True,
                'RequireNumbers': True,
                'RequireSymbols': False
            }
        },
        AutoVerifiedAttributes=['email'],
        UsernameAttributes=['email'],
        MfaConfiguration='OFF',
        AdminCreateUserConfig={
            'AllowAdminCreateUserOnly': True
        }
    )        
    user_pool_id = response['UserPool']['Id']
    
    return user_pool_id

def create_client(user_pool_id, client_name):
    cognito_client = boto3.client('cognito-idp', region_name=region)   

    response = cognito_client.create_user_pool_client(
            UserPoolId=user_pool_id,
            ClientName=client_name,
            GenerateSecret=False,
            ExplicitAuthFlows=[
                'ALLOW_USER_PASSWORD_AUTH',
                'ALLOW_REFRESH_TOKEN_AUTH'
            ]
        )        
    client_id = response['UserPoolClient']['ClientId']
    
    return client_id

def check_user(user_pool_id, username):
    cognito_idp_client = boto3.client('cognito-idp', region_name=region)
    try:
        response = cognito_idp_client.admin_get_user(
            UserPoolId=user_pool_id,
            Username=username
        )
        print(f"response: {response}")
        print(f"✓ User '{username}' already exists")        
        return True
    except cognito_idp_client.exceptions.UserNotFoundException:
        print(f"User '{username}' does not exist, creating...")
        return False
    
def create_user(user_pool_id, username, password):
    cognito_idp_client = boto3.client('cognito-idp', region_name=region)
    try:
        cognito_idp_client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=username,
            UserAttributes=[
                {
                    'Name': 'email',
                    'Value': username
                },
                {
                    'Name': 'email_verified',
                    'Value': 'true'
                }
            ],
            TemporaryPassword=password,
            MessageAction='SUPPRESS'  # Don't send welcome email
        )

        cognito_idp_client.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=username,
            Password=password,
            Permanent=True
        )
        print(f"✓ Password set for user '{username}'")
        return True
    except Exception as e:
        print(f"Warning: Could not set permanent password: {e}")
        print("User may need to change password on first login")
        return False
    
def get_cognito_config(cognito_config):    
    user_pool_name = cognito_config.get('user_pool_name')
    user_pool_id = cognito_config.get('user_pool_id')
    if not user_pool_name:        
        user_pool_name = projectName + '-agentcore-user-pool'
        print(f"No user pool name found in config, using default user pool name: {user_pool_name}")
        cognito_config.setdefault('user_pool_name', user_pool_name)

        cognito_client = boto3.client('cognito-idp', region_name=region)
        response = cognito_client.list_user_pools(MaxResults=60)
        for pool in response['UserPools']:
            if pool['Name'] == user_pool_name:
                user_pool_id = pool['Id']
                print(f"Found cognito user pool: {user_pool_id}")
                cognito_config['user_pool_id'] = user_pool_id
                break

        # create user pool if not exists
        if not user_pool_id: 
            user_pool_id = create_user_pool(user_pool_name)
            print(f"✓ User Pool created successfully: {user_pool_id}")
            cognito_config['user_pool_id'] = user_pool_id

    client_name = cognito_config.get('client_name')
    if not client_name:        
        client_name = f"{projectName}-agentcore-client"
        print(f"No client name found in config, using default client name: {client_name}")
        cognito_config['client_name'] = client_name

    client_id = cognito_config.get('client_id')
    if not client_id:
        response = cognito_client.list_user_pool_clients(UserPoolId=user_pool_id)
        for client in response['UserPoolClients']:
            if client['ClientName'] == client_name:
                client_id = client['ClientId']
                print(f"Found cognito client: {client_id}")
                cognito_config['client_id'] = client_id     
                break

        # create client if not exists
        if not client_id:
            client_id = create_client(user_pool_id, client_name)
            print(f"✓ Client created successfully: {client_id}")
            cognito_config['client_id'] = client_id
                   
    username = cognito_config.get('test_username')
    password = cognito_config.get('test_password')
    if not username or not password:
        print("No test username found in config, using default username and password. Please check config.json and update the test username and password.")
        username = f"{projectName}-test-user@example.com"
        password = "TestPassword123!"        
        cognito_config['test_username'] = username
        cognito_config['test_password'] = password
    
        if not check_user(user_pool_id, username):
            print(f"Creating test user in User Pool: {user_pool_id}")        
            create_user(user_pool_id, username, password)
        print(f"✓ User '{username}' created successfully")    

    return cognito_config

def create_lambda_function_policy(lambda_function_name):
    """Create IAM policy for Lambda function access"""
    
    policy_name = "LambdaFunctionPolicy"+"For"+lambda_function_name
    policy_description = f"Policy for accessing Lambda function endpoints"
    
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AmazonBedrockAgentCoreGatewayLambdaProd",
                "Effect": "Allow",
                "Action": [
                    "lambda:*"
                ],
                "Resource": f"arn:aws:lambda:{region}:{accountId}:function:*"
            },
            {
                "Sid": "GetGateway",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:*"
                ],
                "Resource": f"arn:aws:bedrock-agentcore:{region}:{accountId}:gateway/*"
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
            },
            {
                "Sid": "EC2Access",
                "Effect": "Allow",
                "Action": [
                    "ec2:*"
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

def get_knowledge_base_id(knowledgeBaseName: str):
    knowledgeBaseId = ""

    bedrock_agent_client = boto3.client("bedrock-agent")
    response = bedrock_agent_client.list_knowledge_bases()

    for knowledge_base in response["knowledgeBaseSummaries"]:
        if knowledge_base["name"] == knowledgeBaseName:
            knowledgeBaseId = knowledge_base["knowledgeBaseId"]
            break

    if not knowledgeBaseId:
        print(f"Knowledge base with name {knowledgeBaseName} not found")
        return None

    return knowledgeBaseId 

knowledge_base_id = config.get('knowledge_base_id', "")
if not knowledge_base_id:
    knowledge_base_id = get_knowledge_base_id(projectName)
    print(f"knowledge_base_id: {knowledge_base_id}")

    config['knowledge_base_id'] = knowledge_base_id
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"update knowledge_base_id to {knowledge_base_id} in config.json")

def create_dummpy_lambda_function(lambda_function_path: str):
    body = """import json
import boto3
import os

def lambda_handler(event, context):
    print(f"event: {event}")
    print(f"context: {context}")

    toolName = context.client_context.custom['bedrockAgentCoreToolName']
    print(f"context.client_context: {context.client_context}")
    print(f"Original toolName: {toolName}")
    
    delimiter = "___"
    if delimiter in toolName:
        toolName = toolName[toolName.index(delimiter) + len(delimiter):]
    print(f"Converted toolName: {toolName}")

    keyword = event.get('keyword')
    print(f"keyword: {keyword}")

    if toolName == 'retrieve':
        return {
            'statusCode': 200, 
            'body': f"{toolName} is supported"
        }
    else:
        return {
            'statusCode': 200, 
            'body': f"{toolName} is not supported"
        }"""
    
    with open(os.path.join(lambda_function_path, 'lambda_function.py'), 'w') as f:
        f.write(body)    

def create_trust_policy_for_lambda():
    """Create trust policy for Bedrock AgentCore"""
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": ["lambda.amazonaws.com", "bedrock.amazonaws.com"]
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
    
def create_lambda_function_role(lambda_function_name):
    """Create IAM role for Lambda function access"""
    
    role_name = "LambdaFunctionRole"+"For"+lambda_function_name
    policy_arn = create_lambda_function_policy(lambda_function_name)
    
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
            trust_policy = create_trust_policy_for_lambda()
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
            trust_policy = create_trust_policy_for_lambda()
            
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

# get config of cognito
cognito_config = config.get('cognito', {})
if not cognito_config:
    cognito_config = get_cognito_config(cognito_config)
    if 'cognito' not in config:
        config['cognito'] = {}
    config['cognito'].update(cognito_config)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

# load variables from cognito_config
client_id = cognito_config.get('client_id')
user_pool_id = cognito_config.get('user_pool_id')
username = cognito_config.get('test_username')
password = cognito_config.get('test_password')

def update_lambda_function_arn():
    # zip lambda
    lambda_function_name = 'lambda-' + current_folder_name + '-for-' + config['projectName']
    lambda_function_zip_path = os.path.join(script_dir, lambda_function_name, "lambda_function.zip")
    lambda_dir = os.path.join(script_dir, lambda_function_name)
    # Create zip with all files and folders recursively
    try:
        with zipfile.ZipFile(lambda_function_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:            
            for root, dirs, files in os.walk(lambda_dir):
                for file in files:
                    if file == 'lambda_function.zip':
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, lambda_dir)
                    zip_file.write(file_path, arcname)
        print(f"✓ Lambda function zip created successfully: {lambda_function_zip_path}")
    except Exception as e:
        print(f"Failed to create Lambda function zip: {e}")

        # initiate lambda_function.py
        lambda_function_path = os.path.join(script_dir, lambda_function_name)
        if not os.path.exists(lambda_function_path):
            print(f"Lambda function path not found, creating new lambda function path: {lambda_function_path}")
            os.makedirs(lambda_function_path)

            create_dummpy_lambda_function(lambda_function_path)
            print(f"✓ Lambda function path created successfully: {lambda_function_path}")

            with zipfile.ZipFile(lambda_function_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:     
                for root, dirs, files in os.walk(lambda_dir):
                    for file in files:
                        if file == 'lambda_function.zip':
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, lambda_dir)
                        zip_file.write(file_path, arcname)
            print(f"✓ Lambda function zip created successfully: {lambda_function_zip_path}")
        pass

    lambda_function_arn = config.get('lambda_function_arn')    
    lambda_client = boto3.client('lambda', region_name=region)
    
    need_update = True
    if not lambda_function_arn:        
        print(f"search lambda function name: {lambda_function_name}")
                
        response = lambda_client.list_functions()
        for function in response['Functions']:
            if function['FunctionName'] == lambda_function_name:
                lambda_function_arn = function['FunctionArn']
                print(f"Lambda function found: {lambda_function_arn}")
                break

        if not lambda_function_arn:
            print(f"Lambda function not found, creating new lambda function")
            # create lambda function role
            lambda_function_role = create_lambda_function_role(lambda_function_name)
            
            if not lambda_function_role:
                print(f"Failed to create IAM role for Lambda function: {lambda_function_name}")
                return None

            # create lambda function
            need_update = False
            try:
                # Set environment variables
                environment_variables = {}
                environment_variables['KNOWLEDGE_BASE_ID'] = config.get('knowledge_base_id', "")
                
                response = lambda_client.create_function(
                    FunctionName=lambda_function_name,
                    Runtime='python3.13',
                    Handler='lambda_function.lambda_handler',
                    Role=lambda_function_role,
                    Description=f'Lambda function for {lambda_function_name}',
                    Timeout=60,
                    Environment={
                        'Variables': environment_variables
                    },
                    Code={
                        'ZipFile': open(lambda_function_zip_path, 'rb').read()
                    }
                )
                lambda_function_arn = response['FunctionArn']
                print(f"✓ Lambda function created successfully: {lambda_function_arn}")

                print("Waiting for Lambda function code creation to complete...")
                time.sleep(5)
            except Exception as e:
                print(f"Failed to create Lambda function: {e}")
                return None
    
    if need_update:
        # update lambda code
        response = lambda_client.update_function_code(
            FunctionName=lambda_function_name,
            ZipFile=open(lambda_function_zip_path, 'rb').read()
        )
        lambda_function_arn = response['FunctionArn']
        print(f"✓ Lambda function code updated successfully: {lambda_function_arn}")
        
        # Wait for code update to complete before updating configuration
        print("Waiting for Lambda function code update to complete...")
        time.sleep(5)
        
        # update lambda configuration (timeout and environment variables)
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Set environment variables
                environment_variables = {}
                environment_variables['KNOWLEDGE_BASE_ID'] = config.get('knowledge_base_id', "")
                
                lambda_client.update_function_configuration(
                    FunctionName=lambda_function_name,
                    Timeout=60,
                    Environment={
                        'Variables': environment_variables
                    }
                )
                print(f"✓ Lambda function timeout and environment variables updated")
                break
            except Exception as e:
                retry_count += 1
                if "ResourceConflictException" in str(e) and retry_count < max_retries:
                    print(f"Lambda function is still updating, waiting 10 seconds before retry {retry_count}/{max_retries}...")
                    time.sleep(10)
                else:
                    print(f"Warning: Failed to update Lambda configuration after {retry_count} attempts: {e}")
                    break

    # update config
    if lambda_function_arn:
        config['lambda_function_arn'] = lambda_function_arn

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    return lambda_function_arn

def get_bearer_token(secret_name):
    try:
        session = boto3.Session()
        client = session.client('secretsmanager', region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        bearer_token_raw = response['SecretString']        
        token_data = json.loads(bearer_token_raw)  

        if 'bearer_token' in token_data:
            bearer_token = token_data['bearer_token']
            return bearer_token
        else:
            print("No bearer token found in secret manager")
            return None
    
    except Exception as e:
        print(f"Error getting stored token: {e}")
        return None

def create_cognito_bearer_token(config):
    """Get a fresh bearer token from Cognito"""
    try:
        client = boto3.client('cognito-idp', region_name=region)        
        # Authenticate and get tokens
        response = client.initiate_auth(
            ClientId=client_id,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password
            }
        )
        
        auth_result = response['AuthenticationResult']
        access_token = auth_result['AccessToken']
        # id_token = auth_result['IdToken']
        
        print("Successfully obtained fresh Cognito tokens")
        return access_token
        
    except Exception as e:
        print(f"Error getting Cognito token: {e}")
        return None

def save_bearer_token(secret_name, bearer_token):
    try:        
        session = boto3.Session()
        client = session.client('secretsmanager', region_name=region)
        
        # Create secret value with bearer_key 
        secret_value = {
            "bearer_key": "mcp_server_bearer_token",
            "bearer_token": bearer_token
        }
        
        # Convert to JSON string
        secret_string = json.dumps(secret_value)
        
        # Check if secret already exists
        try:
            client.describe_secret(SecretId=secret_name)
            # Secret exists, update it
            client.put_secret_value(
                SecretId=secret_name,
                SecretString=secret_string
            )
            print(f"Bearer token updated in secret manager with key: {secret_value['bearer_key']}")
        except client.exceptions.ResourceNotFoundException:
            # Secret doesn't exist, create it
            client.create_secret(
                Name=secret_name,
                SecretString=secret_string,
                Description="MCP Server Cognito credentials with bearer key and token"
            )
            print(f"Bearer token created in secret manager with key: {secret_value['bearer_key']}")
            
    except Exception as e:
        print(f"Error saving bearer token: {e}")
        # Continue execution even if saving fails

def main():
    print("1. Getting bearer token...")       
    secret_name = config.get('secret_name')
    if not secret_name:
        secret_name = f'{projectName.lower()}/credentials'
        print(f"No secret name found in config, using default secret name: {secret_name}")
        config['secret_name'] = secret_name
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    
    bearer_token = get_bearer_token(secret_name)
    print(f"Bearer token from secret manager: {bearer_token if bearer_token else 'None'}")

    if not bearer_token:    
        print("No bearer token found in secret manager, getting fresh bearer token from Cognito...")
        bearer_token = create_cognito_bearer_token(config)
        print(f"Bearer token from cognito: {bearer_token if bearer_token else 'None'}")
        
        if bearer_token:
            secret_name = config.get('secret_name')
            if secret_name:
                save_bearer_token(secret_name, bearer_token)
            else:
                print("Warning: No secret_name in config, cannot save bearer token")
        else:
            print("Failed to get bearer token from Cognito. Exiting.")
            return {}

    print("2. Getting or creating gateway...")
    gateway_client = boto3.client('bedrock-agentcore-control', region_name=region)
    
    cognito_discovery_url = f'https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration'
    print(f"Cognito discovery URL: {cognito_discovery_url}")

    gateway_name = config.get('gateway_name')
    if not gateway_name:
        gateway_name = config['projectName']
        print(f"No gateway name found in config, using default gateway name: {gateway_name}")
        config['gateway_name'] = gateway_name

    gateway_id = config.get('gateway_id')    
    if not gateway_id:
        response = gateway_client.list_gateways(maxResults=60)
        for gateway in response['items']:
            if gateway['name'] == gateway_name:
                print(f"gateway: {gateway}")
                gateway_id = gateway.get('gatewayId')
                config['gateway_id'] = gateway_id
                break
    
    gateway_url = config.get('gateway_url')
    if not gateway_url:
        gateway_url = f'https://{gateway_id}.gateway.bedrock-agentcore.{region}.amazonaws.com/mcp'
        print(f"gateway url: {gateway_url}")
        config['gateway_url'] = gateway_url

    # create gateway if not exists
    if not gateway_id or not gateway_url:
        print("Creating gateway...")
        agentcore_gateway_iam_role = config['agentcore_gateway_iam_role']
        auth_config = {
            "customJWTAuthorizer": { 
                "allowedClients": [client_id],  
                "discoveryUrl": cognito_discovery_url
            }
        }
        
        response = gateway_client.create_gateway(
            name=gateway_name,
            roleArn = agentcore_gateway_iam_role,
            protocolType='MCP',
            authorizerType='CUSTOM_JWT',
            authorizerConfiguration=auth_config, 
            description=f'AgentCore Gateway for {projectName}'
        )
        print(f"response: {response}")

        gateway_name = response["name"]
        gateway_id = response["gatewayId"]
        gateway_url = response["gatewayUrl"]

        config['gateway_name'] = gateway_name
        config['gateway_id'] = gateway_id
        config['gateway_url'] = gateway_url
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    print(f"Gateway ID: {gateway_id}")
    
    print("3. updating lambda function...")
    lambda_function_arn = update_lambda_function_arn()
    print(f"lambda_function_arn: {lambda_function_arn}")

    print("4. Getting or creating lambda target...")
    target_id = config.get('target_id', "")
    if not target_id:
        response = gateway_client.list_gateway_targets(
            gatewayIdentifier=gateway_id,
            maxResults=60
        )
        print(f"response: {response}")

        target_id = None
        for target in response['items']:
            if target['name'] == targetname:
                print(f"Target already exists.")
                target_id = target['targetId']
                break
        
        if not target_id:       
            TOOL_SPEC = json.load(open(os.path.join(script_dir, "tool_spec.json")))     
            print("Creating lambda target...")
            lambda_target_config = {
                "mcp": {
                    "lambda": {
                        "lambdaArn": lambda_function_arn, 
                        "toolSchema": {
                            "inlinePayload": [TOOL_SPEC]
                        }
                    }
                }
            }

            credential_config = [ 
                {
                    "credentialProviderType" : "GATEWAY_IAM_ROLE"
                }
            ]
            response = gateway_client.create_gateway_target(
                gatewayIdentifier=gateway_id,
                name=targetname,
                description=f'{targetname} for {projectName}',
                targetConfiguration=lambda_target_config,
                credentialProviderConfigurations=credential_config)
            print(f"response: {response}")

            target_id = response["targetId"]        
            config['target_name'] = targetname
            config['target_id'] = target_id
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

    print(f"target_name: {targetname}, target_id: {target_id}")

    print("\n=== Setup Summary ===")
    print(f"Gateway URL: {gateway_url}")
    print(f"Bearer Token: {bearer_token}")

    # save gateway_url
    config['gateway_url'] = gateway_url
    config['target_name'] = targetname
    config['target_id'] = target_id
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

if __name__ == "__main__":
    main()
