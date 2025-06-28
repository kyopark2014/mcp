import logging
import sys
import json
import traceback
import chat
import utils

from langgraph.prebuilt import ToolNode
from typing import Literal
from langgraph.graph import START, END, StateGraph
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import ToolNode
from typing import Literal
from langgraph.graph import START, END, StateGraph
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages

logging.basicConfig(
    level=logging.INFO,  
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("agent")

config = utils.load_config()
sharing_url = config["sharing_url"] if "sharing_url" in config else None
s3_prefix = "docs"
capture_prefix = "captures"

status_msg = []
response_msg = []
references = []
image_urls = []
mcp_server_info = {}

index = 0
def add_notification(containers, message):
    global index
    containers['notification'][index].info(message)
    index += 1

def get_status_msg(status):
    global status_msg
    status_msg.append(status)

    if status != "end)":
        status = " -> ".join(status_msg)
        return "[status]\n" + status + "..."
    else: 
        status = " -> ".join(status_msg)
        return "[status]\n" + status

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

                                # ext가 이미지라면 
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

class State(TypedDict):
    messages: Annotated[list, add_messages]
    image_url: list

async def call_model(state: State, config):
    logger.info(f"###### call_model ######")

    last_message = state['messages'][-1]
    logger.info(f"last message: {last_message}")
    
    image_url = state['image_url'] if 'image_url' in state else []

    containers = config.get("configurable", {}).get("containers", None)
    
    tools = config.get("configurable", {}).get("tools", None)
    system_prompt = config.get("configurable", {}).get("system_prompt", None)
    
    if isinstance(last_message, ToolMessage):
        tool_name = last_message.name
        tool_content = last_message.content
        logger.info(f"tool_name: {tool_name}, content: {tool_content[:800]}")

        if chat.debug_mode == "Enable":
            add_notification(containers, f"{tool_name}: {str(tool_content)}")
            response_msg.append(f"{tool_name}: {str(tool_content)}")

        global references
        content, urls, refs = get_tool_info(tool_name, tool_content)
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

        if content:  # manupulate the output of tool message
            messages = state["messages"]
            messages[-1] = ToolMessage(
                name=tool_name,
                tool_call_id=last_message.tool_call_id,
                content=content
            )
            state["messages"] = messages

    if isinstance(last_message, AIMessage) and last_message.content:
        if chat.debug_mode == "Enable":
            containers['status'].info(get_status_msg(f"{last_message.name}"))
            add_notification(containers, f"{last_message.content}")
            response_msg.append(last_message.content)    
    
    if system_prompt:
        system = system_prompt
    else:
        system = (
            "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다."
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다."
            "모르는 질문을 받으면 솔직히 모른다고 말합니다."
            "한국어로 답변하세요."
        )

    chatModel = chat.get_chat(extended_thinking=chat.reasoning_mode)
    model = chatModel.bind_tools(tools)

    try:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        chain = prompt | model
            
        response = await chain.ainvoke(state["messages"])
        logger.info(f"response of call_model: {response}")

    except Exception:
        response = AIMessage(content="답변을 찾지 못하였습니다.")

        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    return {"messages": [response], "image_url": image_url, "index": index}

async def should_continue(state: State, config) -> Literal["continue", "end"]:
    logger.info(f"###### should_continue ######")

    messages = state["messages"]    
    last_message = messages[-1]

    containers = config.get("configurable", {}).get("containers", None)
    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        tool_name = last_message.tool_calls[-1]['name']
        logger.info(f"--- CONTINUE: {tool_name} ---")

        tool_args = last_message.tool_calls[-1]['args']

        if last_message.content:
            logger.info(f"last_message: {last_message.content}")
            if chat.debug_mode == "Enable":
                add_notification(containers, f"{last_message.content}")
                response_msg.append(last_message.content)

        logger.info(f"tool_name: {tool_name}, tool_args: {tool_args}")
        if chat.debug_mode == "Enable":
            add_notification(containers, f"{tool_name}: {tool_args}")
        
        if chat.debug_mode == "Enable":
            containers['status'].info(get_status_msg(f"{tool_name}"))
            if "code" in tool_args:
                logger.info(f"code: {tool_args['code']}")
                add_notification(containers, f"{tool_args['code']}")
                response_msg.append(f"{tool_args['code']}")

        return "continue"
    else:
        if chat.debug_mode == "Enable":
            containers['status'].info(get_status_msg("end)"))

        logger.info(f"--- END ---")
        return "end"

def buildChatAgent(tools):
    tool_node = ToolNode(tools)

    workflow = StateGraph(State)

    workflow.add_node("agent", call_model)
    workflow.add_node("action", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "continue": "action",
            "end": END,
        },
    )
    workflow.add_edge("action", "agent")

    return workflow.compile() 

def buildChatAgentWithHistory(tools):
    tool_node = ToolNode(tools)

    workflow = StateGraph(State)

    workflow.add_node("agent", call_model)
    workflow.add_node("action", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "continue": "action",
            "end": END,
        },
    )
    workflow.add_edge("action", "agent")

    return workflow.compile(
        checkpointer=chat.checkpointer,
        store=chat.memorystore
    )

