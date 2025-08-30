import os
import boto3
import requests
import time
from botocore.exceptions import ClientError
import json

def load_config():
    config = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)    
    return config

config = load_config()
region = config['region']
client_id = config['cognito']['client_id']
user_pool_id = config['cognito']['user_pool_id']
lambda_function_name = config['lambda_function_name']

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
        cognito_config = config['cognito']
        region = cognito_config['region']
        client_id = cognito_config['client_id']
        username = cognito_config['test_username']
        password = cognito_config['test_password']
        
        # Create Cognito client
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

def create_gateway():
    secret_name = config['secret_name']
    bearer_token = get_bearer_token(secret_name)
    print(f"Bearer token from secret manager: {bearer_token[:100] if bearer_token else 'None'}...")

    if not bearer_token:    
        print("No bearer token found in secret manager, getting fresh bearer token from Cognito...")
        bearer_token = create_cognito_bearer_token(config)
        print(f"Bearer token from cognito: {bearer_token[:100] if bearer_token else 'None'}...")
        
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
    auth_config = {
        "customJWTAuthorizer": { 
            "allowedClients": [client_id],  
            "discoveryUrl": cognito_discovery_url
        }
    }

    name = config['projectName'] + '-kb-retriever-gateway'
    agentcore_gateway_iam_role = config['agentcore_gateway_iam_role']

    response = gateway_client.create_gateway(
        name=name,
        roleArn = agentcore_gateway_iam_role,
        protocolType='MCP',
        authorizerType='CUSTOM_JWT',
        authorizerConfiguration=auth_config, 
        description='AgentCore Gateway with AWS Lambda target for KB Retriever'
    )
    print(f"response: {response}")

    gatewayID = response["gatewayId"]
    gatewayURL = response["gatewayUrl"]
    print(f"Gateway ID: {gatewayID}")
    print(f"Gateway URL: {gatewayURL}")

    lambda_target_config = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_function_name, 
                "toolSchema": {
                    "inlinePayload": [
                        {
                            "name": "retrieve",
                            "description": "keyword to retrieve the knowledge base",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "orderId": {
                                        "type": "string"
                                    }
                                },
                                "required": ["orderId"]
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
    targetname='LambdaUsingSDK'
    response = gateway_client.create_gateway_target(
        gatewayIdentifier=gatewayID,
        name=targetname,
        description='Lambda Target using SDK',
        targetConfiguration=lambda_target_config,
        credentialProviderConfigurations=credential_config)

    print(f"response: {response}")

        