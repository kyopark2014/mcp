import os
import boto3
import json

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

def create_user_pool(user_pool_name):
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

lambda_function_arn = config.get('lambda_function_arn')
if not lambda_function_arn:
    lambda_function_name = 'lambda-' + current_folder_name + '-for-' + config['projectName']
    print(f"No lambda function arn found in config, using default lambda function name: {lambda_function_name}")
    
    lambda_client = boto3.client('lambda', region_name=region)
    response = lambda_client.list_functions()
    for function in response['Functions']:
        if function['FunctionName'] == lambda_function_name:
            lambda_function_arn = function['FunctionArn']
            print(f"Found lambda function: {lambda_function_arn}")
            break
    config['lambda_function_arn'] = lambda_function_arn

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

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
    
    print("3. Getting or creating lambda target...")

    target_id = config.get('target_id')
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
            print("Creating lambda target...")
            lambda_target_config = {
                "mcp": {
                    "lambda": {
                        "lambdaArn": lambda_function_arn, 
                        "toolSchema": {
                            "inlinePayload": [
                                {
                                    "name": "retrieve",
                                    "description": "keyword to retrieve the knowledge base",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "keyword": {
                                                "type": "string"
                                            }
                                        },
                                        "required": ["keyword"]
                                    }
                                }
                            ]
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
                description='Knowledge Base Retriever',
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
    config['target_id'] = target_id
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

if __name__ == "__main__":
    main()
