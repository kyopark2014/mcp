import logging
import sys
import os
import io
import traceback
import uuid
import re
import yaml
import chat
import utils

from dataclasses import dataclass, field
from typing import Literal, Optional

from langgraph.prebuilt import ToolNode
from langgraph.graph import START, END, StateGraph
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("agent")

config = utils.load_config()
sharing_url = config.get("sharing_url")
s3_prefix = "docs"
capture_prefix = "captures"
user_id = "langgraph"

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(WORKING_DIR, "skills")
ARTIFACTS_DIR = os.path.join(WORKING_DIR, "artifacts")

# ═══════════════════════════════════════════════════════════════════
#  1. Skill System  – Anthropic Agent Skills spec 구현
#     (https://agentskills.io/specification)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    path: str


class SkillManager:
    """Discovers, loads and selects Agent Skills following the Anthropic spec."""

    def __init__(self, skills_dir: str = SKILLS_DIR):
        self.skills_dir = skills_dir
        self.registry: dict[str, Skill] = {}
        self._discover()

    # ---- discovery & metadata loading ----

    def _discover(self):
        """Scan skills directory and load metadata (frontmatter only)."""
        if not os.path.isdir(self.skills_dir):
            os.makedirs(self.skills_dir, exist_ok=True)
            logger.info(f"Created skills directory: {self.skills_dir}")
            return

        for entry in os.listdir(self.skills_dir):
            skill_md = os.path.join(self.skills_dir, entry, "SKILL.md")
            if os.path.isfile(skill_md):
                try:
                    meta, instructions = self._parse_skill_md(skill_md)
                    skill = Skill(
                        name=meta.get("name", entry),
                        description=meta.get("description", ""),
                        instructions=instructions,
                        path=os.path.join(self.skills_dir, entry),
                    )
                    self.registry[skill.name] = skill
                    logger.info(f"Skill discovered: {skill.name}")
                except Exception as e:
                    logger.warning(f"Failed to load skill '{entry}': {e}")

    @staticmethod
    def _parse_skill_md(filepath: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + markdown body from a SKILL.md file."""
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        if not raw.startswith("---"):
            return {}, raw

        parts = raw.split("---", 2)
        if len(parts) < 3:
            return {}, raw

        frontmatter = yaml.safe_load(parts[1]) or {}
        body = parts[2].strip()
        return frontmatter, body

    # ---- prompt generation (progressive disclosure) ----

    def available_skills_xml(self) -> str:
        """Generate <available_skills> XML for the system prompt (metadata only)."""
        if not self.registry:
            return ""
        lines = ["<available_skills>"]
        for s in self.registry.values():
            lines.append("  <skill>")
            lines.append(f"    <name>{s.name}</name>")
            lines.append(f"    <description>{s.description}</description>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_skill_instructions(self, name: str) -> Optional[str]:
        """Return full instructions for a skill (loaded on demand)."""
        skill = self.registry.get(name)
        return skill.instructions if skill else None

    def select_skills(self, query: str) -> list[Skill]:
        """Keyword-based matching to select relevant skills for a query."""
        query_lower = query.lower()
        selected = []
        for skill in self.registry.values():
            keywords = skill.description.lower().split()
            if any(kw in query_lower for kw in keywords if len(kw) > 3):
                selected.append(skill)
        return selected

    def build_active_skill_prompt(self, skills: list[Skill]) -> str:
        """Build the full instructions block for activated skills."""
        if not skills:
            return ""
        parts = ["<active_skills>"]
        for s in skills:
            parts.append(f'<skill name="{s.name}">')
            parts.append(s.instructions)
            parts.append("</skill>")
        parts.append("</active_skills>")
        return "\n".join(parts)


# global singleton
skill_manager = SkillManager()


# ═══════════════════════════════════════════════════════════════════
#  2. Built-in Tools – code execution, file I/O, S3 upload
# ═══════════════════════════════════════════════════════════════════

@tool
def execute_code(code: str) -> str:
    """Execute Python code and return stdout/stderr output.

    Use this tool to run Python code for tasks such as generating PDFs,
    processing data, or performing computations. The execution environment
    has access to common libraries: reportlab, pypdf, pdfplumber, pandas,
    json, csv, os, etc.

    Generated files should be saved to the 'artifacts/' directory.

    Args:
        code: Python code to execute.

    Returns:
        Captured stdout output, or error traceback if execution failed.
    """
    logger.info(f"###### execute_code ######")
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    old_cwd = os.getcwd()
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        os.chdir(WORKING_DIR)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout_capture, stderr_capture

        exec_globals = {"__builtins__": __builtins__}
        exec(code, exec_globals)

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

        return result

    except Exception as e:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        os.chdir(old_cwd)
        tb = traceback.format_exc()
        logger.error(f"Code execution error: {tb}")
        return f"Error executing code:\n{tb}"


@tool
def write_file(filepath: str, content: str) -> str:
    """Write text content to a file.

    Args:
        filepath: Path relative to the working directory (e.g. 'artifacts/report.md').
        content: The text content to write.

    Returns:
        A success or failure message.
    """
    logger.info(f"###### write_file: {filepath} ######")
    try:
        full_path = os.path.join(WORKING_DIR, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        result_msg = f"파일이 저장되었습니다: {filepath}"

        s3_bucket = config.get("s3_bucket")
        if s3_bucket and sharing_url:
            try:
                import boto3
                from urllib import parse as url_parse
                s3 = boto3.client("s3", region_name=config.get("region", "us-west-2"))
                content_type = utils.get_contents_type(filepath)
                s3.put_object(Bucket=s3_bucket, Key=filepath, Body=content, ContentType=content_type)
                url = f"{sharing_url}/{url_parse.quote(filepath)}"
                result_msg += f"\nURL: {url}"
            except Exception as ue:
                logger.warning(f"S3 upload failed: {ue}")

        return result_msg
    except Exception as e:
        return f"파일 저장 실패: {str(e)}"


@tool
def read_file(filepath: str) -> str:
    """Read the contents of a local file.

    Args:
        filepath: Path relative to the working directory.

    Returns:
        The file contents as text, or an error message.
    """
    logger.info(f"###### read_file: {filepath} ######")
    try:
        full_path = os.path.join(WORKING_DIR, filepath)
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"파일 읽기 실패: {str(e)}"


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
            return "S3 버킷이 설정되어 있지 않습니다."

        full_path = os.path.join(WORKING_DIR, filepath)
        if not os.path.exists(full_path):
            return f"파일을 찾을 수 없습니다: {filepath}"

        content_type = utils.get_contents_type(filepath)
        s3 = boto3.client("s3", region_name=config.get("region", "us-west-2"))

        with open(full_path, "rb") as f:
            s3.put_object(Bucket=s3_bucket, Key=filepath, Body=f.read(), ContentType=content_type)

        if sharing_url:
            url = f"{sharing_url}/{url_parse.quote(filepath)}"
            return f"업로드 완료: {url}"
        return f"업로드 완료: s3://{s3_bucket}/{filepath}"

    except Exception as e:
        return f"업로드 실패: {str(e)}"


@tool
def get_skill_instructions(skill_name: str) -> str:
    """Load the full instructions for a specific skill by name.

    Use this when you need detailed instructions for a task that matches
    one of the available skills listed in the system prompt.

    Args:
        skill_name: The name of the skill to load (e.g. 'pdf').

    Returns:
        The full skill instructions, or an error message if not found.
    """
    logger.info(f"###### get_skill_instructions: {skill_name} ######")
    instructions = skill_manager.get_skill_instructions(skill_name)
    if instructions:
        return instructions
    available = ", ".join(skill_manager.registry.keys())
    return f"Skill '{skill_name}'을 찾을 수 없습니다. 사용 가능한 skill: {available}"


def get_builtin_tools():
    """Return the list of built-in tools for the skill-aware agent."""
    return [execute_code, write_file, read_file, upload_file_to_s3, get_skill_instructions]


# ═══════════════════════════════════════════════════════════════════
#  3. Agent State & System Prompt
# ═══════════════════════════════════════════════════════════════════

class State(TypedDict):
    messages: Annotated[list, add_messages]
    image_url: list


BASE_SYSTEM_PROMPT = (
    "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다.\n"
    "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다.\n"
    "모르는 질문을 받으면 솔직히 모른다고 말합니다.\n"
    "한국어로 답변하세요.\n\n"
    "## Agent Workflow\n"
    "1. 사용자 입력을 받는다\n"
    "2. 요청에 맞는 skill이 있으면 get_skill_instructions 도구로 상세 지침을 로드한다\n"
    "3. skill 지침에 따라 execute_code, write_file 등의 도구를 사용하여 작업을 수행한다\n"
    "4. 결과 파일이 있으면 upload_file_to_s3로 업로드하여 URL을 제공한다\n"
    "5. 최종 결과를 사용자에게 전달한다\n"
)

SKILL_USAGE_GUIDE = (
    "\n## Skill 사용 가이드\n"
    "위의 <available_skills>에 나열된 skill이 사용자의 요청과 관련될 때:\n"
    "1. 먼저 get_skill_instructions 도구로 해당 skill의 상세 지침을 로드하세요.\n"
    "2. 지침에 포함된 코드 패턴을 execute_code 도구로 실행하세요.\n"
    "3. 생성된 파일은 upload_file_to_s3로 업로드하고 URL을 사용자에게 전달하세요.\n"
    "4. skill 지침이 없는 일반 질문은 직접 답변하세요.\n"
)


def build_system_prompt(custom_prompt: Optional[str] = None) -> str:
    """Assemble the full system prompt with available skills metadata."""
    if custom_prompt:
        base = custom_prompt
    else:
        base = BASE_SYSTEM_PROMPT

    skills_xml = skill_manager.available_skills_xml()
    if skills_xml:
        return f"{base}\n\n{skills_xml}\n{SKILL_USAGE_GUIDE}"
    return base


# ═══════════════════════════════════════════════════════════════════
#  4. LangGraph Nodes
# ═══════════════════════════════════════════════════════════════════

async def call_model(state: State, config):
    logger.info(f"###### call_model ######")

    last_message = state['messages'][-1]
    logger.info(f"last message: {last_message}")

    image_url = state.get('image_url', [])

    tools = config.get("configurable", {}).get("tools", None)
    custom_prompt = config.get("configurable", {}).get("system_prompt", None)

    system = build_system_prompt(custom_prompt)

    reasoning_mode = getattr(chat, 'reasoning_mode', 'Disable')
    chatModel = chat.get_chat(extended_thinking=reasoning_mode)

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

                tool_msg = ToolMessage(
                    content=content,
                    tool_call_id=msg.tool_call_id
                )
                messages.append(tool_msg)
            else:
                messages.append(msg)

        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            MessagesPlaceholder(variable_name="messages"),
        ])
        chain = prompt | model

        response = await chain.ainvoke(messages)
        logger.info(f"response of call_model: {response}")

    except Exception:
        response = AIMessage(content="답변을 찾지 못하였습니다.")
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    return {"messages": [response], "image_url": image_url}


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


async def plan_node(state: State, config):
    logger.info(f"###### plan_node ######")

    containers = config.get("configurable", {}).get("containers", None)

    system = (
        "For the given objective, come up with a simple step by step plan."
        "This plan should involve individual tasks, that if executed correctly will yield the correct answer."
        "Do not add any superfluous steps."
        "The result of the final step should be the final answer. Make sure that each step has all the information needed."
        "The plan should be returned in <plan> tag."
    )

    chatModel = chat.get_chat(extended_thinking="Disable")

    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            MessagesPlaceholder(variable_name="messages"),
        ])
        chain = prompt | chatModel

        result = await chain.ainvoke(state["messages"])

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


# ═══════════════════════════════════════════════════════════════════
#  5. Agent Builders
# ═══════════════════════════════════════════════════════════════════

def buildChatAgent(tools):
    tool_node = ToolNode(tools, handle_tool_errors=True)

    workflow = StateGraph(State)

    workflow.add_node("agent", call_model)
    workflow.add_node("action", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"continue": "action", "end": END},
    )
    workflow.add_edge("action", "agent")

    return workflow.compile()


def buildChatAgentWithPlan(tools):
    tool_node = ToolNode(tools)

    workflow = StateGraph(State)

    workflow.add_node("plan", plan_node)
    workflow.add_node("agent", call_model)
    workflow.add_node("action", tool_node)
    workflow.add_edge(START, "plan")
    workflow.add_edge("plan", "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"continue": "action", "end": END},
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
        {"continue": "action", "end": END},
    )
    workflow.add_edge("action", "agent")

    return workflow.compile(
        checkpointer=chat.checkpointer,
        store=chat.memorystore
    )


# ═══════════════════════════════════════════════════════════════════
#  6. MCP Server Utilities
# ═══════════════════════════════════════════════════════════════════

def load_multiple_mcp_server_parameters(mcp_json: dict):
    mcpServers = mcp_json.get("mcpServers")

    server_info = {}
    if mcpServers is not None:
        for server_name, cfg in mcpServers.items():
            if cfg.get("type") == "streamable_http":
                server_info[server_name] = {
                    "transport": "streamable_http",
                    "url": cfg.get("url"),
                    "headers": cfg.get("headers", {})
                }
            else:
                server_info[server_name] = {
                    "transport": "stdio",
                    "command": cfg.get("command", ""),
                    "args": cfg.get("args", []),
                    "env": cfg.get("env", {})
                }
    return server_info
