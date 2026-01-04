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
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,    
    SystemMessage,
    UserMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    ToolPermissionContext,
    PermissionResultAllow,
    PermissionResultDeny
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

def add_system_message(containers, message, type):
    global index
    index += 1

    if containers is not None:
        if type == "markdown":
            containers['notification'][index].markdown(message)
        elif type == "info":
            containers['notification'][index].info(message)

# Claude Code environment variables
os.environ["CLAUDE_CODE_USE_BEDROCK"] = "1"
os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "16384"  # Claude 4 Sonnet max: 128000

# WebSocket error prevention
import tempfile

# WebSocket mocking script generation
websocket_mock_script = '''
if (typeof window === 'undefined') {
    global.window = {
        WebSocket: function() {
            return {
                readyState: 1,
                close: function() {},
                send: function() {},
                addEventListener: function() {},
                removeEventListener: function() {}
            };
        }
    };
}
'''

# Save WebSocket mocking script to temporary file
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
    f.write(websocket_mock_script)
    websocket_mock_file = f.name

# Add WebSocket mocking file to Node.js options
os.environ["NODE_OPTIONS"] = f"--require {websocket_mock_file}"

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
                # Convert streamable_http to http type for Claude Agent SDK compatibility
                server_info[server_name] = {                    
                    "type": "http",
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
    # Check if text contains Korean characters
    pattern_hangul = re.compile('[\u3131-\u3163\uac00-\ud7a3]+')
    word_kor = pattern_hangul.search(str(text))

    if word_kor and word_kor != 'None':
        return True
    else:
        return False

session_id = None

async def prompt_for_tool_approval(tool_name: str, input_params: dict, context: ToolPermissionContext):
    logger.info(f"Tool Request:")
    logger.info(f"Tool: {tool_name}")
    logger.info(f"Context: {context}")
    
    # Display parameters
    if input_params:
        params = "Parameters:\n"
        logger.info("Parameters:")
        for key, value in input_params.items():
            display_value = value
            if isinstance(value, str) and len(value) > 100:
                display_value = value[:100] + "..."
            elif isinstance(value, (dict, list)):
                display_value = json.dumps(value, indent=2)
            logger.info(f"{key}: {display_value}")
            params += f"{key}: {display_value}\n"

    # Get user approval
    # answer = input("\n   Approve this tool use? (y/n): ")    
    # if answer.lower() in ['y', 'yes']:
    #     logger.info("✅ Approved")
    #     return PermissionResultAllow(updated_input=input_params)
    # else:
    #     logger.info("❌ Denied")
    #     return PermissionResultDeny(message="User denied permission for this tool")
    
    # Auto-approve for streamlit app
    return PermissionResultAllow(updated_input=input_params)

async def run_claude_agent(prompt, mcp_servers, history_mode, containers):
    global index, session_id
    index = 0
    image_url = []

    logger.info(f"history_mode: {history_mode}")

    logger.info(f"mcp_servers: {mcp_servers}")

    mcp_config.bearer_token = None
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
            permission_mode="default", # "default", "acceptEdits", "plan", "bypassPermissions"
            model=get_model_id(),
            mcp_servers=server_params,
            resume=session_id,
            can_use_tool=prompt_for_tool_approval,
            setting_sources=["project"]
        )
    else:
       options = ClaudeAgentOptions(
            system_prompt=system,
            max_turns=100,
            permission_mode="default", 
            model=get_model_id(),
            mcp_servers=server_params,
            can_use_tool=prompt_for_tool_approval,
            setting_sources=["project"]
        ) 
    
    final_result = ""    
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        async for message in client.receive_response():
            logger.info(f"message: {message}")
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
                            add_system_message(containers, f"{block.text}", "markdown")
                        final_result = block.text
                    elif isinstance(block, ToolUseBlock):
                        logger.info(f"--> tool_use_id: {block.id=}, name: {block.name}, input: {block.input}")
                        if chat.debug_mode == 'Enable':
                            add_notification(containers, f"Tool name: {block.name}, input: {block.input}")
                    elif isinstance(block, ToolResultBlock):
                        logger.info(f"--> tool_use_id: {block.tool_use_id=}, content: {block.content}")
                        # Skip displaying image type ToolResults
                        if isinstance(block.content, list):
                            has_image = any(isinstance(item, dict) and item.get('type') == 'image' for item in block.content)
                            if has_image:
                                logger.info("Skipping image type ToolResult")
                                continue
                        if chat.debug_mode == 'Enable':
                            add_notification(containers, f"Tool result: {block.content}")
                    else:
                        logger.info(f"AssistantMessage: {block}")
                    
            elif isinstance(message, UserMessage):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        logger.info(f"--> tool_use_id: {block.tool_use_id=}, content: {block.content}")
                        # Skip displaying image type ToolResults
                        skip_notification = False
                        if isinstance(block.content, list):
                            has_image = any(isinstance(item, dict) and item.get('type') == 'image' for item in block.content)
                            if has_image:
                                logger.info("Skipping image type ToolResult")
                                skip_notification = True
                        
                        if not skip_notification and chat.debug_mode == 'Enable':
                            add_notification(containers, f"Tool result: {block.content}")
                        
                        if isinstance(block.content, list):
                            for item in block.content:
                                if isinstance(item, dict) and "text" in item:
                                    logger.info(f"--> ToolResult: {item['text']}")
                                    if "path" in item['text'] and item['text'].strip():
                                        try:
                                            json_path = json.loads(item['text'])
                                            path = json_path.get('path', "")
                                            logger.info(f"path: {path}")
                                            image_url.append(path)
                                        except json.JSONDecodeError as e:
                                            logger.warning(f"JSON parsing failed: {e}, text: {item['text']}")
                        elif isinstance(block.content, str):
                            logger.info(f"--> ToolResult content is string: {block.content}")
                            try:
                                parsed_content = json.loads(block.content)
                                logger.info(f"--> Parsed content: {parsed_content}")
                                if isinstance(parsed_content, dict):
                                    if "result" in parsed_content and isinstance(parsed_content["result"], dict):
                                        if "path" in parsed_content["result"]:
                                            paths = parsed_content["result"]["path"]
                                            if isinstance(paths, list):
                                                for path in paths:
                                                    logger.info(f"path from parsed JSON: {path}")
                                                    image_url.append(path)
                                    elif "path" in parsed_content:
                                        path = parsed_content.get('path', "")
                                        logger.info(f"path from parsed JSON: {path}")
                                        image_url.append(path)
                            except json.JSONDecodeError as e:
                                logger.warning(f"JSON parsing failed: {e}, content: {block.content}")
                    else:
                        logger.info(f"UserMessage: {block}")
            else:
                logger.info(f"Message: {message}")
    
    return final_result, image_url
