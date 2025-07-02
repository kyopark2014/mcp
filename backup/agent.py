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
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
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

index = 0
def add_notification(container, message):
    global index
    container['notification'][index].info(message)
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

response_msg = []
references = []
image_urls = []

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

def extract_reference(response):
    references = []
    for i, re in enumerate(response):
        if isinstance(re, ToolMessage):
            logger.info(f"###### extract_reference ######")
            try: 
                
                # check json format
                if isinstance(re.content, str) and (re.content.strip().startswith('{') or re.content.strip().startswith('[')):
                    tool_result = json.loads(re.content)
                    # logger.info(f"tool_result: {tool_result}")
                else:
                    tool_result = re.content
                    # logger.info(f"tool_result (not JSON): {tool_result[:200]}")
                                
                if isinstance(tool_result, list):
                    logger.info(f"size of tool_result: {len(tool_result)}")
                    for i, item in enumerate(tool_result):
                        logger.info(f'item[{i}]: {item}')
                        
                        # RAG
                        if "reference" in item:
                            logger.info(f"reference: {item['reference']}")

                            infos = item['reference']
                            url = infos['url']
                            title = infos['title']
                            source = infos['from']
                            logger.info(f"url: {url}, title: {title}, source: {source}")

                            references.append({
                                "url": url,
                                "title": title,
                                "content": item['contents'][:100].replace("\n", "")
                            })

                        # Others               
                        if isinstance(item, str):
                            try:
                                item = json.loads(item)

                                # AWS Document
                                if "rank_order" in item:
                                    references.append({
                                        "url": item['url'],
                                        "title": item['title'],
                                        "content": item['context'][:100].replace("\n", "")
                                  })
                            except json.JSONDecodeError:
                                logger.info(f"JSON parsing error: {item}")
                                continue

            except:
                logger.info(f"fail to parsing..")
                pass
    return references

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
                    message = value["messages"]
                    final_output = value
                elif isinstance(value, list):
                    value = {"messages": value, "image_url": []}
                    message = value["messages"]
                    final_output = value
                else:
                    value = {"messages": [value], "image_url": []}
                    message = value["messages"]
                    final_output = value

                refs = extract_reference(message)
                if refs:
                    for r in refs:
                        references.append(r)
                        logger.info(f"r: {r}")
                
    if final_output and "messages" in final_output and len(final_output["messages"]) > 0:
        result = final_output["messages"][-1].content
    else:
        result = "답변을 찾지 못하였습니다."

    image_url = final_output["image_url"] if final_output and "image_url" in final_output else []

    return result, image_url, status_msg, response_msg

def status_messages(message):
    # type of message
    if isinstance(message, AIMessage):
        logger.info(f"status_messages (AIMessage): {message}")
    elif isinstance(message, ToolMessage):
        logger.info(f"status_messages (ToolMessage): {message}")
    elif isinstance(message, HumanMessage):
        logger.info(f"status_messages (HumanMessage): {message}")

    if isinstance(message, AIMessage):
        if message.content:
            logger.info(f"content: {message.content}")
            content = message.content
            if len(content) > 500:
                content = content[:500] + "..."       
            push_debug_messages("text", content)
        if hasattr(message, 'tool_calls') and message.tool_calls:
            logger.info(f"Tool name: {message.tool_calls[0]['name']}")
                
            if 'args' in message.tool_calls[0]:
                logger.info(f"Tool args: {message.tool_calls[0]['args']}")
                    
                args = message.tool_calls[0]['args']
                if 'code' in args:
                    logger.info(f"code: {args['code']}")
                    push_debug_messages("text", args['code'])
                elif message.tool_calls[0]['args']:
                    status = f"Tool name: {message.tool_calls[0]['name']}  \nTool args: {message.tool_calls[0]['args']}"
                    logger.info(f"status: {status}")
                    push_debug_messages("text", status)

    elif isinstance(message, ToolMessage):
        if message.name:
            logger.info(f"Tool name: {message.name}")
            
            if message.content:                
                content = message.content
                if len(content) > 500:
                    content = content[:500] + "..."
                logger.info(f"Tool result: {content}")                
                status = f"Tool name: {message.name}  \nTool result: {content}"
            else:
                status = f"Tool name: {message.name}"

            logger.info(f"status: {status}")
            push_debug_messages("text", status)

