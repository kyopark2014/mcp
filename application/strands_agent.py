import chat
import os
import contextlib
import mcp_config
import logging
import sys
import utils
import boto3

from contextlib import contextmanager
from typing import Dict, List, Optional
from strands.models import BedrockModel
from strands_tools import calculator, current_time, use_aws
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamablehttp_client
from botocore.config import Config
from speak import speak
from bedrock_agentcore.runtime import BedrockAgentCoreApp

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("strands-agent")

initiated = False
strands_tools = []
mcp_servers = []

tool_list = []

memory_id = actor_id = session_id = namespace = None

s3_prefix = "docs"
capture_prefix = "captures"

selected_strands_tools = []
selected_mcp_servers = []

history_mode = "Disable"
aws_region = utils.bedrock_region


#########################################################
# Strands Agent 
#########################################################
def get_model():
    if chat.model_type == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif chat.model_type == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 
    elif chat.model_type == 'openai':
        STOP_SEQUENCE = "" 

    if chat.model_type == 'claude':
        maxOutputTokens = 4096 # 4k
    else:
        maxOutputTokens = 5120 # 5k

    maxReasoningOutputTokens=64000
    thinking_budget = min(maxOutputTokens, maxReasoningOutputTokens-1000)

    # AWS 자격 증명 설정
    aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    aws_session_token = os.environ.get('AWS_SESSION_TOKEN')

    # Bedrock 클라이언트 설정
    bedrock_config = Config(
        read_timeout=900,
        connect_timeout=900,
        retries=dict(max_attempts=3, mode="adaptive"),
    )

    if aws_access_key and aws_secret_key:
        bedrock_client = boto3.client(
            'bedrock-runtime',
            region_name=aws_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
            config=bedrock_config
        )
    else:
        bedrock_client = boto3.client(
            'bedrock-runtime',
            region_name=aws_region,
            config=bedrock_config
        )

    if chat.reasoning_mode=='Enable' and chat.model_type != 'openai':
        model = BedrockModel(
            client=bedrock_client,
            model_id=chat.model_id,
            max_tokens=64000,
            stop_sequences = [STOP_SEQUENCE],
            temperature = 1,
            additional_request_fields={
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
            },
        )
    elif chat.reasoning_mode=='Disable' and chat.model_type != 'openai':
        model = BedrockModel(
            client=bedrock_client,
            model_id=chat.model_id,
            max_tokens=maxOutputTokens,
            stop_sequences = [STOP_SEQUENCE],
            temperature = 0.1,
            top_p = 0.9,
            additional_request_fields={
                "thinking": {
                    "type": "disabled"
                }
            }
        )
    elif chat.model_type == 'openai':
        model = BedrockModel(
            model=chat.model_id,
            region=aws_region,
            streaming=True
        )
    return model

conversation_manager = SlidingWindowConversationManager(
    window_size=10,  
)

