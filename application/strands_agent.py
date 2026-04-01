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
from strands import Agent, tool

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

def s3_uri_to_console_url(uri: str, region: str) -> str:
    """Open the object in the AWS S3 console (when sharing_url is not configured)."""
    if not uri or not uri.startswith("s3://"):
        return ""
    rest = uri[5:]
    parts = rest.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    enc_key = parse.quote(key, safe="")
    return f"https://{region}.console.aws.amazon.com/s3/object/{bucket}?prefix={enc_key}"

import io, os, sys, json, traceback
import subprocess as _subprocess, pathlib as _pathlib, shutil as _shutil
import tempfile as _tempfile, glob as _glob, datetime as _datetime
import math as _math, re as _re, requests as _requests
from pathlib import Path

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(WORKING_DIR, "artifacts")

_ARTIFACT_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx"})

_mpl_runtime_ready = False

def _artifact_files_mtime_snapshot() -> dict:
    """Relative path from WORKING_DIR -> mtime. Only scans under artifacts/."""
    snap = {}
    if not os.path.isdir(ARTIFACTS_DIR):
        return snap
    for dirpath, _, filenames in os.walk(ARTIFACTS_DIR):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            try:
                rel = os.path.relpath(full, WORKING_DIR)
                snap[rel] = os.path.getmtime(full)
            except OSError:
                pass
    return snap


def _touched_artifact_paths(before: dict, after: dict) -> list:
    """Only files created or modified between pre/post execution snapshots."""
    touched = []
    for rel, mt in after.items():
        if rel not in before or before[rel] != mt:
            touched.append(rel)
    return sorted(touched)


def _paths_for_ui(relative_paths: list) -> list:
    """absolute path for Streamlit st.image."""
    out = []
    for rel in relative_paths:
            out.append(os.path.abspath(os.path.join(WORKING_DIR, rel)))
    return out


def _ensure_matplotlib_runtime():
    """Use non-interactive Agg backend, prefer CJK-capable fonts, silence headless/show noise."""
    global _mpl_runtime_ready
    if _mpl_runtime_ready:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")

        import warnings

        warnings.filterwarnings(
            "ignore",
            message=r"Glyph .* missing from font",
            category=UserWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"FigureCanvasAgg is non-interactive.*",
            category=UserWarning,
        )

        import matplotlib.font_manager as fm
        import matplotlib as mpl

        mpl.rcParams["axes.unicode_minus"] = False
        cjk_candidates = (
            "AppleGothic",
            "Apple SD Gothic Neo",
            "Malgun Gothic",
            "NanumGothic",
            "NanumBarunGothic",
            "Noto Sans CJK KR",
            "Noto Sans KR",
        )
        mpl.rcParams["font.family"] = "sans-serif"
        mpl.rcParams["font.sans-serif"] = list(cjk_candidates) + ["DejaVu Sans", "sans-serif"]

        _mpl_runtime_ready = True
    except Exception as e:
        logger.info(f"matplotlib runtime setup skipped: {e}")
        _mpl_runtime_ready = True

_exec_globals = {
    "__builtins__": __builtins__,
    "subprocess": _subprocess,
    "json": json,
    "os": os,
    "sys": sys,
    "io": io,
    "pathlib": _pathlib,
    "shutil": _shutil,
    "tempfile": _tempfile,
    "glob": _glob,
    "datetime": _datetime,
    "math": _math,
    "re": _re,
    "requests": _requests,
    "WORKING_DIR": WORKING_DIR,
    "ARTIFACTS_DIR": ARTIFACTS_DIR,
}