####################### Agent #######################
# Agent 
#####################################################
def create_agent(tools, historyMode):
    tool_node = ToolNode(tools)

    chatModel = chat.get_chat(extended_thinking=chat.reasoning_mode)
    model = chatModel.bind_tools(tools)

    class State(TypedDict):
        messages: Annotated[list, add_messages]
        image_url: list

    def call_model(state: State, config):
        logger.info(f"###### call_model ######")
        logger.info(f"state: {state['messages']}")

        last_message = state['messages'][-1].content
        logger.info(f"last message: {last_message}")
        
        # get image_url from state
        image_url = state['image_url'] if 'image_url' in state else []
        if isinstance(last_message, str) and (last_message.strip().startswith('{') or last_message.strip().startswith('[')):
            try:                 
                tool_result = json.loads(last_message)
                if "path" in tool_result:
                    logger.info(f"path: {tool_result['path']}")

                    path = tool_result['path']
                    if isinstance(path, list):
                        for p in path:
                            logger.info(f"image: {p}")
                            #if p.startswith('http') or p.startswith('https'):
                            image_url.append(p)
                    else:
                        logger.info(f"image: {path}")
                        #if path.startswith('http') or path.startswith('https'):
                        image_url.append(path)
            except json.JSONDecodeError:
                tool_result = last_message
        if image_url:
            logger.info(f"image_url: {image_url}")

        if chat.isKorean(state["messages"][0].content)==True:
            system = (
                "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다."
                "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다."
                "모르는 질문을 받으면 솔직히 모른다고 말합니다."
                "한국어로 답변하세요."
            )
        else: 
            system = (            
                "You are a conversational AI designed to answer in a friendly way to a question."
                "If you don't know the answer, just say that you don't know, don't try to make up an answer."
            )

        try:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", system),
                    MessagesPlaceholder(variable_name="messages"),
                ]
            )
            chain = prompt | model
                
            response = chain.invoke(state["messages"])
            # logger.info(f"call_model response: {response}")
            logger.info(f"call_model: {response.content}")

        except Exception:
            response = AIMessage(content="답변을 찾지 못하였습니다.")

            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")
            # raise Exception ("Not able to request to LLM")

        return {"messages": [response], "image_url": image_url}

    def should_continue(state: State) -> Literal["continue", "end"]:
        logger.info(f"###### should_continue ######")

        messages = state["messages"]    
        last_message = messages[-1]
        
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            tool_name = last_message.tool_calls[-1]['name']
            logger.info(f"--- CONTINUE: {tool_name} ---")

            if chat.debug_mode == "Enable":
                status_messages(last_message)

            return "continue"
        else:
            logger.info(f"--- END ---")
            return "end"

    def buildChatAgent():
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
    
    def buildChatAgentWithHistory():
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
    
    # workflow 
    if historyMode == "Enable":
        app = buildChatAgentWithHistory()
        config = {
            "recursion_limit": 50,
            "configurable": {"thread_id": chat.userId}
        }
    else:
        app = buildChatAgent()
        config = {
            "recursion_limit": 50
        }

    return app, config

# server_params = StdioServerParameters(
#   command="python",
#   args=["application/mcp-server.py"],
# )

