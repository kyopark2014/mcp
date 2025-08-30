import time
import os
import json
import logging
import sys

from bedrock_agentcore_starter_toolkit import Runtime
from boto3.session import Session

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("utils")

boto_session = Session()
region = boto_session.region_name
logger.info(f"Using AWS region: {region}")

agentcore_runtime = Runtime()

def load_config():
    config = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

bedrock_region = config['region']
projectName = config['projectName']
agent_runtime_role = config['agent_runtime_role']
tool_name = "use_aws"

logger.info("Configuring AgentCore Runtime...")
response = agentcore_runtime.configure(
    entrypoint="mcp_server_use_aws.py",
    execution_role=agent_runtime_role,
    auto_create_ecr=True,
    requirements_file="requirements.txt",
    region=region,
    protocol="MCP",
    agent_name=tool_name
)
logger.info(f"Configuration response: {response}")

# Launching MCP server to AgentCore Runtime
logger.info("Launching MCP server to AgentCore Runtime...")
logger.info("This may take several minutes...")
launch_result = agentcore_runtime.launch()
logger.info("Launch completed ✓")
logger.info(f"Agent ARN: {launch_result.agent_arn}")
logger.info(f"Agent ID: {launch_result.agent_id}")

# Checking AgentCore Runtime Status
logger.info("Checking AgentCore Runtime status...")
status_response = agentcore_runtime.status()
status = status_response.endpoint['status']
logger.info(f"Initial status: {status}")

end_status = ['READY', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']
while status not in end_status:
    logger.info(f"Status: {status} - waiting...")
    time.sleep(10)
    status_response = agentcore_runtime.status()
    status = status_response.endpoint['status']

if status == 'READY':
    logger.info("AgentCore Runtime is READY!")
else:
    logger.info(f"AgentCore Runtime status: {status}")
    
logger.info(f"Final status: {status}")