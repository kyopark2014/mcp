import boto3
import json
import os
import time
import jwt
from datetime import datetime, timedelta

accountId = boto3.client('sts').get_caller_identity()['Account']

def load_config():
    """Load configuration from config.json"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"Failed to load config.json: {e}")
        return None
    
config = load_config()
region = config['region']

def create_test_user():
    """Create a test user in Cognito User Pool"""
    try:
        user_pool_id = config['cognito']['user_pool_id']
        region = config['region']
        username = config['cognito']['test_username']
        password = config['cognito']['test_password']
        
        print(f"Creating test user in User Pool: {user_pool_id}")
        print(f"Username: {username}")
        print(f"Region: {region}")
        
        # Create Cognito Identity Provider client
        cognito_idp_client = boto3.client('cognito-idp', region_name=region)
        
        # Check if user already exists
        try:
            response = cognito_idp_client.admin_get_user(
                UserPoolId=user_pool_id,
                Username=username
            )
            print(f"✓ User '{username}' already exists")
            return True
        except cognito_idp_client.exceptions.UserNotFoundException:
            print(f"User '{username}' does not exist, creating...")
        
        # Create user
        response = cognito_idp_client.admin_create_user(
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
        
        print(f"✓ User '{username}' created successfully")
        
        # Set permanent password
        try:
            cognito_idp_client.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=username,
                Password=password,
                Permanent=True
            )
            print(f"✓ Password set for user '{username}'")
        except Exception as e:
            print(f"Warning: Could not set permanent password: {e}")
            print("User may need to change password on first login")
        
        return True
        
    except Exception as e:
        print(f"Error creating test user: {e}")
        return False
   
def create_cognito_user_pool():
    """Creates Cognito User Pool for MCP authentication"""    
    pool_name = config['cognito']['user_pool_name']
    client_name = config['cognito']['client_name']
    
    try:
        cognito_client = boto3.client('cognito-idp', region_name=config['region'])
        
        # Check existing User Pool
        try:
            response = cognito_client.list_user_pools(MaxResults=10)
            for pool in response['UserPools']:
                if pool['Name'] == pool_name:
                    print(f"Existing User Pool found: {pool['Id']}")
                    user_pool_id = pool['Id']
                    
                    # Check if client already exists for this user pool
                    try:
                        client_response = cognito_client.list_user_pool_clients(UserPoolId=user_pool_id)
                        for client in client_response['UserPoolClients']:
                            if client['ClientName'] == client_name:
                                client_id = client['ClientId']
                                print(f"Existing App client found: {client_id}")
                                
                                # Update config.json with client_id
                                try:
                                    config['cognito']['client_id'] = client_id
                                    config_file = "config.json"
                                    with open(config_file, "w") as f:
                                        json.dump(config, f, indent=2)
                                    print(f"✓ Client ID updated in config.json: {client_id}")
                                except Exception as e:
                                    print(f"Warning: Failed to update config.json with client_id: {e}")
                                
                                return user_pool_id, client_id
                        
                        # Client doesn't exist, create it
                        print("Creating new App client for existing User Pool...")
                        client_response = cognito_client.create_user_pool_client(
                            UserPoolId=user_pool_id,
                            ClientName=client_name,
                            GenerateSecret=False,
                            ExplicitAuthFlows=[
                                'ALLOW_USER_PASSWORD_AUTH',
                                'ALLOW_REFRESH_TOKEN_AUTH'
                            ]
                        )
                        
                        client_id = client_response['UserPoolClient']['ClientId']
                        print(f"✓ App client created successfully: {client_id}")
                        
                        # Update config.json with client_id
                        try:
                            config['cognito']['client_id'] = client_id
                            config_file = "config.json"
                            with open(config_file, "w") as f:
                                json.dump(config, f, indent=2)
                            print(f"✓ Client ID updated in config.json: {client_id}")
                        except Exception as e:
                            print(f"Warning: Failed to update config.json with client_id: {e}")
                        
                        return user_pool_id, client_id
                        
                    except Exception as e:
                        print(f"Failed to check/create client for existing User Pool: {e}")
                        return None, None
        except Exception as e:
            print(f"Failed to check User Pool list: {e}")
        
        # Create new User Pool
        print("Creating new Cognito User Pool...")
        
        response = cognito_client.create_user_pool(
            PoolName=pool_name,
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
        print(f"User Pool created successfully: {user_pool_id}")
        
        # Create app client
        client_response = cognito_client.create_user_pool_client(
            UserPoolId=user_pool_id,
            ClientName=client_name,
            GenerateSecret=False,
            ExplicitAuthFlows=[
                'ALLOW_USER_PASSWORD_AUTH',
                'ALLOW_REFRESH_TOKEN_AUTH'
            ]
        )
        
        client_id = client_response['UserPoolClient']['ClientId']
        print(f"✓ App client created successfully: {client_id}")
        
        # Update config.json with client_id
        try:
            config['cognito']['client_id'] = client_id
            config_file = "config.json"
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)
            print(f"✓ Client ID updated in config.json: {client_id}")
        except Exception as e:
            print(f"Warning: Failed to update config.json with client_id: {e}")
        
        return user_pool_id, client_id
        
    except Exception as e:
        print(f"Failed to create Cognito User Pool: {e}")
        return None, None

def create_cognito_identity_pool(user_pool_id):
    """Creates Cognito Identity Pool and fixes App Client authentication flows"""    
    identity_pool_name = config['cognito']['identity_pool_name']
    client_id = config['cognito'].get('client_id', '')
    region = config['region']
    
    if not client_id:
        print("Warning: client_id not found in config. Please run the setup again.")
        return None
    
    try:
        # First, fix the Cognito app client authentication flows
        print("Fixing Cognito app client authentication flows...")
        cognito_idp_client = boto3.client('cognito-idp', region_name=region)
        
        try:
            # Update the app client to enable proper authentication flows
            response = cognito_idp_client.update_user_pool_client(
                UserPoolId=user_pool_id,
                ClientId=client_id,
                ExplicitAuthFlows=[
                    'ALLOW_ADMIN_USER_PASSWORD_AUTH',
                    'ALLOW_USER_PASSWORD_AUTH',
                    'ALLOW_REFRESH_TOKEN_AUTH',
                    'ALLOW_USER_SRP_AUTH'
                ],
                ReadAttributes=[
                    'email',
                    'email_verified',
                    'name'
                ],
                WriteAttributes=[
                    'email',
                    'name'
                ]
            )
            print("✓ Cognito app client authentication flows updated successfully")
        except Exception as e:
            print(f"Warning: Failed to update Cognito app client: {e}")
        
        # Now create or find Identity Pool
        identity_client = boto3.client('cognito-identity', region_name=region)
        
        # Check existing Identity Pool
        try:
            response = identity_client.list_identity_pools(MaxResults=10)
            for pool in response['IdentityPools']:
                if pool['IdentityPoolName'] == identity_pool_name:
                    print(f"Existing Identity Pool found: {pool['IdentityPoolId']}")
                    identity_pool_id = pool['IdentityPoolId']
                    
                    # Update existing identity pool to allow unauthenticated access for testing
                    try:
                        print("Updating existing Identity Pool to allow unauthenticated access for testing...")
                        pool_response = identity_client.describe_identity_pool(IdentityPoolId=identity_pool_id)
                        update_response = identity_client.update_identity_pool(
                            IdentityPoolId=identity_pool_id,
                            IdentityPoolName=identity_pool_name,
                            AllowUnauthenticatedIdentities=True,
                            CognitoIdentityProviders=pool_response.get('CognitoIdentityProviders', []),
                            SupportedLoginProviders=pool_response.get('SupportedLoginProviders', {})
                        )
                        print("✓ Existing Identity Pool updated to allow unauthenticated access for testing")
                    except Exception as e:
                        print(f"Warning: Failed to update existing Identity Pool for testing: {e}")
                    
                    return identity_pool_id
        except Exception as e:
            print(f"Failed to check Identity Pool list: {e}")
        
        # Create new Identity Pool
        print("Creating new Cognito Identity Pool...")
        
        response = identity_client.create_identity_pool(
            IdentityPoolName=identity_pool_name,
            AllowUnauthenticatedIdentities=False,
            CognitoIdentityProviders=[
                {
                    'ProviderName': f'cognito-idp.{region}.amazonaws.com/{user_pool_id}',
                    'ClientId': client_id,
                    'ServerSideTokenCheck': False
                }
            ]
        )
        
        identity_pool_id = response['IdentityPoolId']
        print(f"✓ Identity Pool created successfully: {identity_pool_id}")
        
        # Update identity pool to allow unauthenticated access for testing
        try:
            print("Updating Identity Pool to allow unauthenticated access for testing...")
            update_response = identity_client.update_identity_pool(
                IdentityPoolId=identity_pool_id,
                IdentityPoolName=identity_pool_name,
                AllowUnauthenticatedIdentities=True,
                CognitoIdentityProviders=response.get('CognitoIdentityProviders', []),
                SupportedLoginProviders=response.get('SupportedLoginProviders', {})
            )
            print("✓ Identity Pool updated to allow unauthenticated access for testing")
        except Exception as e:
            print(f"Warning: Failed to update Identity Pool for testing: {e}")
        
        return identity_pool_id
        
    except Exception as e:
        print(f"Failed to create Cognito Identity Pool: {e}")
        return None

def update_agentcore_config_with_cognito(user_pool_id, identity_pool_id, client_id, discovery_url):
    """Updates AgentCore configuration with Cognito information"""
    # Update Cognito configuration
    config['cognito'].update({
        'user_pool_id': user_pool_id,
        'identity_pool_id': identity_pool_id,
        'discovery_url': discovery_url
    })
    
    # Update client_id if provided
    if client_id:
        config['cognito']['client_id'] = client_id
    
    # Save configuration file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"AgentCore configuration updated successfully: {config_path}")
    
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
        
        # Create secret value with bearer_token 
        secret_value = {
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
            print(f"Bearer token updated in secret manager with key: {secret_value['bearer_token']}")
        except client.exceptions.ResourceNotFoundException:
            # Secret doesn't exist, create it
            client.create_secret(
                Name=secret_name,
                SecretString=secret_string,
                Description="MCP Server Cognito credentials with bearer key and token"
            )
            print(f"Bearer token created in secret manager with key: {secret_value['bearer_token']}")
            
    except Exception as e:
        print(f"Error saving bearer token: {e}")

def main():
    print("=== AWS Bedrock AgentCore MCP Setup ===\n")
    
    # 1. Create Cognito User Pool
    print("1. Creating Cognito User Pool...")
    user_pool_id, client_id = create_cognito_user_pool()
    
    # 2. Create Cognito Identity Pool
    print("\n2. Creating Cognito Identity Pool...")
    identity_pool_id = None
    if user_pool_id:
        identity_pool_id = create_cognito_identity_pool(user_pool_id)
    
    # 3. Update AgentCore Configuration
    print("\n3. Updating AgentCore Configuration...")

    discovery_url = f"https://cognito-idp.{config['region']}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration"

    if user_pool_id and identity_pool_id:
        update_agentcore_config_with_cognito(user_pool_id, identity_pool_id, client_id, discovery_url)
            
    # 4. Create test user
    print("\n4. Creating test user...")
    if user_pool_id:
        response = create_test_user()
        print(f"response of create_test_user: {response}")
            
        # 5. Create Bearer token
        print("\n5. Creating Bearer token...")
        bearer_token = create_cognito_bearer_token(config)
        print(f"bearer_tokenen: {bearer_token}")

        # secret of bearer token
        current_folder_name = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
        target = current_folder_name.split('/')[-1].lower()
        print(f"target: {target}")

        project = config['projectName'].lower()
        secret_name = f'{project}/credentials'
        print(f"secret_name: {secret_name}")
        
        try:
            config['secret_name'] = secret_name
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print(f"✓ secret_name updated in config.json: {secret_name}")
        except Exception as e:
            print(f"Warning: Failed to update config.json with client_id: {e}")

        save_bearer_token(secret_name, bearer_token)

    print("\n=== Setup Summary ===")
    print("✓ Cognito User Pool and Identity Pool created")
    print("✓ App client authentication flows configured")
    print("✓ Test user created")
    print("✓ Bearer token generated and saved")
    print("\nYou can now use the MCP server with authentication!")
    
if __name__ == "__main__":
    main()
