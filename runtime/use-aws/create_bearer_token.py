import boto3
import json
import os

accountId = boto3.client('sts').get_caller_identity()['Account']

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

def load_config():
    """Load configuration from config.json"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"Failed to load config.json: {e}")
        return None
    
config = load_config()
region = config['region']
projectName = config['projectName']

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

    client_name = cognito_config.get('client_name')
    if not client_name:        
        client_name = f"{projectName}-agentcore-client"
        print(f"No client name found in config, using default client name: {client_name}")
        cognito_config['client_name'] = client_name

    client_id = cognito_config.get('client_id')
    if not client_id and user_pool_id:
        response = cognito_client.list_user_pool_clients(UserPoolId=user_pool_id)
        for client in response['UserPoolClients']:
            if client['ClientName'] == client_name:
                client_id = client['ClientId']
                print(f"Found cognito client: {client_id}")
                cognito_config['client_id'] = client_id   
                break             
        
    username = cognito_config.get('test_username')
    password = cognito_config.get('test_password')
    if not username or not password:
        print("No test username found in config, using default username and password. Please check config.json and update the test username and password.")
        username = f"{projectName}-test-user@example.com"
        password = "TestPassword123!"        
        cognito_config['test_username'] = username
        cognito_config['test_password'] = password

    # Set default identity pool name if not provided
    identity_pool_name = cognito_config.get('identity_pool_name')    
    if not identity_pool_name:
        identity_pool_name = f"{projectName}-agentcore-identity-pool"
        print(f"No identity pool name found in config, using default: {identity_pool_name}")
        cognito_config['identity_pool_name'] = identity_pool_name

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    return cognito_config

# get config of cognito
cognito_config = config.get('cognito', {})
if not cognito_config:
    cognito_config = get_cognito_config(cognito_config)
    if 'cognito' not in config:
        config['cognito'] = {}
    config['cognito'].update(cognito_config)
 
# load variables from cognito_config
username = cognito_config.get('test_username')
password = cognito_config.get('test_password')
user_pool_name = cognito_config['user_pool_name']
client_name = cognito_config['client_name']

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
    
def create_cognito_user_pool():
    """Creates Cognito User Pool for MCP authentication"""    
    user_pool_name = cognito_config['user_pool_name']    
    user_pool_id = cognito_config.get('user_pool_id')
    if not user_pool_id:
        user_pool_id = create_user_pool(user_pool_name)
        print(f"✓ User Pool created successfully: {user_pool_id}")
        cognito_config['user_pool_id'] = user_pool_id

    client_id = cognito_config.get('client_id')        
    if not client_id:         
        print("Creating new App client for existing User Pool...")
        client_id = create_client(user_pool_id, client_name)
        print(f"✓ App client created successfully: {client_id}")
        cognito_config['client_id'] = client_id

    # save config
    config['cognito'].update(cognito_config)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"✓ Client ID updated in config.json: {client_id}")

    return user_pool_id, client_id

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

def create_test_user():
    """Create a test user in Cognito User Pool"""
    user_pool_id = cognito_config.get('user_pool_id')
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

    config['cognito'].update(cognito_config)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return config        

def create_cognito_identity_pool(user_pool_id, client_id):
    """Creates Cognito Identity Pool"""    
    identity_pool_name = cognito_config.get('identity_pool_name')
    identity_pool_id = cognito_config.get('identity_pool_id')    
    
    if not identity_pool_id:    
        identity_client = boto3.client('cognito-identity', region_name=region)
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
                
    return identity_pool_id
        
def update_agentcore_config_with_cognito(user_pool_id, identity_pool_id, client_id, discovery_url):
    """Updates AgentCore configuration with Cognito information"""
    # Update Cognito configuration
    config['cognito'].update({
        'client_id': client_id,
        'user_pool_id': user_pool_id,
        'identity_pool_id': identity_pool_id,
        'discovery_url': discovery_url
    })
        
    # Save configuration file
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"AgentCore configuration updated successfully: {config_path}")
    
def create_cognito_bearer_token(config):
    """Get a fresh bearer token from Cognito"""
    try:
        cognito_config = config['cognito']
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
    identity_pool_id = create_cognito_identity_pool(user_pool_id, client_id)
    
    # 3. Update AgentCore Configuration
    print("\n3. Updating AgentCore Configuration...")
    discovery_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration"
    update_agentcore_config_with_cognito(user_pool_id, identity_pool_id, client_id, discovery_url)
            
    # 4. Create test user
    print("\n4. Creating test user...")        
    config = create_test_user()
    print(f"config: {config}")

    # 5. Create Bearer token
    print("\n5. Creating Bearer token...")
    bearer_token = create_cognito_bearer_token(config)
    print(f"bearer_tokenen: {bearer_token}")

    # 6. Save bearer token    
    secret_name = f'{projectName.lower()}/credentials'
    print(f"secret_name: {secret_name}")    
    config['secret_name'] = secret_name
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"✓ secret_name updated in config.json: {secret_name}")
    
    save_bearer_token(secret_name, bearer_token)

    print("\n=== Setup Summary ===")
    print("✓ Cognito User Pool and Identity Pool created")
    print("✓ App client authentication flows configured")
    print("✓ Test user created")
    print("✓ Bearer token generated and saved")
    print("\nYou can now use the MCP server with authentication!")
    
if __name__ == "__main__":
    main()
