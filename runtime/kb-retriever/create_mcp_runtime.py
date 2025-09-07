import boto3
import json
import os

def load_config():
    config = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

aws_region = config['region']
accountId = config['accountId']
projectName = config['projectName']
agent_runtime_role = config['agent_runtime_role']

current_folder_name = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
target = current_folder_name.split('/')[-1]
print(f"target: {target}")

repositoryName = (projectName+'_'+target).lower()
print(f"repositoryName: {repositoryName}")

# get lagtest image
ecr_client = boto3.client('ecr', region_name=aws_region)
response = ecr_client.describe_images(repositoryName=repositoryName)
images = response['imageDetails']
print(f"images: {images}")

# get latest image
images_sorted = sorted(images, key=lambda x: x['imagePushedAt'], reverse=True)
latestImage = images_sorted[0]
print(f"latestImage: {latestImage}")
imageTags = latestImage['imageTags'][0]
print(f"imageTags: {imageTags}")

client = boto3.client('bedrock-agentcore-control', region_name=aws_region)

# Check for duplicate Agent Runtime name
def create_agent_runtime(targetAgentRuntime):
    runtime_name = targetAgentRuntime
    print(f"create agent runtime!")    
    print(f"Trying to create agent: {runtime_name}")

    # create agent runtime
    agentRuntimeArn = None
    try:        
        response = client.create_agent_runtime(
            agentRuntimeName=runtime_name,
            agentRuntimeArtifact={
                'containerConfiguration': {
                    'containerUri': f"{accountId}.dkr.ecr.{aws_region}.amazonaws.com/{repositoryName}:{imageTags}"
                }
            },
            networkConfiguration={"networkMode":"PUBLIC"}, 
            roleArn=agent_runtime_role,
            protocolConfiguration={"serverProtocol":"MCP"},
            authorizerConfiguration={
                "customJWTAuthorizer": {
                    "allowedClients": [
                        config['cognito']['client_id']
                    ],
                    "discoveryUrl": config['cognito']['discovery_url']
                }
            }
        )
        print(f"response of create agent runtime: {response}")

        agentRuntimeArn = response['agentRuntimeArn']
        print(f"agentRuntimeArn: {agentRuntimeArn}")

    except client.exceptions.ConflictException as e:
        print(f"[ERROR] ConflictException: {e}")

    return agentRuntimeArn

def update_agent_runtime(agentRuntimeId):    
    response = client.update_agent_runtime(
        agentRuntimeId=agentRuntimeId,
        description="Update agent runtime",
        agentRuntimeArtifact={
            'containerConfiguration': {
                'containerUri': f"{accountId}.dkr.ecr.{aws_region}.amazonaws.com/{repositoryName}:{imageTags}"
            }
        },
        roleArn=agent_runtime_role,
        networkConfiguration={"networkMode":"PUBLIC"},
        protocolConfiguration={"serverProtocol":"MCP"},
        authorizerConfiguration={
            "customJWTAuthorizer": {
                "allowedClients": [
                    config['cognito']['client_id']
                ],
                "discoveryUrl": config['cognito']['discovery_url']
            }
        }
    )
    print(f"response: {response}")

    agentRuntimeArn = response['agentRuntimeArn']
    print(f"agentRuntimeArn: {agentRuntimeArn}")

    return agentRuntimeArn

def main():
    targetAgentRuntime = projectName.lower().replace('-', '_')+'_'+target.lower().replace('-', '_')
    print(f"targetAgentRuntime: {targetAgentRuntime}")

    client = boto3.client('bedrock-agentcore-control', region_name=aws_region)
    response = client.list_agent_runtimes()
    print(f"response: {response}")

    isExist = False
    agentRuntimeId = None
    agentRuntimes = response['agentRuntimes']
    if len(agentRuntimes) > 0:
        for agentRuntime in agentRuntimes:
            agentRuntimeName = agentRuntime['agentRuntimeName']
            print(f"agentRuntimeName: {agentRuntimeName}")
            if agentRuntimeName == targetAgentRuntime:
                print(f"agentRuntimeName: {agentRuntimeName} is already exists")
                agentRuntimeId = agentRuntime['agentRuntimeId']
                print(f"agentRuntimeId: {agentRuntimeId}")
                isExist = True        
                break
    print(f"isExist: {isExist}")

    if isExist:
        print(f"update agent runtime: {targetAgentRuntime}, imageTags: {imageTags}")
        agentRuntimeArn = update_agent_runtime(agentRuntimeId)
    else:
        print(f"create agent runtime: {targetAgentRuntime}, imageTags: {imageTags}")
        agentRuntimeArn = create_agent_runtime(targetAgentRuntime)

    config['agent_runtime_arn'] = agentRuntimeArn            

    # knowledge_base_name
    knowledge_base_name = config.get("knowledge_base_name", "")
    if not knowledge_base_name:
        knowledge_base_name = projectName
        config['knowledge_base_name'] = knowledge_base_name

    # knowledge_base_id
    knowledge_base_id = config.get("knowledge_base_id", "")
    if not knowledge_base_id:
        # search knowledge base id using knowledge base name
        bedrock_agent_client = boto3.client("bedrock-agent")
        response = bedrock_agent_client.list_knowledge_bases()
        for knowledge_base in response["knowledgeBaseSummaries"]:
            if knowledge_base["name"] == projectName:
                knowledge_base_id = knowledge_base["knowledgeBaseId"]
                break
        print(f"knowledge_base_id: {knowledge_base_id}")
        config['knowledge_base_name'] = projectName
        config['knowledge_base_id'] = knowledge_base_id
    
    # update config
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
if __name__ == "__main__":
    main()    