@tool
def execute_code(code: str) -> str:
    """Execute Python code and return stdout/stderr output.

    Use this tool to run Python code for tasks such as processing data,
    processing data, or performing computations. The execution environment
    has access to common libraries: pandas, numpy, matplotlib, seaborn, etc.
    json, csv, os, requests, etc.

    Variables and imports from previous calls persist across invocations.
    Generated files should be saved to the 'artifacts/' directory.

    Path variables (pre-defined, do NOT redefine):
    - WORKING_DIR: absolute path to application directory
    - ARTIFACTS_DIR: absolute path to artifacts directory (WORKING_DIR/artifacts)

    Args:
        code: Python code to execute.

    Returns:
        Captured stdout output, or error traceback if execution failed.
        If there is a result file, return the path of the file.            
    """
    logger.info(f"###### execute_code ######")
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    before_files = _artifact_files_mtime_snapshot()

    old_cwd = os.getcwd()
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        os.chdir(WORKING_DIR)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout_capture, stderr_capture

        _ensure_matplotlib_runtime()
        exec(code, _exec_globals)

        sys.stdout, sys.stderr = old_stdout, old_stderr
        os.chdir(old_cwd)

        output = stdout_capture.getvalue()
        errors = stderr_capture.getvalue()

        result = ""
        if output:
            result += output
        if errors:
            result += f"\n[stderr]\n{errors}"
        if not result.strip():
            result = "Code executed successfully (no output)."

        after_files = _artifact_files_mtime_snapshot()
        touched = _touched_artifact_paths(before_files, after_files)
        artifact_rels = [
            r
            for r in touched
            if os.path.splitext(r)[1].lower() in _ARTIFACT_EXT
        ]
        other_rels = [r for r in touched if r not in artifact_rels]
        if other_rels:
            lines = "\n".join(
                os.path.abspath(os.path.join(WORKING_DIR, r)) for r in other_rels
            )
            result += f"\n[artifacts]\n{lines}"

        if artifact_rels:
            payload = {"output": result.strip()}
            payload["path"] = _paths_for_ui(artifact_rels)
            return json.dumps(payload, ensure_ascii=False)

        return result

    except Exception as e:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        os.chdir(old_cwd)
        tb = traceback.format_exc()
        logger.error(f"Code execution error: {tb}")
        return f"Error executing code:\n{tb}"

