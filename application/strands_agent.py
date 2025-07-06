import chat
import os
import contextlib
import mcp_config
import logging
import sys
import json
import utils

from urllib import parse
from contextlib import contextmanager
from typing import Dict, List, Optional
from strands.models import BedrockModel
from strands_tools import calculator, current_time, use_aws
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp import stdio_client, StdioServerParameters
from botocore.config import Config

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("strands-agent")

tool_list = []

update_required = False
initiated = False
strands_tools = []
mcp_servers = []

status_msg = []
response_msg = []
references = []
image_url = []

s3_prefix = "docs"
capture_prefix = "captures"

selected_strands_tools = []
selected_mcp_servers = []

index = 0
def add_notification(containers, message):
    global index
    containers['notification'][index].info(message)
    index += 1

def add_response(containers, message):
    global index
    containers['notification'][index].markdown(message)
    index += 1

status_msg = []
def get_status_msg(status):
    global status_msg
    status_msg.append(status)

    if status != "end)":
        status = " -> ".join(status_msg)
        return "[status]\n" + status + "..."
    else: 
        status = " -> ".join(status_msg)
        return "[status]\n" + status    

#########################################################
# Strands Agent 
#########################################################
def get_model():
    if chat.model_type == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif chat.model_type == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 

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
    aws_region = os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2')

    # Bedrock 클라이언트 설정
    bedrock_config = Config(
        read_timeout=900,
        connect_timeout=900,
        retries=dict(max_attempts=3, mode="adaptive"),
    )

    # 자격 증명이 있는 경우 Bedrock 클라이언트 생성
    if aws_access_key and aws_secret_key:
        import boto3
        bedrock_client = boto3.client(
            'bedrock-runtime',
            region_name=aws_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
            config=bedrock_config
        )
    else:
        # 기본 자격 증명 사용
        import boto3
        bedrock_client = boto3.client(
            'bedrock-runtime',
            region_name=aws_region,
            config=bedrock_config
        )

    if chat.reasoning_mode=='Enable':
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
    else:
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
    return model

conversation_manager = SlidingWindowConversationManager(
    window_size=10,  
)

