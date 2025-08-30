import os
import boto3
from botocore.exceptions import ClientError
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

cognito_config = config['cognito']
region = cognito_config['region']
client_id = cognito_config['client_id']
username = cognito_config['test_username']
password = cognito_config['test_password']
user_pool_id = config['cognito']['user_pool_id']

lambda_function_arn = config['lambda_function_arn']
if not lambda_function_arn:
    # get current folder name
    
    lambda_function_name = 'lambda-' + current_folder_name + '-for-' + config['projectName']

    # lambda list에서 lambda_function_name의 arn을 찾기
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
    secret_name = config['secret_name']
    bearer_token = get_bearer_token(secret_name)
    print(f"Bearer token from secret manager: {bearer_token if bearer_token else 'None'}")

    if not bearer_token:    
        print("No bearer token found in secret manager, getting fresh bearer token from Cognito...")
        bearer_token = create_cognito_bearer_token(config)
        print(f"Bearer token from cognito: {bearer_token if bearer_token else 'None'}")
        
        if bearer_token:
            secret_name = config['secret_name']
            save_bearer_token(secret_name, bearer_token)
        else:
            print("Failed to get bearer token from Cognito. Exiting.")
            return {}

    gateway_client = boto3.client('bedrock-agentcore-control', region_name = region)

    cognito_discovery_url = f'https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration'
    print(f"Cognito discovery URL: {cognito_discovery_url}")

    # CreateGateway with Cognito authorizer without CMK. Use the Cognito user pool created in the previous step
    gateway_client = boto3.client('bedrock-agentcore-control', region_name=region)

    gateway_name = config['projectName'] + '-kb-retriever'
    gateway_id = config['gateway_id']
    gateway_url = config['gateway_url']
    print(f"gateway_id: {gateway_id}, gateway_url: {gateway_url}")

    print("2. Getting or creating gateway...")
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
            description='AgentCore Gateway for KB Retriever'
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

    target_id = config.get('target_id', "")
    if not target_id:
        response = gateway_client.list_gateway_targets(
            gatewayIdentifier=gateway_id,
            maxResults=100
        )
        print(f"response: {response}")

        target_id = None
        for target in response['items']:
            if target['name'] == targetname:
                print(f"Target already exists: {targetname}, {target['targetId']}")
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
