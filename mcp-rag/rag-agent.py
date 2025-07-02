import utils
import traceback
import boto3 
import re
import json
import info

from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.server.fastmcp import FastMCP
from langgraph.graph import START, END, StateGraph
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from typing import Literal
from langchain_aws import ChatBedrock
from botocore.config import Config
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import ToolNode

logger = utils.CreateLogger("agent")

model_name = "Claude 3.5 Sonnet"
model_type = "claude"
models = info.get_model_info(model_name)
multi_region = "Disable"
selected_chat = 0

def isKorean(text):
    # check korean
    pattern_hangul = re.compile('[\u3131-\u3163\uac00-\ud7a3]+')
    word_kor = pattern_hangul.search(str(text))
    # print('word_kor: ', word_kor)

    if word_kor and word_kor != 'None':
        # logger.info(f"Korean: {word_kor}")
        return True
    else:
        logger.info(f"Not Korean: {word_kor}")
        return False
    
def get_chat(extended_thinking):
    global selected_chat, model_type

    logger.info(f"models: {models}")
    logger.info(f"selected_chat: {selected_chat}")
    
    profile = models[selected_chat]
    # print('profile: ', profile)
        
    bedrock_region =  profile['bedrock_region']
    modelId = profile['model_id']
    model_type = profile['model_type']
    number_of_models = len(models)

    if model_type == 'claude':
        maxOutputTokens = 4096 # 4k
    else:
        maxOutputTokens = 5120 # 5k
    logger.info(f"LLM: {selected_chat}, bedrock_region: {bedrock_region}, modelId: {modelId}, model_type: {model_type}")

    if profile['model_type'] == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif profile['model_type'] == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 
                          
    # bedrock   
    boto3_bedrock = boto3.client(
        service_name='bedrock-runtime',
        region_name=bedrock_region,
        config=Config(
            retries = {
                'max_attempts': 30
            }
        )
    )
    if extended_thinking=='Enable':
        maxReasoningOutputTokens=64000
        logger.info(f"extended_thinking: {extended_thinking}")
        thinking_budget = min(maxOutputTokens, maxReasoningOutputTokens-1000)

        parameters = {
            "max_tokens":maxReasoningOutputTokens,
            "temperature":1,            
            "thinking": {
                "type": "enabled",
                "budget_tokens": thinking_budget
            },
            "stop_sequences": [STOP_SEQUENCE]
        }
    else:
        parameters = {
            "max_tokens":maxOutputTokens,     
            "temperature":0.1,
            "top_k":250,
            "top_p":0.9,
            "stop_sequences": [STOP_SEQUENCE]
        }

    chat = ChatBedrock(   # new chat model
        model_id=modelId,
        client=boto3_bedrock, 
        model_kwargs=parameters,
        region_name=bedrock_region
    )    
    
    if multi_region=='Enable':
        selected_chat = selected_chat + 1
        if selected_chat == number_of_models:
            selected_chat = 0
    else:
        selected_chat = 0

    return chat

def show_extended_thinking(st, result):
    # logger.info(f"result: {result}")
    if "thinking" in result.response_metadata:
        if "text" in result.response_metadata["thinking"]:
            thinking = result.response_metadata["thinking"]["text"]
            st.info(thinking)

debug_mode = "Enable"
def create_agent(tools):
    tool_node = ToolNode(tools)
    tool_classes = list(tool_node.tools_by_name.values())
    logger.info(f"tool_classes: {tool_classes}")

    chatModel = get_chat(extended_thinking="Disable")
    model = chatModel.bind_tools(tool_classes)

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    def call_model(state: State, config):
        logger.info(f"###### call_model ######")
        logger.info(f"state: {state['messages']}")

        if isKorean(state["messages"][0].content)==True:
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

        for attempt in range(3):   
            logger.info(f"attempt: {attempt}")
            try:
                prompt = ChatPromptTemplate.from_messages(
                    [
                        ("system", system),
                        MessagesPlaceholder(variable_name="messages"),
                    ]
                )
                chain = prompt | model
                    
                response = chain.invoke(state["messages"])
                logger.info(f"call_model response: {response}")

                if isinstance(response.content, list):            
                    for re in response.content:
                        if "type" in re:
                            if re['type'] == 'text':
                                logger.info(f"--> {re['type']}: {re['text']}")

                                status = re['text']
                                logger.info(f"status: {status}")
                                
                                status = status.replace('`','')
                                status = status.replace('\"','')
                                status = status.replace("\'",'')
                                
                                logger.info(f"status: {status}")
                                if status.find('<thinking>') != -1:
                                    logger.info(f"Remove <thinking> tag.")
                                    status = status[status.find('<thinking>')+11:status.find('</thinking>')]
                                    logger.info(f"status without tag: {status}")

                                # if debug_mode=="Enable":
                                #     utils.status(st, status)
                                
                            elif re['type'] == 'tool_use':                
                                logger.info(f"--> {re['type']}: {re['name']}, {re['input']}")

                                # if debug_mode=="Enable":
                                #     utils.status(st, f"{re['type']}: {re['name']}, {re['input']}")
                            else:
                                logger.info(re)
                        else: # answer
                            logger.info(response.content)
                break
            except Exception:
                response = AIMessage(content="답변을 찾지 못하였습니다.")

                err_msg = traceback.format_exc()
                logger.info(f"error message: {err_msg}")
                # raise Exception ("Not able to request to LLM")

        return {"messages": [response]}

    def should_continue(state: State) -> Literal["continue", "end"]:
        logger.info(f"###### should_continue ######")

        logger.info(f"state: {state}")
        messages = state["messages"]    

        last_message = messages[-1]
        logger.info(f"last_message: {last_message}")

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            logger.info(f"{last_message.content}")

            for message in last_message.tool_calls:
                args = message['args']
                if debug_mode=='Enable': 
                    if "code" in args:                    
                        state_msg = f"tool name: {message['name']}"
                        logger.info(f"state_msg: {state_msg}")
                        logger.info(f"args: {args}")

            logger.info(f"--- CONTINUE: {last_message.tool_calls[-1]['name']} ---")
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
    
    return buildChatAgent()

server_params = StdioServerParameters(
  command="python",
  args=["/Users/ksdyb/Documents/src/mcp/mcp-rag/rag-server.py"],
)

async def mcp_rag_agent(query):
    async with stdio_client(server_params) as (read, write):
        # Open an MCP session to interact with the math_server.py tool.
        async with ClientSession(read, write) as session:
            # Initialize the session.
            await session.initialize()

            logger.info(f"query: {query}")
            
            # Load tools
            tools = await load_mcp_tools(session)
            print(f"tools: {tools}")
                            
            agent = create_agent(tools)
            
            agent_response = await agent.ainvoke({"messages": query})
            print(f"agent_response: {agent_response}")

        # Return the response.
        return agent_response["messages"][-1].content
    
import asyncio

if __name__ == "__main__":
    #query = "What is the capital of France?"
    query = "what's (4 + 6) x 14?"
    # query = "What are the types of boiler error codes?"
    #query = "Hello"

    result = asyncio.run(mcp_rag_agent(query))
    print(f"result: {result}")

