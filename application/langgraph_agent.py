import logging
import sys
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

user_id = "langgraph"

class State(TypedDict):
    messages: Annotated[list, add_messages]
    image_url: list

async def call_model(state: State, config):
    logger.info(f"###### call_model ######")

    last_message = state['messages'][-1]
    logger.info(f"last message: {last_message}")
    
    image_url = state['image_url'] if 'image_url' in state else []

    tools = config.get("configurable", {}).get("tools", None)
    system_prompt = config.get("configurable", {}).get("system_prompt", None)
    
    if system_prompt:
        system = system_prompt
    else:
        system = (
            "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다."
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다."
            "모르는 질문을 받으면 솔직히 모른다고 말합니다."
            "한국어로 답변하세요."

            "An agent orchestrates the following workflow:"
            "1. Receives user input"
            "2. Processes the input using a language model"
            "3. Decides whether to use tools to gather information or perform actions"
            "4. Executes those tools and receives results"
            "5. Continues reasoning with the new information"
            "6. Produces a final response"
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