class MCPClientManager:
    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
        self.client_configs: Dict[str, dict] = {}  # Store client configurations
    
    def _refresh_bearer_token_and_update_client(self, client_name: str) -> bool:
        """Refresh bearer token and update client configuration"""
        try:
            # Load the original config to get Cognito settings
            config = mcp_config.load_config(client_name)
            if not config:
                logger.error(f"Failed to load config for {client_name}")
                return False
            
            # Get fresh bearer token from Cognito
            bearer_token = mcp_config.create_cognito_bearer_token(utils.load_config())
            if not bearer_token:
                logger.error("Failed to get fresh bearer token from Cognito")
                return False
            
            logger.info("Successfully obtained fresh bearer token")
            
            # Update the client configuration with new bearer token
            if client_name in self.client_configs:
                client_config = self.client_configs[client_name]
                if 'headers' in client_config:
                    client_config['headers']['Authorization'] = f"Bearer {bearer_token}"
                    logger.info(f"Updated bearer token for {client_name}")
                    
                    # Save the new bearer token
                    secret_name = config.get('secret_name')
                    if secret_name:
                        mcp_config.save_bearer_token(secret_name, bearer_token)
                    
                    # Remove the old client to force recreation
                    if client_name in self.clients:
                        del self.clients[client_name]
                    
                    logger.info(f"Successfully refreshed bearer token for {client_name}")
                    return True
                else:
                    logger.error(f"No headers found in client config for {client_name}")
                    return False
            else:
                logger.error(f"No client config found for {client_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error during bearer token refresh for {client_name}: {e}")
            return False
        
    def add_stdio_client(self, name: str, command: str, args: List[str], env: dict[str, str] = {}) -> None:
        """Add a new MCP client configuration (lazy initialization)"""
        self.client_configs[name] = {
            "transport": "stdio",
            "command": command,
            "args": args,
            "env": env
        }
        logger.info(f"Stored configuration for MCP client: {name}")
    
    def add_streamable_client(self, name: str, url: str, headers: dict[str, str] = {}) -> None:
        """Add a new MCP client configuration (lazy initialization)"""
        self.client_configs[name] = {
            "transport": "streamable_http",
            "url": url,
            "headers": headers
        }
        logger.info(f"Stored configuration for MCP client: {name}")
    
    def get_client(self, name: str) -> Optional[MCPClient]:
        """Get or create MCP client (lazy initialization)"""
        if name not in self.client_configs:
            logger.warning(f"No configuration found for MCP client: {name}")
            return None
            
        if name not in self.clients:
            # Create client on first use
            config = self.client_configs[name]
            logger.info(f"Creating MCP client for {name} with config: {config}")
            try:
                if "transport" in config and config["transport"] == "streamable_http":
                    try:
                        self.clients[name] = MCPClient(lambda: streamablehttp_client(
                            url=config["url"], 
                            headers=config["headers"]
                        ))
                    except Exception as http_error:
                        logger.error(f"Failed to create streamable HTTP client for {name}: {http_error}")
                        if "403" in str(http_error) or "Forbidden" in str(http_error) or "MCPClientInitializationError" in str(http_error) or "client initialization failed" in str(http_error):
                            logger.error(f"Authentication failed for {name}. Attempting to refresh bearer token...")
                            
                            # Try to refresh bearer token and retry
                            if self._refresh_bearer_token_and_update_client(name):
                                # Retry with new bearer token
                                logger.info("Retrying MCP client creation with fresh bearer token...")
                                config = self.client_configs[name]
                                self.clients[name] = MCPClient(lambda: streamablehttp_client(
                                    url=config["url"], 
                                    headers=config["headers"]
                                ))
                                
                                logger.info(f"Successfully created MCP client for {name} after bearer token refresh")
                            else:
                                raise http_error
                        else:
                            raise http_error
                else:
                    self.clients[name] = MCPClient(lambda: stdio_client(
                        StdioServerParameters(
                            command=config["command"], 
                            args=config["args"], 
                            env=config["env"]
                        )
                    ))
                
                logger.info(f"Successfully created MCP client: {name}")
            except Exception as e:
                logger.error(f"Failed to create MCP client {name}: {e}")
                logger.error(f"Exception type: {type(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                return None
        else:
            # Check if client is already running and stop it if necessary
            try:
                client = self.clients[name]
                if hasattr(client, '_session') and client._session is not None:
                    logger.info(f"Stopping existing session for client: {name}")
                    try:
                        client.stop()
                    except Exception as stop_error:
                        # Ignore 404 errors during session termination (common with AWS Bedrock AgentCore)
                        if "404" in str(stop_error) or "Not Found" in str(stop_error):
                            logger.info(f"Session already terminated for {name} (404 expected)")
                        else:
                            logger.warning(f"Error stopping existing client session for {name}: {stop_error}")
            except Exception as e:
                logger.warning(f"Error checking client session for {name}: {e}")
        return self.clients[name]
    
    def remove_client(self, name: str) -> None:
        """Remove an MCP client"""
        if name in self.clients:
            del self.clients[name]
        if name in self.client_configs:
            del self.client_configs[name]
    
    @contextmanager
    def get_active_clients(self, active_clients: List[str]):
        """Manage active clients context"""
        logger.info(f"active_clients: {active_clients}")
        active_contexts = []
        try:
            for client_name in active_clients:
                client = self.get_client(client_name)
                if client:
                    # Ensure client is not already running
                    try:
                        if hasattr(client, '_session') and client._session is not None:
                            logger.info(f"Stopping existing session for client: {client_name}")
                            try:
                                client.stop()
                            except Exception as stop_error:
                                # Ignore 404 errors during session termination (common with AWS Bedrock AgentCore)
                                if "404" in str(stop_error) or "Not Found" in str(stop_error):
                                    logger.info(f"Session already terminated for {client_name} (404 expected)")
                                else:
                                    logger.warning(f"Error stopping existing session for {client_name}: {stop_error}")
                    except Exception as e:
                        logger.warning(f"Error checking existing session for {client_name}: {e}")
                    
                    active_contexts.append(client)

            # logger.info(f"active_contexts: {active_contexts}")
            if active_contexts:
                with contextlib.ExitStack() as stack:
                    for client in active_contexts:
                        try:
                            stack.enter_context(client)
                        except Exception as e:
                            logger.error(f"Error entering context for client: {e}")
                            
                            # Check if this is a 403 error and try to refresh bearer token
                            logger.info(f"Error details: {type(e).__name__}: {str(e)}")
                            if "403" in str(e) or "Forbidden" in str(e) or "MCPClientInitializationError" in str(e) or "client initialization failed" in str(e):
                                logger.info("403 error detected, attempting to refresh bearer token...")
                                try:
                                    # Find the client name from the active_clients list
                                    client_name = None
                                    for name, client_obj in mcp_manager.clients.items():
                                        if client_obj == client:
                                            client_name = name
                                            break
                                    
                                    if client_name:
                                        if self._refresh_bearer_token_and_update_client(client_name):
                                            # Retry with new bearer token
                                            logger.info("Retrying client creation with fresh bearer token...")
                                            # Remove the old client completely and create a new one
                                            if client_name in self.clients:
                                                del self.clients[client_name]
                                            new_client = self.get_client(client_name)
                                            if new_client:
                                                stack.enter_context(new_client)
                                                logger.info(f"Successfully created client for {client_name} after bearer token refresh")
                                                continue
                                    
                                except Exception as retry_error:
                                    logger.error(f"Error during bearer token refresh and retry: {retry_error}")
                            
                            # Try to stop the client if it's already running
                            try:
                                if hasattr(client, 'stop'):
                                    try:
                                        client.stop()
                                    except Exception as stop_error:
                                        # Ignore 404 errors during session termination
                                        if "404" in str(stop_error) or "Not Found" in str(stop_error):
                                            logger.info(f"Session already terminated (404 expected)")
                                        else:
                                            logger.warning(f"Error stopping client: {stop_error}")
                            except:
                                pass
                            raise
                    yield
            else:
                yield
        except Exception as e:
            logger.error(f"Error in MCP client context: {e}")
            raise

# Initialize MCP client manager
mcp_manager = MCPClientManager()

# Set up MCP clients
def init_mcp_clients(mcp_servers: list):
    logger.info(f"mcp_servers: {mcp_servers}")
    
    for tool in mcp_servers:
        logger.info(f"Initializing MCP client for tool: {tool}")
        config = mcp_config.load_config(tool)
        # logger.info(f"config: {config}")

        # Skip if config is empty or doesn't have mcpServers
        if not config or "mcpServers" not in config:
            logger.warning(f"No configuration found for tool: {tool}")
            continue

        # Get the first key from mcpServers
        server_key = next(iter(config["mcpServers"]))
        server_config = config["mcpServers"][server_key]
        
        if "type" in server_config and server_config["type"] == "streamable_http":
            name = tool  # Use tool name as client name
            url = server_config["url"]
            headers = server_config.get("headers", {})                
            logger.info(f"Adding MCP client - name: {name}, url: {url}, headers: {headers}")
                
            try:                
                mcp_manager.add_streamable_client(name, url, headers)
                logger.info(f"Successfully added streamable MCP client for {name}")
            except Exception as e:
                logger.error(f"Failed to add streamable MCP client for {name}: {e}")
                
                # Try to refresh bearer token and retry for 403 errors
                if "403" in str(e) or "Forbidden" in str(e) or "MCPClientInitializationError" in str(e) or "client initialization failed" in str(e):
                    logger.info("Attempting to refresh bearer token and retry...")
                    if mcp_manager._refresh_bearer_token_and_update_client(name):
                        # Retry with new bearer token
                        logger.info("Retrying MCP client creation with fresh bearer token...")
                        mcp_manager.add_streamable_client(name, url, mcp_manager.client_configs[name]["headers"])
                        logger.info(f"Successfully added streamable MCP client for {name} after bearer token refresh")
                    else:
                        continue
                else:
                    continue            
        else:
            name = tool  # Use tool name as client name
            command = server_config["command"]
            args = server_config["args"]
            env = server_config.get("env", {})  # Use empty dict if env is not present            
            logger.info(f"Adding MCP client - name: {name}, command: {command}, args: {args}, env: {env}")        

            try:
                mcp_manager.add_stdio_client(name, command, args, env)
                logger.info(f"Successfully added MCP client for {name}")
            except Exception as e:
                logger.error(f"Failed to add stdio MCP client for {name}: {e}")
                continue
                            
def update_tools(strands_tools: list, mcp_servers: list):
    tools = []
    tool_map = {
        "calculator": calculator,
        "current_time": current_time,
        "use_aws": use_aws,
        "speak": speak
        # "python_repl": python_repl  # Temporarily disabled
    }

    for tool_item in strands_tools:
        if isinstance(tool_item, list):
            tools.extend(tool_item)
        elif isinstance(tool_item, str) and tool_item in tool_map:
            tools.append(tool_map[tool_item])

    # MCP tools
    mcp_servers_loaded = 0
    for mcp_tool in mcp_servers:
        logger.info(f"Processing MCP tool: {mcp_tool}")        
        try:
            with mcp_manager.get_active_clients([mcp_tool]) as _:
                client = mcp_manager.get_client(mcp_tool)
                if client:
                    logger.info(f"Got client for {mcp_tool}, attempting to list tools...")
                    try:
                        mcp_servers_list = client.list_tools_sync()
                        logger.info(f"{mcp_tool}_tools: {mcp_servers_list}")
                        if mcp_servers_list:
                            tools.extend(mcp_servers_list)
                            mcp_servers_loaded += 1
                            logger.info(f"Successfully added {len(mcp_servers_list)} tools from {mcp_tool}")
                        else:
                            logger.warning(f"No tools returned from {mcp_tool}")
                    except Exception as tool_error:
                        logger.error(f"Error listing tools for {mcp_tool}: {tool_error}")
                        continue
                else:
                    logger.error(f"Failed to get client for {mcp_tool}")
        except Exception as e:
            logger.error(f"Error getting tools for {mcp_tool}: {e}")
            logger.error(f"Exception type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Try to refresh bearer token and retry for 403 errors
            if "403" in str(e) or "Forbidden" in str(e) or "MCPClientInitializationError" in str(e) or "client initialization failed" in str(e):
                logger.info(f"Attempting to refresh bearer token and retry for {mcp_tool}...")
                if mcp_manager._refresh_bearer_token_and_update_client(mcp_tool):
                    # Retry getting tools
                    logger.info("Retrying tool retrieval with fresh bearer token...")
                    with mcp_manager.get_active_clients([mcp_tool]) as _:
                        client = mcp_manager.get_client(mcp_tool)
                        if client:
                            mcp_servers_list = client.list_tools_sync()
                            if mcp_servers_list:
                                tools.extend(mcp_servers_list)
                                mcp_servers_loaded += 1
                                logger.info(f"Successfully added {len(mcp_servers_list)} tools from {mcp_tool} after bearer token refresh")
                            else:
                                logger.warning(f"No tools returned from {mcp_tool} after bearer token refresh")
                        else:
                            logger.error(f"Failed to get client for {mcp_tool} after bearer token refresh")
            
            continue

    logger.info(f"Successfully loaded {mcp_servers_loaded} out of {len(mcp_servers)} MCP tools")
    logger.info(f"tools: {tools}")

    return tools

def create_agent(system_prompt, tools, history_mode):
    if system_prompt==None:
        system_prompt = (
            "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다." 
            "모르는 질문을 받으면 솔직히 모른다고 말합니다."
        )

    if not system_prompt or not system_prompt.strip():
        system_prompt = "You are a helpful AI assistant."

    model = get_model()
    if history_mode == "Enable":
        logger.info("history_mode: Enable")
        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            conversation_manager=conversation_manager
        )
    else:
        logger.info("history_mode: Disable")
        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            tools=tools
            #max_parallel_tools=2
        )
    return agent