def load_multiple_mcp_server_parameters():
    logger.info(f"mcp_json: {chat.mcp_json}")

    mcpServers = chat.mcp_json.get("mcpServers")
    logger.info(f"mcpServers: {mcpServers}")
  
    server_info = {}
    if mcpServers is not None:
        command = ""
        args = []
        for server in mcpServers:
            logger.info(f"server: {server}")

            config = mcpServers.get(server)
            logger.info(f"config: {config}")

            if "command" in config:
                command = config["command"]
            if "args" in config:
                args = config["args"]
            if "env" in config:
                env = config["env"]

                server_info[server] = {
                    "command": command,
                    "args": args,
                    "env": env,
                    "transport": "stdio"
                }
            else:
                server_info[server] = {
                    "command": command,
                    "args": args,
                    "transport": "stdio"
                }
    logger.info(f"server_info: {server_info}")

    return server_info

def get_mcp_server_name(too_name):
    mcp_server_name = {}
    for server_name, tools in mcp_server_info:
        tool_names = [tool.name for tool in tools]
        logger.info(f"{server_name}: {tool_names}")
        for name in tool_names:
            mcp_server_name[name] = server_name
    return mcp_server_name[too_name]

def get_mcp_server_list():
    server_lists = []
    for server_name, tools in mcp_server_info:
        server_lists.append(server_name)
    return server_lists

async def run_agent(query, historyMode, containers):
    global status_msg, response_msg, image_urls, references, mcp_server_info
    status_msg = []
    response_msg = []
    image_urls = []
    references = []
    
    if chat.debug_mode == "Enable":
        containers["status"].info(get_status_msg("(start"))

    server_params = load_multiple_mcp_server_parameters()
    logger.info(f"server_params: {server_params}")    

    async with MultiServerMCPClient(server_params) as client:        
        mcp_server_info = client.server_name_to_tools.items()

        tools = client.get_tools()

        if chat.debug_mode == "Enable":
            tool_list = [tool.name for tool in tools]
            containers["tools"].info(f"Tools: {tool_list}")
            logger.info(f"tool_list: {tool_list}")

        if historyMode == "Enable":
            app = buildChatAgentWithHistory(tools)
            config = {
                "recursion_limit": 50,
                "configurable": {"thread_id": chat.userId},
                "containers": containers,
                "tools": tools
            }
        else:
            app = buildChatAgent(tools)
            config = {
                "recursion_limit": 50,
                "containers": containers,
                "tools": tools
            }
        
        inputs = {
            "messages": [HumanMessage(content=query)]
        }
        
        global index
        index = 0

        value = result = None
        final_output = None
        async for output in app.astream(inputs, config):
            for key, value in output.items():
                logger.info(f"--> key: {key}, value: {value}")

                if key == "messages" or key == "agent":
                    if isinstance(value, dict) and "messages" in value:
                        final_output = value
                    elif isinstance(value, list):
                        final_output = {"messages": value, "image_url": []}
                    else:
                        final_output = {"messages": [value], "image_url": []}

        if final_output and "messages" in final_output and len(final_output["messages"]) > 0:
            result = final_output["messages"][-1].content
        else:
            result = "답변을 찾지 못하였습니다."

        logger.info(f"result: {final_output}")
        logger.info(f"references: {references}")
        if references:
            ref = "\n\n### Reference\n"
            for i, reference in enumerate(references):
                ref += f"{i+1}. [{reference['title']}]({reference['url']}), {reference['content']}...\n"    
            result += ref

        image_url = final_output["image_url"] if final_output and "image_url" in final_output else []

        logger.info(f"result: {result}")       
        logger.info(f"image_url: {image_url}")
    
    return result, image_url

async def run_task(question, tools, system_prompt, containers, historyMode, previous_status_msg, previous_response_msg):
    global status_msg, response_msg, references, image_urls
    status_msg = previous_status_msg
    response_msg = previous_response_msg

    if chat.debug_mode == "Enable":
        containers["status"].info(get_status_msg("(start"))

    if historyMode == "Enable":
        app = buildChatAgentWithHistory(tools)
        config = {
            "recursion_limit": 50,
            "configurable": {"thread_id": chat.userId},
            "containers": containers,
            "tools": tools,
            "system_prompt": system_prompt
        }
    else:
        app = buildChatAgent(tools)
        config = {
            "recursion_limit": 50,
            "containers": containers,
            "tools": tools,
            "system_prompt": system_prompt
        }

    value = None
    inputs = {
        "messages": [HumanMessage(content=question)]
    }

    final_output = None
    async for output in app.astream(inputs, config):
        for key, value in output.items():
            logger.info(f"--> key: {key}, value: {value}")
            
            if key == "messages" or key == "agent":
                if isinstance(value, dict) and "messages" in value:
                    final_output = value
                elif isinstance(value, list):
                    final_output = {"messages": value, "image_url": []}
                else:
                    final_output = {"messages": [value], "image_url": []}
                
    if final_output and "messages" in final_output and len(final_output["messages"]) > 0:
        result = final_output["messages"][-1].content
    else:
        result = "답변을 찾지 못하였습니다."

    image_url = final_output["image_url"] if final_output and "image_url" in final_output else []

    return result, image_url, status_msg, response_msg