def load_mcp_server_parameters():
    logger.info(f"mcp_json: {chat.mcp_json}")

    mcpServers = chat.mcp_json.get("mcpServers")
    logger.info(f"mcpServers: {mcpServers}")

    command = ""
    args = []
    if mcpServers is not None:
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

            break

    return StdioServerParameters(
        command=command,
        args=args,
        env=env
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

def tool_info(tools, st):
    tool_info = ""
    tool_list = []
    # st.info("Getting tool information.")
    for tool in tools:
        tool_info += f"name: {tool.name}\n"    
        if hasattr(tool, 'description'):
            tool_info += f"description: {tool.description}\n"
        tool_info += f"args_schema: {tool.args_schema}\n\n"
        tool_list.append(tool.name)
    # st.info(f"{tool_info}")
    st.info(f"Tools: {tool_list}")

def extract_reference(response):
    references = []
    for i, re in enumerate(response):
        logger.info(f"message[{i}]: {re}")

        if i==len(response)-1:
            break

        if isinstance(re, ToolMessage):            
            try: 
                # tavily
                if isinstance(re.content, str) and "Title:" in re.content and "URL:" in re.content and "Content:" in re.content:
                    logger.info("Tavily parsing...")                    
                    items = re.content.split("\n\n")
                    for i, item in enumerate(items):
                        logger.info(f"item[{i}]: {item}")
                        if "Title:" in item and "URL:" in item and "Content:" in item:
                            try:
                                title_part = item.split("Title:")[1].split("URL:")[0].strip()
                                url_part = item.split("URL:")[1].split("Content:")[0].strip()
                                content_part = item.split("Content:")[1].strip()
                                
                                logger.info(f"title_part: {title_part}")
                                logger.info(f"url_part: {url_part}")
                                logger.info(f"content_part: {content_part}")
                                
                                references.append({
                                    "url": url_part,
                                    "title": title_part,
                                    "content": content_part[:100] + "..." if len(content_part) > 100 else content_part
                                })
                            except Exception as e:
                                logger.info(f"파싱 오류: {str(e)}")
                                continue
                
                # check json format
                if isinstance(re.content, str) and (re.content.strip().startswith('{') or re.content.strip().startswith('[')):
                    tool_result = json.loads(re.content)
                    logger.info(f"tool_result: {tool_result}")
                else:
                    tool_result = re.content
                    logger.info(f"tool_result (not JSON): {tool_result}")

                # ArXiv
                if "papers" in tool_result:
                    logger.info(f"size of papers: {len(tool_result['papers'])}")

                    papers = tool_result['papers']
                    for paper in papers:
                        url = paper['url']
                        title = paper['title']
                        content = paper['abstract'][:100]
                        logger.info(f"url: {url}, title: {title}, content: {content}")

                        references.append({
                            "url": url,
                            "title": title,
                            "content": content
                        })
                                
                if isinstance(tool_result, list):
                    logger.info(f"size of tool_result: {len(tool_result)}")
                    for i, item in enumerate(tool_result):
                        logger.info(f'item[{i}]: {item}')
                        
                        # RAG
                        if "reference" in item:
                            logger.info(f"reference: {item['reference']}")

                            infos = item['reference']
                            url = infos['url']
                            title = infos['title']
                            source = infos['from']
                            logger.info(f"url: {url}, title: {title}, source: {source}")

                            references.append({
                                "url": url,
                                "title": title,
                                "content": item['contents'][:100]
                            })

                        # Others               
                        if isinstance(item, str):
                            try:
                                item = json.loads(item)

                                # AWS Document
                                if "rank_order" in item:
                                    references.append({
                                        "url": item['url'],
                                        "title": item['title'],
                                        "content": item['context'][:100]
                                    })
                            except json.JSONDecodeError:
                                logger.info(f"JSON parsing error: {item}")
                                continue

            except:
                logger.info(f"fail to parsing..")
                pass
    return references

def get_debug_messages():
    global debug_messages
    messages = debug_messages.copy()
    debug_messages = []  # Clear messages after returning
    return messages

def push_debug_messages(type, contents):
    global debug_messages
    debug_messages.append({
        type: contents
    })

def extract_thinking_tag(response, st):
    if response.find('<thinking>') != -1:
        status = response[response.find('<thinking>')+10:response.find('</thinking>')]
        logger.info(f"gent_thinking: {status}")
        
        if chat.debug_mode=="Enable":
            st.info(status)

        if response.find('<thinking>') == 0:
            msg = response[response.find('</thinking>')+12:]
        else:
            msg = response[:response.find('<thinking>')]
        logger.info(f"msg: {msg}")
    else:
        msg = response

    return msg

async def mcp_rag_agent_multiple(query, historyMode, st):
    server_params = load_multiple_mcp_server_parameters()
    logger.info(f"server_params: {server_params}")

    async with MultiServerMCPClient(server_params) as client:
        ref = ""
        with st.status("thinking...", expanded=True, state="running") as status:
            tools = client.get_tools()
            if chat.debug_mode == "Enable":
                tool_info(tools, st)
                logger.info(f"tools: {tools}")

            # react agent
            # model = get_chat(extended_thinking="Disable")
            # agent = create_react_agent(model, client.get_tools())

            # langgraph agent
            agent, config = create_agent(tools, historyMode)

            try:
                response = await agent.ainvoke({"messages": query}, config)
                logger.info(f"response: {response}")

                result = response["messages"][-1].content
                # logger.info(f"result: {result}")

                debug_msgs = get_debug_messages()
                for msg in debug_msgs:
                    logger.info(f"debug_msg: {msg}")
                    if "image" in msg:
                        st.image(msg["image"])
                    elif "text" in msg:
                        st.info(msg["text"])

                image_url = response["image_url"] if "image_url" in response else []
                logger.info(f"image_url: {image_url}")

                for image in image_url:
                    st.image(image)

                if chat.model_type == "nova":
                    result = extract_thinking_tag(result, st) # for nova

                references = extract_reference(response["messages"])                
                if references:
                    ref = "\n\n### Reference\n"
                    for i, reference in enumerate(references):
                        ref += f"{i+1}. [{reference['title']}]({reference['url']}), {reference['content']}...\n"    
                    logger.info(f"ref: {ref}")
                    result += ref

                st.markdown(result)

                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": result,
                    "images": image_url if image_url else []
                })

                return result
            except Exception as e:
                logger.error(f"Error during agent invocation: {str(e)}")
                raise Exception(f"Agent invocation failed: {str(e)}")