@tool
def write_file(filepath: str, content: str = "") -> str:
    """Write text content to a file.

    CRITICAL: content must always be passed. Calling without content will fail.
    Never call without content. Both filepath and content are required in a single call.

    Args:
        filepath: Absolute path or path relative to WORKING_DIR.
        content: The text content to write. REQUIRED - must not be omitted. Must include full file content.

    Returns:
        A success or failure message.
    """
    if not content:
        return (
            "Error: content parameter is required. "
            "Pass the full content to save in the form write_file(filepath='path', content='content_to_save')."
        )
    logger.info(f"###### write_file: {filepath} ######")
    try:
        full_path = filepath if os.path.isabs(filepath) else os.path.join(WORKING_DIR, filepath)
        parent = os.path.dirname(full_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        result_msg = f"File saved: {filepath}"
        return result_msg
    except Exception as e:
        return f"Failed to save file: {str(e)}"


@tool
def read_file(filepath: str) -> str:
    """Read the contents of a local file.

    Args:
        filepath: Absolute path or path relative to WORKING_DIR.

    Returns:
        The file contents as text, or an error message.
    """
    logger.info(f"###### read_file: {filepath} ######")
    try:
        full_path = filepath if os.path.isabs(filepath) else os.path.join(WORKING_DIR, filepath)
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Failed to read file: {str(e)}"

@tool
def upload_file_to_s3(filepath: str) -> str:
    """Upload a local file to S3 and return the download URL.

    Args:
        filepath: Path relative to the working directory (e.g. 'artifacts/report.pdf').

    Returns:
        The download URL, or an error message.
    """
    logger.info(f"###### upload_file_to_s3: {filepath} ######")
    try:
        import boto3
        from urllib import parse as url_parse

        s3_bucket = config.get("s3_bucket")
        if not s3_bucket:
            return "S3 bucket is not configured."

        full_path = os.path.join(WORKING_DIR, filepath)
        if not os.path.exists(full_path):
            return f"File not found: {filepath}"

        content_type = utils.get_contents_type(filepath)
        s3 = boto3.client("s3", region_name=config.get("region", "us-west-2"))

        with open(full_path, "rb") as f:
            s3.put_object(Bucket=s3_bucket, Key=filepath, Body=f.read(), ContentType=content_type)

        if sharing_url:
            url = f"{sharing_url}/{url_parse.quote(filepath)}"
            return f"Upload complete: {url}"
        return f"Upload complete: {s3_uri_to_console_url(f"s3://{s3_bucket}/{filepath}", config.get("region", "us-west-2"))}"

    except Exception as e:
        return f"Upload failed: {str(e)}"

@tool
def memory_search(query: str, max_results: int = 5, min_score: float = 0.0) -> str:
    """Search across memory files (MEMORY.md and memory/*.md) for relevant information.

    Performs keyword-based search over all memory files and returns matching snippets
    ranked by relevance score.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (default: 5).
        min_score: Minimum relevance score threshold 0.0-1.0 (default: 0.0).

    Returns:
        JSON array of matching snippets with text, path, from (line), lines, and score.
    """
    import re as _re
    logger.info(f"###### memory_search: {query} ######")

    memory_root = Path(WORKING_DIR)
    memory_dir = memory_root / "memory"

    target_files = []
    memory_md = memory_root / "MEMORY.md"
    if memory_md.exists():
        target_files.append(memory_md)
    if memory_dir.exists():
        target_files.extend(sorted(memory_dir.glob("*.md"), reverse=True))

    if not target_files:
        return json.dumps([], ensure_ascii=False)

    query_lower = query.lower()
    query_tokens = [t for t in _re.split(r'\s+', query_lower) if len(t) >= 2]

    results = []
    for fpath in target_files:
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception:
            continue

        lines = content.split("\n")
        content_lower = content.lower()

        if not any(tok in content_lower for tok in query_tokens):
            continue

        window_size = 5
        for i in range(0, len(lines), window_size):
            chunk_lines = lines[i:i + window_size]
            chunk_text = "\n".join(chunk_lines)
            chunk_lower = chunk_text.lower()

            matched_tokens = sum(1 for tok in query_tokens if tok in chunk_lower)
            if matched_tokens == 0:
                continue

            score = matched_tokens / len(query_tokens) if query_tokens else 0.0

            if score >= min_score:
                rel_path = str(fpath.relative_to(memory_root))
                results.append({
                    "text": chunk_text.strip(),
                    "path": rel_path,
                    "from": i + 1,
                    "lines": len(chunk_lines),
                    "score": round(score, 3),
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:max_results]

    return json.dumps(results, indent=2, ensure_ascii=False)


@tool
def memory_get(path: str, from_line: int = 0, lines: int = 0) -> str:
    """Read a specific memory file (MEMORY.md or memory/*.md).

    Use after memory_search to get full context, or when you know the exact file path.

    Args:
        path: Workspace-relative path (e.g. "MEMORY.md", "memory/2026-03-02.md").
        from_line: Starting line number, 1-indexed (0 = read from beginning).
        lines: Number of lines to read (0 = read entire file).

    Returns:
        JSON with 'text' (file content) and 'path'. Returns empty text if file doesn't exist.
    """
    logger.info(f"###### memory_get: {path} ######")

    full_path = Path(WORKING_DIR) / path

    if not full_path.exists():
        return json.dumps({"text": "", "path": path}, ensure_ascii=False)

    try:
        content = full_path.read_text(encoding="utf-8")

        if from_line > 0 or lines > 0:
            all_lines = content.split("\n")
            start = max(0, from_line - 1)
            if lines > 0:
                end = start + lines
                content = "\n".join(all_lines[start:end])
            else:
                content = "\n".join(all_lines[start:])

        return json.dumps({"text": content, "path": path}, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"text": f"Error reading file: {e}", "path": path}, ensure_ascii=False)


def get_builtin_tools() -> list:
    """Return the list of built-in tools for the skill-aware agent."""
    return [execute_code, write_file, read_file, upload_file_to_s3]

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
        if 'sonnet-4-5' in chat.model_id:
            maxOutputTokens = 8192 # 8k for Sonnet 4.5
        else:
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
            max_tokens=32000,  
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
            additional_request_fields={
                "thinking": {
                    "type": "disabled"
                }
            }
        )
    elif chat.model_type == 'openai':
        model = BedrockModel(
            client=bedrock_client,
            model_id=chat.model_id,
            max_tokens=maxOutputTokens,
            temperature=0.1
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
    tools = get_builtin_tools()

    tool_map = {
        "calculator": calculator,
        "current_time": current_time,
        "use_aws": use_aws
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
            "결과 파일이 있으면 upload_file_to_s3로 업로드하여 URL을 제공합니다."
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