class MCPClientManager:
    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
        self.client_configs: Dict[str, dict] = {}  # Store client configurations
        
    def add_client(self, name: str, command: str, args: List[str], env: dict[str, str] = {}) -> None:
        """Add a new MCP client configuration (lazy initialization)"""
        self.client_configs[name] = {
            "command": command,
            "args": args,
            "env": env
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
            logger.info(f"Reusing existing MCP client: {name}")
                
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
                    active_contexts.append(client)

            # logger.info(f"active_contexts: {active_contexts}")
            if active_contexts:
                with contextlib.ExitStack() as stack:
                    for client in active_contexts:
                        stack.enter_context(client)
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
        
        name = tool  # Use tool name as client name
        command = server_config["command"]
        args = server_config["args"]
        env = server_config.get("env", {})  # Use empty dict if env is not present
        
        logger.info(f"Adding MCP client - name: {name}, command: {command}, args: {args}, env: {env}")        

        try:
            mcp_manager.add_client(name, command, args, env)
            logger.info(f"Successfully added MCP client for {name}")
        except Exception as e:
            logger.error(f"Failed to add MCP client for {name}: {e}")
            continue

def update_tools(strands_tools: list, mcp_servers: list):
    tools = []
    tool_map = {
        "calculator": calculator,
        "current_time": current_time,
        "use_aws": use_aws
        # "python_repl": python_repl  # Temporarily disabled
    }

    for tool_name in strands_tools:
        if tool_name in tool_map:
            tools.append(tool_map[tool_name])

    # MCP tools
    mcp_servers_loaded = 0
    for mcp_tool in mcp_servers:
        logger.info(f"Processing MCP tool: {mcp_tool}")        
        try:
            with mcp_manager.get_active_clients([mcp_tool]) as _:
                client = mcp_manager.get_client(mcp_tool)
                if client:
                    logger.info(f"Got client for {mcp_tool}, attempting to list tools...")
                    mcp_servers_list = client.list_tools_sync()
                    logger.info(f"{mcp_tool}_tools: {mcp_servers_list}")
                    if mcp_servers_list:
                        tools.extend(mcp_servers_list)
                        mcp_servers_loaded += 1
                        logger.info(f"Successfully added {len(mcp_servers_list)} tools from {mcp_tool}")
                    else:
                        logger.warning(f"No tools returned from {mcp_tool}")
                else:
                    logger.error(f"Failed to get client for {mcp_tool}")
        except Exception as e:
            logger.error(f"Error getting tools for {mcp_tool}: {e}")
            logger.error(f"Exception type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            continue

    logger.info(f"Successfully loaded {mcp_servers_loaded} out of {len(mcp_servers)} MCP tools")
    logger.info(f"tools: {tools}")

    return tools

def create_agent(tools, history_mode):
    system = (
        "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
        "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다." 
        "모르는 질문을 받으면 솔직히 모른다고 말합니다."
    )
    model = get_model()
    if history_mode == "Enable":
        logger.info("history_mode: Enable")
        agent = Agent(
            model=model,
            system_prompt=system,
            tools=tools,
            conversation_manager=conversation_manager
        )
    else:
        logger.info("history_mode: Disable")
        agent = Agent(
            model=model,
            system_prompt=system,
            tools=tools
            #max_parallel_tools=2
        )
    return agent

def get_tool_info(tool_name, tool_content):
    tool_references = []    
    urls = []
    content = ""

    # tavily
    if isinstance(tool_content, str) and "Title:" in tool_content and "URL:" in tool_content and "Content:" in tool_content:
        logger.info("Tavily parsing...")
        items = tool_content.split("\n\n")
        for i, item in enumerate(items):
            # logger.info(f"item[{i}]: {item}")
            if "Title:" in item and "URL:" in item and "Content:" in item:
                try:
                    title_part = item.split("Title:")[1].split("URL:")[0].strip()
                    url_part = item.split("URL:")[1].split("Content:")[0].strip()
                    content_part = item.split("Content:")[1].strip().replace("\n", "")
                    
                    logger.info(f"title_part: {title_part}")
                    logger.info(f"url_part: {url_part}")
                    logger.info(f"content_part: {content_part}")

                    content += f"{content_part}\n\n"
                    
                    tool_references.append({
                        "url": url_part,
                        "title": title_part,
                        "content": content_part[:100] + "..." if len(content_part) > 100 else content_part
                    })
                except Exception as e:
                    logger.info(f"Parsing error: {str(e)}")
                    continue                

    # OpenSearch
    elif tool_name == "SearchIndexTool": 
        if ":" in tool_content:
            extracted_json_data = tool_content.split(":", 1)[1].strip()
            try:
                json_data = json.loads(extracted_json_data)
                # logger.info(f"extracted_json_data: {extracted_json_data[:200]}")
            except json.JSONDecodeError:
                logger.info("JSON parsing error")
                json_data = {}
        else:
            json_data = {}
        
        if "hits" in json_data:
            hits = json_data["hits"]["hits"]
            if hits:
                logger.info(f"hits[0]: {hits[0]}")

            for hit in hits:
                text = hit["_source"]["text"]
                metadata = hit["_source"]["metadata"]
                
                content += f"{text}\n\n"

                filename = metadata["name"].split("/")[-1]
                # logger.info(f"filename: {filename}")
                
                content_part = text.replace("\n", "")
                tool_references.append({
                    "url": metadata["url"], 
                    "title": filename,
                    "content": content_part[:100] + "..." if len(content_part) > 100 else content_part
                })
                
        logger.info(f"content: {content}")
        
    # Knowledge Base
    elif tool_name == "QueryKnowledgeBases": 
        try:
            # Handle case where tool_content contains multiple JSON objects
            if tool_content.strip().startswith('{'):
                # Parse each JSON object individually
                json_objects = []
                current_pos = 0
                brace_count = 0
                start_pos = -1
                
                for i, char in enumerate(tool_content):
                    if char == '{':
                        if brace_count == 0:
                            start_pos = i
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0 and start_pos != -1:
                            try:
                                json_obj = json.loads(tool_content[start_pos:i+1])
                                # logger.info(f"json_obj: {json_obj}")
                                json_objects.append(json_obj)
                            except json.JSONDecodeError:
                                logger.info(f"JSON parsing error: {tool_content[start_pos:i+1][:100]}")
                            start_pos = -1
                
                json_data = json_objects
            else:
                # Try original method
                json_data = json.loads(tool_content)                
            # logger.info(f"json_data: {json_data}")

            # Build content
            if isinstance(json_data, list):
                for item in json_data:
                    if isinstance(item, dict) and "content" in item:
                        content_text = item["content"].get("text", "")
                        content += content_text + "\n\n"

                        uri = "" 
                        if "location" in item:
                            if "s3Location" in item["location"]:
                                uri = item["location"]["s3Location"]["uri"]
                                # logger.info(f"uri (list): {uri}")
                                ext = uri.split(".")[-1]

                                # if ext is an image 
                                sharing_url = utils.sharing_url
                                url = sharing_url + "/" + s3_prefix + "/" + uri.split("/")[-1]
                                if ext in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "ico", "webp"]:
                                    url = sharing_url + "/" + capture_prefix + "/" + uri.split("/")[-1]
                                logger.info(f"url: {url}")
                                
                                tool_references.append({
                                    "url": url, 
                                    "title": uri.split("/")[-1],
                                    "content": content_text[:100] + "..." if len(content_text) > 100 else content_text
                                })          
                
        except json.JSONDecodeError as e:
            logger.info(f"JSON parsing error: {e}")
            json_data = {}
            content = tool_content  # Use original content if parsing fails

        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")

    # aws document
    elif tool_name == "search_documentation":
        try:
            json_data = json.loads(tool_content)
            for item in json_data:
                logger.info(f"item: {item}")
                
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        logger.info(f"Failed to parse item as JSON: {item}")
                        continue
                
                if isinstance(item, dict) and 'url' in item and 'title' in item:
                    url = item['url']
                    title = item['title']
                    content_text = item['context'][:100] + "..." if len(item['context']) > 100 else item['context']
                    tool_references.append({
                        "url": url,
                        "title": title,
                        "content": content_text
                    })
                else:
                    logger.info(f"Invalid item format: {item}")
                    
        except json.JSONDecodeError:
            logger.info(f"JSON parsing error: {tool_content}")
            pass

        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")
            
    # ArXiv
    elif tool_name == "search_papers" and "papers" in tool_content:
        try:
            json_data = json.loads(tool_content)

            papers = json_data['papers']
            for paper in papers:
                url = paper['url']
                title = paper['title']
                abstract = paper['abstract'].replace("\n", "")
                content_text = abstract[:100] + "..." if len(abstract) > 100 else abstract
                content += f"{content_text}\n\n"
                logger.info(f"url: {url}, title: {title}, content: {content_text}")

                tool_references.append({
                    "url": url,
                    "title": title,
                    "content": content_text
                })
        except json.JSONDecodeError:
            logger.info(f"JSON parsing error: {tool_content}")
            pass

        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")

    else:        
        try:
            if isinstance(tool_content, dict):
                json_data = tool_content
            elif isinstance(tool_content, list):
                json_data = tool_content
            else:
                json_data = json.loads(tool_content)
            
            logger.info(f"json_data: {json_data}")
            if isinstance(json_data, dict) and "path" in json_data:  # path
                path = json_data["path"]
                if isinstance(path, list):
                    for url in path:
                        urls.append(url)
                else:
                    urls.append(path)            

            for item in json_data:
                logger.info(f"item: {item}")
                if "reference" in item and "contents" in item:
                    url = item["reference"]["url"]
                    title = item["reference"]["title"]
                    content_text = item["contents"][:100] + "..." if len(item["contents"]) > 100 else item["contents"]
                    tool_references.append({
                        "url": url,
                        "title": title,
                        "content": content_text
                    })
            logger.info(f"tool_references: {tool_references}")

        except json.JSONDecodeError:
            pass

    return content, urls, tool_references

def get_tool_list(tools):
    tool_list = []
    for tool in tools:
        if hasattr(tool, 'tool_name'):  # MCP tool
            tool_list.append(tool.tool_name)
                
        if str(tool).startswith("<module 'strands_tools."):   # strands_tools 
            module_name = str(tool).split("'")[1].split('.')[-1]
            tool_list.append(module_name)
    return tool_list

async def run_agent(question, strands_tools, mcp_servers, historyMode, containers):
    result = ""
    current_response = ""

    global references, image_url
    image_url = []    
    references = []

    global status_msg
    status_msg = []

    global agent, initiated, update_required, tool_list
    global selected_strands_tools, selected_mcp_servers

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

    if not initiated: 
        logger.info("create agent!")
        init_mcp_clients(mcp_servers)
        tools = update_tools(strands_tools, mcp_servers)
        logger.info(f"tools: {tools}")

        agent = create_agent(tools, historyMode)
        tool_list = get_tool_list(tools)
        if chat.debug_mode == 'Enable':
            containers['tools'].info(f"Tools: {tool_list}")
        initiated = True
    elif update_required:      
        logger.info(f"update_required: {update_required}")
        logger.info("update agent!")
        init_mcp_clients(mcp_servers)
        tools = update_tools(strands_tools, mcp_servers)
        logger.info(f"tools: {tools}")

        agent = create_agent(tools, historyMode)
        tool_list = get_tool_list(tools)
        if chat.debug_mode == 'Enable':
            containers['tools'].info(f"Tools: {tool_list}")
        update_required = False
    else:
        if chat.debug_mode == 'Enable':
            containers['tools'].info(f"tool_list: {tool_list}")
    
    if chat.debug_mode == 'Enable':
        containers['status'].info(get_status_msg(f"(start"))    

    with mcp_manager.get_active_clients(mcp_servers) as _:
        agent_stream = agent.stream_async(question)
        
        tool_name = ""
        async for event in agent_stream:
            # logger.info(f"event: {event}")
            if "message" in event:
                message = event["message"]
                logger.info(f"message: {message}")

                for content in message["content"]:                
                    if "text" in content:
                        logger.info(f"text: {content['text']}")
                        if chat.debug_mode == 'Enable':
                            add_response(containers, content['text'])

                        result = content['text']
                        current_response = ""

                    if "toolUse" in content:
                        tool_use = content["toolUse"]
                        logger.info(f"tool_use: {tool_use}")
                        
                        tool_name = tool_use["name"]
                        input = tool_use["input"]
                        
                        logger.info(f"tool_nmae: {tool_name}, arg: {input}")
                        if chat.debug_mode == 'Enable':       
                            add_notification(containers, f"tool name: {tool_name}, arg: {input}")
                            containers['status'].info(get_status_msg(f"{tool_name}"))
                
                    if "toolResult" in content:
                        tool_result = content["toolResult"]
                        logger.info(f"tool_name: {tool_name}")
                        logger.info(f"tool_result: {tool_result}")
                        if "content" in tool_result:
                            tool_content = tool_result['content']
                            for content in tool_content:
                                if "text" in content:
                                    if chat.debug_mode == 'Enable':
                                        add_notification(containers, f"tool result: {content['text']}")

                                    try:
                                        json_data = json.loads(content['text'])
                                        if isinstance(json_data, dict) and "path" in json_data:
                                            paths = json_data["path"]
                                            logger.info(f"paths: {paths}")
                                            for path in paths:
                                                if path.startswith("http"):
                                                    image_url.append(path)
                                                    logger.info(f"Added image URL: {path}")
                                    except json.JSONDecodeError:
                                        pass

                                    content, urls, refs = get_tool_info(tool_name, content['text'])
                                    logger.info(f"content: {content}")
                                    logger.info(f"urls: {urls}")
                                    logger.info(f"refs: {refs}")

                                    if refs:
                                        for r in refs:
                                            references.append(r)
                                        logger.info(f"refs: {refs}")
                                    if urls:
                                        for url in urls:
                                            image_url.append(url)
                                        logger.info(f"urls: {urls}")

                                        if chat.debug_mode == "Enable":
                                            add_notification(containers, f"Added path to image_url: {urls}")
                                            response_msg.append(f"Added path to image_url: {urls}")
                                        
            if "event_loop_metrics" in event and \
                hasattr(event["event_loop_metrics"], "tool_metrics") and \
                "generate_image_with_colors" in event["event_loop_metrics"].tool_metrics:
                tool_info = event["event_loop_metrics"].tool_metrics["generate_image_with_colors"].tool
                if "input" in tool_info and "filename" in tool_info["input"]:
                    fname = tool_info["input"]["filename"]
                    if fname:
                        url = f"{chat.path}/{chat.s3_image_prefix}/{parse.quote(fname)}.png"
                        if url not in image_url:
                            image_url.append(url)
                            logger.info(f"Added image URL: {url}")

            if "data" in event:
                text_data = event["data"]
                current_response += text_data

                if chat.debug_mode == 'Enable':
                    containers["notification"][index].markdown(current_response)
                continue

    if chat.debug_mode == 'Enable':
        containers['status'].info(get_status_msg(f"end)"))

    ref = ""
    if references:
        ref = "\n\n### Reference\n"
        for i, reference in enumerate(references):
            ref += f"{i+1}. [{reference['title']}]({reference['url']}), {reference['content']}...\n"    

        # show reference
        if chat.debug_mode == 'Enable':
            containers['notification'][index-1].markdown(result+ref)

    return result+ref, image_url

async def run_task(question, strands_tools, mcp_servers, system_prompt, containers, historyMode, previous_status_msg, previous_response_msg):
    global status_msg, response_msg
    status_msg = previous_status_msg
    response_msg = previous_response_msg

    result = ""
    current_response = ""

    global references, image_url
    image_url = []    
    references = []

    logger.info(f"mcp_servers: {mcp_servers}")
    init_mcp_clients(mcp_servers)
    tools = update_tools(strands_tools, mcp_servers)
    logger.info(f"tools: {tools}")
    agent = create_agent(tools, historyMode)

    tool_list = get_tool_list(tools)
    logger.info(f"tool_list: {tool_list}")

    if chat.debug_mode == 'Enable':
        containers['tools'].info(f"Tools: {tool_list}")

    logger.info(f"tool_list: {tool_list}")

    with mcp_manager.get_active_clients(mcp_servers) as _:
        agent_stream = agent.stream_async(question)
        
        tool_name = ""
        async for event in agent_stream:
            # logger.info(f"event: {event}")
            if "message" in event:
                message = event["message"]
                logger.info(f"message: {message}")

                for content in message["content"]:                
                    if "text" in content:
                        logger.info(f"text: {content['text']}")
                        if chat.debug_mode == 'Enable':
                            add_response(containers, content['text'])

                        result = content['text']
                        current_response = ""

                    if "toolUse" in content:
                        tool_use = content["toolUse"]
                        logger.info(f"tool_use: {tool_use}")
                        
                        tool_name = tool_use["name"]
                        input = tool_use["input"]
                        
                        logger.info(f"tool_nmae: {tool_name}, arg: {input}")
                        if chat.debug_mode == 'Enable':       
                            add_notification(containers, f"tool name: {tool_name}, arg: {input}")
                            containers['status'].info(get_status_msg(f"{tool_name}"))
                
                    if "toolResult" in content:
                        tool_result = content["toolResult"]
                        logger.info(f"tool_name: {tool_name}")
                        logger.info(f"tool_result: {tool_result}")
                        if "content" in tool_result:
                            tool_content = tool_result['content']
                            for content in tool_content:
                                if "text" in content:
                                    if chat.debug_mode == 'Enable':
                                        add_notification(containers, f"tool result: {content['text']}")

                                    try:
                                        json_data = json.loads(content['text'])
                                        if isinstance(json_data, dict) and "path" in json_data:
                                            paths = json_data["path"]
                                            logger.info(f"paths: {paths}")
                                            for path in paths:
                                                if path.startswith("http"):
                                                    image_url.append(path)
                                                    logger.info(f"Added image URL: {path}")
                                    except json.JSONDecodeError:
                                        pass

                                    content, urls, refs = get_tool_info(tool_name, content['text'])
                                    logger.info(f"content: {content}")
                                    logger.info(f"urls: {urls}")
                                    logger.info(f"refs: {refs}")

                                    if refs:
                                        for r in refs:
                                            references.append(r)
                                        logger.info(f"refs: {refs}")
                                    if urls:
                                        for url in urls:
                                            image_url.append(url)
                                        logger.info(f"urls: {urls}")

                                        if chat.debug_mode == "Enable":
                                            add_notification(containers, f"Added path to image_url: {urls}")
                                            response_msg.append(f"Added path to image_url: {urls}")
                                        
            if "event_loop_metrics" in event and \
                hasattr(event["event_loop_metrics"], "tool_metrics") and \
                "generate_image_with_colors" in event["event_loop_metrics"].tool_metrics:
                tool_info = event["event_loop_metrics"].tool_metrics["generate_image_with_colors"].tool
                if "input" in tool_info and "filename" in tool_info["input"]:
                    fname = tool_info["input"]["filename"]
                    if fname:
                        url = f"{chat.path}/{chat.s3_image_prefix}/{parse.quote(fname)}.png"
                        if url not in image_url:
                            image_url.append(url)
                            logger.info(f"Added image URL: {url}")

            if "data" in event:
                text_data = event["data"]
                current_response += text_data

                if chat.debug_mode == 'Enable':
                    containers["notification"][index].markdown(current_response)
                continue

    if chat.debug_mode == 'Enable':
        containers['status'].info(get_status_msg(f"end)"))

    ref = ""
    if references:
        ref = "\n\n### Reference\n"
        for i, reference in enumerate(references):
            ref += f"{i+1}. [{reference['title']}]({reference['url']}), {reference['content']}...\n"    

        # show reference
        if chat.debug_mode == 'Enable':
            containers['notification'][index-1].markdown(result+ref)

    return result, image_url, status_msg, response_msg