async def mcp_rag_agent_single(query, historyMode, st):
    server_params = load_mcp_server_parameters()
    logger.info(f"server_params: {server_params}")

    async with stdio_client(server_params) as (read, write):
        # Open an MCP session to interact with the math_server.py tool.
        async with ClientSession(read, write) as session:
            # Initialize the session.
            await session.initialize()

            logger.info(f"query: {query}")
            
            # Load tools
            tools = await load_mcp_tools(session)
            logger.info(f"tools: {tools}")

            with st.status("thinking...", expanded=True, state="running") as status:       
                if chat.debug_mode == "Enable":
                    tool_info(tools, st)

                agent = create_agent(tools, historyMode)
                
                # Run the agent.            
                agent_response = await agent.ainvoke({"messages": query})                
                logger.info(f"agent_response: {agent_response}")

                if chat.debug_mode == "Enable":
                    for i, re in enumerate(agent_response["messages"]):
                        if i==0 or i==len(agent_response["messages"])-1:
                            continue
                        
                        if isinstance(re, AIMessage):
                            if re.content:
                                st.info(f"Agent: {re.content}")
                            if re.tool_calls:
                                for tool_call in re.tool_calls:
                                    st.info(f"Agent: {tool_call['name']}, {tool_call['args']}")
                        # elif isinstance(re, ToolMessage):
                        #     st.info(f"Tool: {re.content}")
                
                result = agent_response["messages"][-1].content
                logger.info(f"result: {result}")

            # st.info(f"Agent: {result}")

            st.markdown(result)
            st.session_state.messages.append({
                "role": "assistant", 
                "content": result
            })
            
            return result

async def run_agent(query, historyMode, containers):
    global status_msg, response_msg, references, image_urls
    status_msg = []
    response_msg = []
    references = []
    image_urls = []

    if chat.debug_mode == "Enable":
        containers["status"].info(get_status_msg("(start"))

    server_params = load_multiple_mcp_server_parameters()
    logger.info(f"server_params: {server_params}")

    async with MultiServerMCPClient(server_params) as client:        
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
                        message = value["messages"]
                        final_output = value
                    elif isinstance(value, list):
                        value = {"messages": value, "image_url": []}
                        message = value["messages"]
                        final_output = value
                    else:
                        value = {"messages": [value], "image_url": []}
                        message = value["messages"]
                        final_output = value

                    refs = extract_reference(message)
                    if refs:
                        for r in refs:
                            references.append(r)
                            logger.info(f"r: {r}")
                    
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