def get_tool_list(tools):
    tool_list = []
    for tool in tools:
        if hasattr(tool, 'tool_name'):  # MCP tool
            tool_list.append(tool.tool_name)
                
        if str(tool).startswith("<module 'strands_tools."):   # strands_tools 
            module_name = str(tool).split("'")[1].split('.')[-1]
            tool_list.append(module_name)
    return tool_list

async def initiate_agent(system_prompt, strands_tools, mcp_servers, historyMode):
    global agent, initiated
    global selected_strands_tools, selected_mcp_servers, history_mode, tool_list

    update_required = False
    if selected_strands_tools != strands_tools:
        logger.info("strands_tools update!")
        selected_strands_tools = strands_tools
        update_required = True
        logger.info(f"strands_tools: {strands_tools}")

    if selected_mcp_servers != mcp_servers:
        logger.info("mcp_servers update!")
        selected_mcp_servers = mcp_servers
        update_required = True
        logger.info(f"mcp_servers: {mcp_servers}")

    if history_mode != historyMode:
        logger.info("history_mode update!")
        history_mode = historyMode
        update_required = True
        logger.info(f"history_mode: {history_mode}")

    logger.info(f"initiated: {initiated}, update_required: {update_required}")

    if not initiated or update_required:
        
        init_mcp_clients(mcp_servers)
        tools = update_tools(strands_tools, mcp_servers)
        logger.info(f"tools: {tools}")

        agent = create_agent(system_prompt, tools, history_mode)
        tool_list = get_tool_list(tools)

        if not initiated:
            logger.info("create agent!")
            initiated = True
        else:
            logger.info("update agent!")
            update_required = False

