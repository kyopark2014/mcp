import json
import re
import logging
import sys
import os
import info
import chat
import mcp_config

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,    
    SystemMessage,
    UserMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock    
)

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("claude_agent")

index = 0
def add_notification(containers, message):
    global index

    index += 1

    if containers is not None:
        containers['notification'][index].info(message)
    index += 1

os.environ["CLAUDE_CODE_USE_BEDROCK"] = "1"
os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "4096"

def get_model_id():
    models = []
    model_name = chat.model_name

    models = info.get_model_info(model_name)

    model_id = models[0]["model_id"]
    
    return model_id

def load_multiple_mcp_server_parameters(mcp_json: dict):
    mcpServers = mcp_json.get("mcpServers")
  
    server_info = {}
    if mcpServers is not None:
        for server_name, config in mcpServers.items():
            if config.get("type") == "streamable_http":
                server_info[server_name] = {                    
                    "transport": "streamable_http",
                    "url": config.get("url"),
                    "headers": config.get("headers", {})
                }
            else:
                command = config.get("command", "")
                args = config.get("args", [])
                env = config.get("env", {})
                
                server_info[server_name] = {
                    "transport": "stdio",
                    "command": command,
                    "args": args,
                    "env": env                    
                }
    return server_info

def isKorean(text):
    # check korean
    pattern_hangul = re.compile('[\u3131-\u3163\uac00-\ud7a3]+')
    word_kor = pattern_hangul.search(str(text))
    # print('word_kor: ', word_kor)

    if word_kor and word_kor != 'None':
        # logger.info(f"Korean: {word_kor}")
        return True
    else:
        # logger.info(f"Not Korean:: {word_kor}")
        return False

session_id = None

async def run_claude_agent(prompt, mcp_servers, history_mode, containers):
    global index, session_id
    index = 0
    image_url = []

    logger.info(f"history_mode: {history_mode}")

    logger.info(f"mcp_servers: {mcp_servers}")

    mcp_json = mcp_config.load_selected_config(mcp_servers)
    logger.info(f"mcp_json: {mcp_json}")

    server_params = load_multiple_mcp_server_parameters(mcp_json)
    logger.info(f"server_params: {server_params}")    

    if isKorean(prompt):
        system = (
            "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다."
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다."
            "모르는 질문을 받으면 솔직히 모른다고 말합니다."
            "한국어로 답변하세요."
        )
    else:
        system = (
            "You are a helpful assistant"
            "Provide sufficient specific details for the situation."
            "If you don't know the answer, say you don't know."
        )

    logger.info(f"session_id: {session_id}")
    if session_id is not None and history_mode == "Enable":
        options = ClaudeAgentOptions(
            system_prompt=system,
            max_turns=100,
            permission_mode="bypassPermissions",
            model=get_model_id(),
            mcp_servers=server_params,
            resume=session_id
        )
    else:
       options = ClaudeAgentOptions(
            system_prompt=system,
            max_turns=100,
            permission_mode="bypassPermissions",
            model=get_model_id(),
            mcp_servers=server_params
        ) 
    
    final_result = ""    
    async for message in query(prompt=prompt, options=options):
        # logger.info(message)
        if isinstance(message, SystemMessage):
            logger.info(f"SystemMessage: {message}")
            subtype = message.subtype
            data = message.data
            logger.info(f"SystemMessage: type={subtype}")

            if subtype == "init":
                session_id = message.data.get('session_id')
                logger.info(f"Session started with ID: {session_id}")
                
            if "tools" in data:
                tools = data["tools"]
                logger.info(f"--> tools: {tools}")

                if chat.debug_mode == 'Enable':
                    add_notification(containers, f"Tools: {tools}")

        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    logger.info(f"--> TextBlock: {block.text}")
                    if chat.debug_mode == 'Enable':
                        add_notification(containers, f"{block.text}")
                    final_result = block.text
                elif isinstance(block, ToolUseBlock):
                    logger.info(f"--> tool_use_id: {block.id=}, name: {block.name}, input: {block.input}")
                    if chat.debug_mode == 'Enable':
                        add_notification(containers, f"Tool name: {block.name}, input: {block.input}")
                elif isinstance(block, ToolResultBlock):
                    logger.info(f"--> tool_use_id: {block.tool_use_id=}, content: {block.content}")
                    if chat.debug_mode == 'Enable':
                        add_notification(containers, f"Tool result: {block.content}")
                else:
                    logger.info(f"AssistantMessage: {block}")
                
        elif isinstance(message, UserMessage):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    logger.info(f"--> tool_use_id: {block.tool_use_id=}, content: {block.content}")
                    if chat.debug_mode == 'Enable':
                        add_notification(containers, f"Tool result: {block.content}")
                    
                    if isinstance(block.content, list):
                        for item in block.content:
                            if isinstance(item, dict) and "text" in item:
                                logger.info(f"--> ToolResult: {item['text']}")
                                if "path" in item['text']:
                                    json_path = json.loads(item['text'])
                                    path = json_path.get('path', "")
                                    logger.info(f"path: {path}")
                                    image_url.append(path)
                else:
                    logger.info(f"UserMessage: {block}")
        else:
            logger.info(f"Message: {message}")

    return final_result, image_url
