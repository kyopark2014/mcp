import traceback
import boto3
import json
import utils
import chat
import tool_use
import os

from langchain_core.documents import Document
from tavily import TavilyClient  
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from langgraph.graph import START, END, StateGraph
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing import Literal

import logging
import sys

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("search")

# load config
config = utils.load_config()

bedrock_region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "agentic-workflow"

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

# load secret
if aws_access_key and aws_secret_key:
    secretsmanager = boto3.client(
        service_name='secretsmanager',
        region_name=bedrock_region,
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        aws_session_token=aws_session_token,
    )
else:
    secretsmanager = boto3.client(
        service_name='secretsmanager',
        region_name=bedrock_region
)

# api key for tavily search
tavily_key = tavily_api_wrapper = ""
try:
    get_tavily_api_secret = secretsmanager.get_secret_value(
        SecretId=f"tavilyapikey-{projectName}"
    )
    #print('get_tavily_api_secret: ', get_tavily_api_secret)
    secret = json.loads(get_tavily_api_secret['SecretString'])
    #print('secret: ', secret)

    if "tavily_api_key" in secret:
        tavily_key = secret['tavily_api_key']
        #print('tavily_api_key: ', tavily_api_key)

        if tavily_key:
            tavily_api_wrapper = TavilySearchAPIWrapper(tavily_api_key=tavily_key)
            #     os.environ["TAVILY_API_KEY"] = tavily_key

            # Tavily Tool Test
            # query = 'what is Amazon Nova Pro?'
            # search = TavilySearchResults(
            #     max_results=1,
            #     include_answer=True,
            #     include_raw_content=True,
            #     api_wrapper=tavily_api_wrapper,
            #     search_depth="advanced", # "basic"
            #     # include_domains=["google.com", "naver.com"]
            # )
            # output = search.invoke(query)
            # print('tavily output: ', output)    
        else:
            logger.info(f"tavily_key is required.")
except Exception as e: 
    logger.info(f"Tavily credential is required: {e}")
    pass

def retrieve_documents_from_tavily(query, top_k):
    logger.info(f"###### retrieve_documents_from_tavily ######")

    relevant_documents = []        
    search = TavilySearchResults(
        max_results=top_k,
        include_answer=True,
        include_raw_content=True,        
        api_wrapper=tavily_api_wrapper,
        search_depth="advanced", 
        # include_domains=["google.com", "naver.com"]
    )
                    
    try: 
        output = search.invoke(query)
        # logger.info(f"tavily output: {output}")

        if output[:9] == "HTTPError":
            logger.info(f"output: {output}")
            raise Exception ("Not able to request to tavily")
        else:        
            # logger.info(f"-> tavily query: {query}")
            for i, result in enumerate(output):
                # logger.info(f"{i}: {result}")
                if result:
                    content = result.get("content")
                    url = result.get("url")
                    
                    relevant_documents.append(
                        Document(
                            page_content=content,
                            metadata={
                                'name': 'WWW',
                                'url': url,
                                'from': 'tavily'
                            },
                        )
                    )                   
    
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")     
        # raise Exception ("Not able to request to tavily")   

    return relevant_documents 

def retrieve_contents_from_tavily(queries, top_k):
    logger.info(f"###### retrieve_contents_from_tavily ######")

    contents = []       
    search = TavilySearchResults(
        max_results=top_k,
        include_answer=True,
        include_raw_content=True,        
        api_wrapper=tavily_api_wrapper,
        search_depth="advanced", 
        # include_domains=["google.com", "naver.com"]
    )
                    
    try: 
        for query in queries:
            output = search.invoke(query)
            logger.info(f"tavily output: {output}")

            if output[:9] == "HTTPError":
                logger.info(f"output: {output}")
                raise Exception ("Not able to request to tavily")
            else:        
                logger.info(f"-> tavily query: {query}")
                for i, result in enumerate(output):
                    logger.info(f"{i}: {result}")
                    if result and 'content' in result:
                        contents.append(result['content'])
    
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")     
        # raise Exception ("Not able to request to tavily")   

    return contents 

def tavily_search(query, k):
    docs = []    
    try:
        tavily_client = TavilyClient(
            api_key=tavily_key
        )
        response = tavily_client.search(query, max_results=k)
        # print('tavily response: ', response)
            
        for r in response["results"]:
            name = r.get("title")
            if name is None:
                name = 'WWW'
            
            docs.append(
                Document(
                    page_content=r.get("content"),
                    metadata={
                        'name': name,
                        'url': r.get("url"),
                        'from': 'tavily'
                    },
                )
            )                   
    except Exception as e:
        logger.info(f"Exception: {e}")

    return docs

def init_enhanced_search(st):
    llm = chat.get_chat(extended_thinking="Disable") 

    model = llm.bind_tools(tool_use.tools)

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    tool_node = ToolNode(tool_use.tools)

    def should_continue(state: State) -> Literal["continue", "end"]:
        messages = state["messages"]    
        # print('(should_continue) messages: ', messages)
            
        last_message = messages[-1]
        if not last_message.tool_calls:
            return "end"
        else:                
            return "continue"

    def call_model(state: State):
        logger.info(f"##### call_model #####")

        messages = state["messages"]
        # print('messages: ', messages)

        last_message = messages[-1]
        logger.info(f"last_message: {last_message}")

        if isinstance(last_message, ToolMessage) and last_message.content=="":              
            logger.info(f"last_message is empty")
            logger.info(f"question: {state['messages'][0].content}")
            answer = chat.get_basic_answer(state['messages'][0].content)          
            return {"messages": [AIMessage(content=answer)]}
            
        if chat.isKorean(messages[0].content)==True:
            system = (
                "당신은 질문에 답변하기 위한 정보를 수집하는 연구원입니다."
                "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다."
                "모르는 질문을 받으면 솔직히 모른다고 말합니다."
                "최종 답변에는 조사한 내용을 반드시 포함하여야 하고, <result> tag를 붙여주세요."
            )
        else: 
            system = (            
                "You are a researcher charged with providing information that can be used when making answer."
                "If you don't know the answer, just say that you don't know, don't try to make up an answer."
                "You will be acting as a thoughtful advisor."
                "Put it in <result> tags."
            )
                
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        chain = prompt | model
                
        response = chain.invoke(messages)
        logger.info(f"call_model response: {response}")
              
        # state messag
        if response.tool_calls:
            logger.info(f"tool_calls response: {response.tool_calls}")

            toolinfo = response.tool_calls[-1]            
            if toolinfo['type'] == 'tool_call':
                logger.info(f"tool name: {toolinfo['name']}")    

            if chat.debug_mode=="Enable":
                st.info(f"{response.tool_calls[-1]['name']}: {response.tool_calls[-1]['args']}")
                   
        return {"messages": [response]}

    def buildChatAgent():
        workflow = StateGraph(State)

        workflow.add_node("agent", call_model)
        workflow.add_node("action", tool_node)
            
        workflow.set_entry_point("agent")
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

def enhanced_search(query, st):
    logger.info(f"###### enhanced_search ######")
    inputs = [HumanMessage(content=query)]

    app_enhanced_search = init_enhanced_search(st)        
    result = app_enhanced_search.invoke({"messages": inputs})   
    logger.info(f"result: {result}")
            
    message = result["messages"][-1]
    logger.info(f"enhanced_search: {message}")

    if message.content.find('<result>')==-1:
        return message.content
    else:
        return message.content[message.content.find('<result>')+8:message.content.find('</result>')]

