import json
import re
import logging
import sys
import os
import asyncio
import info
import chat
import mcp_config

# Apply nest_asyncio to allow nested event loops for Streamlit compatibility
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    # Logger not yet defined, so just pass silently
    # User should install nest-asyncio: pip install nest-asyncio
    pass

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

# Try to disable WebSocket usage in Bun/Claude Code
# This might help if Claude Code tries to use WebSocket unnecessarily
os.environ["DISABLE_WEBSOCKET"] = "1"
os.environ["NO_WEBSOCKET"] = "1"

# WebSocket error prevention
import tempfile

# WebSocket mocking script generation
# This script needs to work with both Node.js and Bun
websocket_mock_script = '''
// Mock WebSocket for Bun/Node.js environments
(function() {
    function MockWebSocket() {
        return {
            readyState: 1,
            CONNECTING: 0,
            OPEN: 1,
            CLOSING: 2,
            CLOSED: 3,
            close: function() {},
            send: function() {},
            addEventListener: function() {},
            removeEventListener: function() {},
            dispatchEvent: function() { return true; },
            onopen: null,
            onclose: null,
            onerror: null,
            onmessage: null,
            url: '',
            protocol: '',
            extensions: '',
            readyState: 1,
            binaryType: 'blob'
        };
    }
    
    // Set on global scope for Bun compatibility
    if (typeof global !== 'undefined') {
        if (typeof global.window === 'undefined') {
            global.window = {};
        }
        global.window.WebSocket = MockWebSocket;
        global.WebSocket = MockWebSocket;
        
        // Also set on globalThis for broader compatibility
        if (typeof globalThis !== 'undefined') {
            globalThis.window = globalThis.window || {};
            globalThis.window.WebSocket = MockWebSocket;
            globalThis.WebSocket = MockWebSocket;
        }
    }
    
    // Set on window if it exists
    if (typeof window !== 'undefined') {
        window.WebSocket = MockWebSocket;
    }
})();
'''

# Save WebSocket mocking script to temporary file
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
    f.write(websocket_mock_script)
    websocket_mock_file = f.name

# Add WebSocket mocking file to Node.js options
# Note: Bun doesn't support --require, but we set it anyway for Node.js compatibility
os.environ["NODE_OPTIONS"] = f"--require {websocket_mock_file}"

# For Bun, try setting BUN_INSTALL_SCRIPT or other Bun-specific environment variables
# Bun may use different environment variables for preloading scripts
# However, since Bun doesn't officially support --require, we need to find another way

# Try to set the WebSocket mock file path in a way Bun might recognize
# This is experimental and may not work, but worth trying
os.environ["BUN_PRELOAD"] = websocket_mock_file

# Log the WebSocket mock file location for debugging
logger.info(f"WebSocket mock file created at: {websocket_mock_file}")
logger.info(f"NODE_OPTIONS set to: {os.environ.get('NODE_OPTIONS')}")
logger.info(f"BUN_PRELOAD set to: {os.environ.get('BUN_PRELOAD')}")

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
    
    # Log environment variables before creating client
    logger.info(f"CLAUDE_CODE_USE_BEDROCK: {os.environ.get('CLAUDE_CODE_USE_BEDROCK')}")
    logger.info(f"CLAUDE_CODE_MAX_OUTPUT_TOKENS: {os.environ.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS')}")
    logger.info(f"NODE_OPTIONS: {os.environ.get('NODE_OPTIONS')}")
    logger.info(f"BUN_PRELOAD: {os.environ.get('BUN_PRELOAD')}")
    logger.info(f"DISABLE_WEBSOCKET: {os.environ.get('DISABLE_WEBSOCKET')}")
    logger.info(f"NO_WEBSOCKET: {os.environ.get('NO_WEBSOCKET')}")
    
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
    try:
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
    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"ERROR CAUGHT in run_claude_agent")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {e}")
        logger.error(f"Error repr: {repr(e)}")
        
        # Log all attributes of the exception for ProcessError
        if hasattr(e, '__dict__'):
            logger.error(f"Exception __dict__: {e.__dict__}")
        
        # Log all attributes using dir() to see everything
        all_attrs = [attr for attr in dir(e) if not attr.startswith('_')]
        logger.error(f"Exception attributes (dir): {all_attrs}")
        
        # Try to access each attribute
        for attr in all_attrs:
            try:
                value = getattr(e, attr)
                if not callable(value):
                    logger.error(f"  {attr} = {value}")
            except Exception as attr_error:
                logger.error(f"  {attr} = <error: {attr_error}>")
        
        # Log additional details if available
        if hasattr(e, '__cause__') and e.__cause__:
            logger.error(f"Caused by: {type(e.__cause__).__name__}: {e.__cause__}")
        if hasattr(e, '__context__') and e.__context__:
            logger.error(f"Context: {type(e.__context__).__name__}: {e.__context__}")
        
        # Log common ProcessError attributes specifically
        logger.error("Checking ProcessError-specific attributes:")
        for attr in ['exit_code', 'returncode', 'stderr', 'stdout', 'cmd', 'args', 'message', 'msg', 'process', 'subprocess']:
            if hasattr(e, attr):
                try:
                    value = getattr(e, attr)
                    logger.error(f"  ProcessError.{attr} = {value}")
                    if attr == 'process' and value is not None:
                        # If process object exists, try to get its stderr/stdout
                        if hasattr(value, 'stderr'):
                            try:
                                stderr_content = value.stderr.read() if hasattr(value.stderr, 'read') else str(value.stderr)
                                logger.error(f"    process.stderr = {stderr_content}")
                            except:
                                logger.error(f"    process.stderr = <cannot read>")
                        if hasattr(value, 'stdout'):
                            try:
                                stdout_content = value.stdout.read() if hasattr(value.stdout, 'read') else str(value.stdout)
                                logger.error(f"    process.stdout = {stdout_content}")
                            except:
                                logger.error(f"    process.stdout = <cannot read>")
                except Exception as attr_error:
                    logger.error(f"  ProcessError.{attr} = <error accessing: {attr_error}>")
        
        import traceback
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())
        logger.error("=" * 80)
        raise
    
    return final_result, image_url

def run_claude_agent_sync(prompt, mcp_servers, history_mode, containers):
    """
    Synchronous wrapper for run_claude_agent using nest_asyncio.
    This allows running async code in Streamlit's event loop environment.
    """
    try:
        return asyncio.run(run_claude_agent(prompt, mcp_servers, history_mode, containers))
    except Exception as e:
        logger.error(f"Error in run_claude_agent_sync: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise
