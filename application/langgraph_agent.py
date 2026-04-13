import logging
import sys
import traceback
import chat
import utils
import subprocess

from langgraph.prebuilt import ToolNode
from typing import Literal
from langgraph.graph import START, END, StateGraph
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from typing import Literal
from langgraph.graph import START, END, StateGraph
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from urllib import parse

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
from urllib.parse import quote
from langchain_core.tools import tool
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

import datetime
from pytz import timezone

@tool
def get_current_time(format: str=f"%Y-%m-%d %H:%M:%S")->str:
    """Returns the current date and time in the specified format"""
    # f"%Y-%m-%d %H:%M:%S"
    
    format = format.replace('\'','')
    timestr = datetime.datetime.now(timezone('Asia/Seoul')).strftime(format)
    logger.info(f"timestr: {timestr}")
    
    return timestr

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

def _ensure_cli_scripts_on_path() -> None:
    """Prepend pip user script dir so CLIs (e.g. browser-use) resolve in subprocess."""
    import site
    import sysconfig

    extra: list[str] = []
    user_base = getattr(site, "USER_BASE", None)
    if user_base:
        user_bin = os.path.join(user_base, "bin")
        if os.path.isdir(user_bin):
            extra.append(user_bin)
    try:
        scripts = sysconfig.get_path("scripts")
        if scripts and os.path.isdir(scripts):
            extra.append(scripts)
    except Exception:
        pass
    path = os.environ.get("PATH", "")
    parts = [p for p in path.split(os.pathsep) if p]
    for d in reversed(extra):
        if d and d not in parts:
            parts.insert(0, d)
    os.environ["PATH"] = os.pathsep.join(parts)

@tool
def bash(command: str) -> str:
    """Execute a bash command and return the result"""
    logger.info(f"###### bash: {command} ######")
    _ensure_cli_scripts_on_path()
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True,
        cwd=WORKING_DIR, timeout=300,
        env=os.environ,
    )
    parts = []
    if result.stdout:
        parts.append(f"STDOUT:\n{result.stdout}")
    if result.stderr:
        parts.append(f"STDERR:\n{result.stderr}")
    if result.returncode != 0:
        parts.append(f"Return code: {result.returncode}")
    return "\n".join(parts) if parts else "(no output)"


def get_builtin_tools() -> list:
    """Return the list of built-in tools for the skill-aware agent."""

    if config.get("sharing_url"):
        return [execute_code, write_file, read_file, bash, upload_file_to_s3, get_current_time]
    else:
        return [execute_code, write_file, read_file, bash, get_current_time]

class State(TypedDict):
    messages: Annotated[list, add_messages]
    artifacts: list

async def call_model(state: State, config):
    logger.info(f"###### call_model ######")

    last_message = state['messages'][-1]
    logger.info(f"last message: {last_message}")
    
    artifacts = state['artifacts'] if 'artifacts' in state else []

    tools = config.get("configurable", {}).get("tools", None)
    system_prompt = config.get("configurable", {}).get("system_prompt", None)
    
    if system_prompt:
        system = system_prompt
    else:
        system = (
            "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다.\n"
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다.\n"
            "모르는 질문을 받으면 솔직히 모른다고 말합니다.\n"
            "결과 파일이 있으면 upload_file_to_s3로 업로드하여 URL을 제공합니다.\n"
            "한국어로 답변하세요.\n"

            "An agent orchestrates the following workflow:\n"
            "1. Receives user input\n"
            "2. Processes the input using a language model\n"
            "3. Decides whether to use tools to gather information or perform actions\n"
            "4. Executes those tools and receives results\n"
            "5. Continues reasoning with the new information\n"
            "6. Produces a final response\n"
        )

    # Use reasoning_mode with fallback to default
    reasoning_mode = getattr(chat, 'reasoning_mode', 'Disable')
    chatModel = chat.get_chat(extended_thinking=reasoning_mode)
    
    # Ensure tools is not None before binding
    if tools is None:
        logger.warning("tools is None, using empty list")
        tools = []
    
    model = chatModel.bind_tools(tools)

    try:
        messages = []
        for msg in state["messages"]:
            if isinstance(msg, ToolMessage):
                content = msg.content
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            # Remove 'id' field if present, but keep other fields
                            item_clean = {k: v for k, v in item.items() if k != 'id'}
                            if 'text' in item_clean:
                                text_parts.append(item_clean['text'])
                            elif 'content' in item_clean:
                                text_parts.append(str(item_clean['content']))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    content = '\n'.join(text_parts) if text_parts else str(content)
                elif not isinstance(content, str):
                    content = str(content)
                
                # Create ToolMessage without 'name' field (Bedrock doesn't accept it)
                tool_msg = ToolMessage(
                    content=content,
                    tool_call_id=msg.tool_call_id
                )
                messages.append(tool_msg)
            else:
                messages.append(msg)
        
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        chain = prompt | model
            
        response = await chain.ainvoke(messages)
        logger.info(f"response of call_model: {response}")

    except Exception:
        response = AIMessage(content="답변을 찾지 못하였습니다.")

        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    return {"messages": [response], "artifacts": artifacts}

async def should_continue(state: State, config) -> Literal["continue", "end"]:
    logger.info(f"###### should_continue ######")

    messages = state["messages"]    
    last_message = messages[-1]
    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        tool_name = last_message.tool_calls[-1]['name']
        logger.info(f"--- CONTINUE: {tool_name} ---")

        tool_args = last_message.tool_calls[-1]['args']

        if last_message.content:
            logger.info(f"last_message: {last_message.content}")

        logger.info(f"tool_name: {tool_name}, tool_args: {tool_args}")

        return "continue"
    else:
        logger.info(f"--- END ---")
        return "end"

def buildChatAgent(tools):
    tool_node = ToolNode(tools, handle_tool_errors=True)

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

async def plan_node(state: State, config):
    logger.info(f"###### plan_node ######")

    containers = config.get("configurable", {}).get("containers", None)

    system=(
        "For the given objective, come up with a simple step by step plan."
        "This plan should involve individual tasks, that if executed correctly will yield the correct answer." 
        "Do not add any superfluous steps."
        "The result of the final step should be the final answer. Make sure that each step has all the information needed."
        "The plan should be returned in <plan> tag."
    )

    chatModel = chat.get_chat(extended_thinking="Disable")
    
    try:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        chain = prompt | chatModel
            
        result = await chain.ainvoke(state["messages"])
        # logger.info(f"result of plan_node: {result.content}")

        plan = result.content[result.content.find('<plan>')+6:result.content.find('</plan>')]
        logger.info(f"plan: {plan}")

        plan = plan.strip()
        response = HumanMessage(content="다음의 plan을 참고하여 답변하세요.\n" + plan)

        if containers is not None:
            chat.add_notification(containers, '계획:\n' + plan)

    except Exception:
        response = HumanMessage(content="")

        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    return {"messages": [response]}

def buildChatAgentWithPlan(tools):
    tool_node = ToolNode(tools, handle_tool_errors=True)

    workflow = StateGraph(State)

    workflow.add_node("plan", plan_node)
    workflow.add_node("agent", call_model)
    workflow.add_node("action", tool_node)
    workflow.add_edge(START, "plan")
    workflow.add_edge("plan", "agent")
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
    tool_node = ToolNode(tools, handle_tool_errors=True)

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

