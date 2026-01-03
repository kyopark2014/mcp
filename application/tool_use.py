import traceback
import json
import boto3
import re
import requests
import datetime
import knowledge_base as kb
import chat
import utils
import search as search_module
import base64
import uuid
import yfinance as yf
import os

from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from typing import Literal
from langchain_core.tools import tool
from bs4 import BeautifulSoup
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_aws import AmazonKnowledgeBasesRetriever
from pytz import timezone
from langchain_core.documents import Document
from urllib import parse
from langgraph.graph import START, END, StateGraph
from io import BytesIO
from langchain_experimental.tools import PythonAstREPLTool

import logging
import sys

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("tool_use")

# load config
config = utils.load_config()
print(f"config: {config}")

# variables
bedrock_region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "langgraph-nova"

path = config["sharing_url"] if "sharing_url" in config else None
if path is None:
    raise Exception ("No Sharing URL")

numberOfDocs = 4
s3_prefix = 'docs'
s3_image_prefix = 'images'

doc_prefix = s3_prefix+'/'

reference_docs = []
contentList = []

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

# api key to get weather information in agent
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

try:
    get_weather_api_secret = secretsmanager.get_secret_value(
        SecretId=f"openweathermap-{projectName}"
    )
    #print('get_weather_api_secret: ', get_weather_api_secret)
    if get_weather_api_secret['SecretString']:
        secret = json.loads(get_weather_api_secret['SecretString'])
        #print('secret: ', secret)
        weather_api_key = secret['weather_api_key']
    else:
        logger.info(f"No secret found for weather api")

except Exception as e:
    pass

def get_basic_answer(query):
    logger.info(f"#### get_basic_answer ####")
    llm = chat.get_chat(extended_thinking="Disable")

    if chat.isKorean(query)==True:
        system = (
            "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다." 
            "모르는 질문을 받으면 솔직히 모른다고 말합니다."
        )
    else: 
        system = (
            "You will be acting as a thoughtful advisor."
            "Using the following conversation, answer friendly for the newest question." 
            "If you don't know the answer, just say that you don't know, don't try to make up an answer."     
        )    
    
    human = "Question: {input}"    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system), 
        ("human", human)
    ])    
    
    chain = prompt | llm    
    output = chain.invoke({"input": query})
    logger.info(f"output.content: {output.content}")

    return output.content

####################### LangGraph #######################
# Agentic Workflow: Tool Use
#########################################################
image_url = []

@tool 
def get_book_list(keyword: str) -> str:
    """
    Search book list by keyword and then return book list
    keyword: search keyword
    return: book list
    """
    
    keyword = keyword.replace('\'','')

    answer = ""
    url = f"https://search.kyobobook.co.kr/search?keyword={keyword}&gbCode=TOT&target=total"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        prod_info = soup.find_all("a", attrs={"class": "prod_info"})
        
        if len(prod_info):
            answer = "추천 도서는 아래와 같습니다.\n"
            
        for prod in prod_info[:5]:
            title = prod.text.strip().replace("\n", "")       
            link = prod.get("href")
            answer = answer + f"{title}, URL: {link}\n\n"
    
    return answer

@tool
def get_current_time(format: str=f"%Y-%m-%d %H:%M:%S")->str:
    """Returns the current date and time in the specified format"""
    # f"%Y-%m-%d %H:%M:%S"
    
    format = format.replace('\'','')
    timestr = datetime.datetime.now(timezone('Asia/Seoul')).strftime(format)
    logger.info(f"timestr: {timestr}")
    
    return timestr

@tool
def get_weather_info(city: str) -> str:
    """
    retrieve weather information by city name and then return weather statement.
    city: the English name of city to retrieve
    return: weather statement
    """    
    
    city = city.replace('\n','')
    city = city.replace('\'','')
    city = city.replace('\"','')
                
    llm = chat.get_chat(extended_thinking="Disable")
    if chat.isKorean(city):
        place = chat.traslation(llm, city, "Korean", "English")
        logger.info(f"city (translated): {place}")
    else:
        place = city
        city = chat.traslation(llm, city, "English", "Korean")
        logger.info(f"city (translated): {city}")
        
    logger.info(f"place: {place}")
    
    weather_str: str = f"{city}에 대한 날씨 정보가 없습니다."
    if weather_api_key: 
        apiKey = weather_api_key
        lang = 'en' 
        units = 'metric' 
        api = f"https://api.openweathermap.org/data/2.5/weather?q={place}&APPID={apiKey}&lang={lang}&units={units}"
        # print('api: ', api)
                
        try:
            result = requests.get(api)
            result = json.loads(result.text)
            logger.info(f"result: {result}")
        
            if 'weather' in result:
                overall = result['weather'][0]['main']
                current_temp = result['main']['temp']
                min_temp = result['main']['temp_min']
                max_temp = result['main']['temp_max']
                humidity = result['main']['humidity']
                wind_speed = result['wind']['speed']
                cloud = result['clouds']['all']
                
                #weather_str = f"The current weather in {city} is characterized by {overall}, with current temperature of {current_temp}°C, minimum temperature of {min_temp}°C, and maximum temperature of {max_temp}°C. Current humidity is {humidity}% and wind speed is {wind_speed} meters per second. Cloud coverage is {cloud}%."
                weather_str = f"{city}의 현재 날씨의 특징은 {overall}이며, 현재 온도는 {current_temp} 입니다. 현재 습도는 {humidity}% 이고, 바람은 초당 {wind_speed} 미터 입니다. 구름은 {cloud}% 입니다."
                #weather_str = f"Today, the overall of {city} is {overall}, current temperature is {current_temp} degree, min temperature is {min_temp} degree, highest temperature is {max_temp} degree. huminity is {humidity}%, wind status is {wind_speed} meter per second. the amount of cloud is {cloud}%."            
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")   
            # raise Exception ("Not able to request to LLM")    
        
    logger.info(f"weather_str: {weather_str}")                        
    return weather_str

# # Tavily Tool
# tavily_tool = TavilySearchResults(
#     max_results=3,
#     include_answer=True,
#     include_raw_content=True,
#     api_wrapper=tavily_api_wrapper,
#     search_depth="advanced", # "basic"
#     # include_domains=["google.com", "naver.com"]
# )
     
@tool    
def search_by_knowledge_base(keyword: str) -> str:
    """
    Search technical information by keyword and then return the result as a string.
    keyword: search keyword
    return: the technical information of keyword
    """    
    logger.info(f"###### search_by_knowledge_base ######") 
    
    global reference_docs
 
    logger.info(f"keyword: {keyword}")
    keyword = keyword.replace('\'','')
    keyword = keyword.replace('|','')
    keyword = keyword.replace('\n','')
    logger.info(f"modified keyword: {keyword}")
    
    relevant_docs = kb.retrieve_documents_from_knowledge_base(keyword, top_k=numberOfDocs)

    # grading        
    filtered_docs = chat.grade_documents(keyword, relevant_docs)

    filtered_docs = chat.check_duplication(filtered_docs) # duplication checker

    relevant_context = ""
    for i, document in enumerate(filtered_docs):
        logger.info(f"{i}: {document}")
        if document.page_content:
            relevant_context += document.page_content + "\n\n"        
    logger.info(f"relevant_context: {relevant_context}")
    
    if len(filtered_docs):
        reference_docs += filtered_docs
        return relevant_context
    else:        
        # relevant_context = "No relevant documents found."
        relevant_context = "관련된 정보를 찾지 못하였습니다."
        logger.info(f"--> {relevant_context}")
        return relevant_context
    
@tool
def search_by_tavily(keyword: str) -> str:
    """
    Search general knowledge by keyword and then return the result as a string.
    keyword: search keyword
    return: the information of keyword
    """    
    global reference_docs    
    answer = ""
    
    keyword = keyword.replace('\'','')
    relevant_documents = search_module.retrieve_documents_from_tavily(keyword, top_k=3)
    # logger.info(f"--> {len(relevant_documents)} docs from tavily")

    # grade  
    filtered_docs = chat.grade_documents(keyword, relevant_documents)

    answer = ""
    for doc in filtered_docs:
        content = doc.page_content
        url = doc.metadata['url']
        answer += f"{content}, URL: {url}\n" 

    if len(filtered_docs):
        reference_docs += filtered_docs
    
    if answer == "":
        # answer = "No relevant documents found." 
        answer = "관련된 정보를 찾지 못하였습니다."
                     
    return answer

@tool
def stock_data_lookup(ticker, country):
    """
    Retrieve accurate stock data for a given ticker.
    country: the english country name of the stock
    ticker: the ticker to retrieve price history for. In South Korea, a ticker is a 6-digit number.
    return: the information of ticker
    """ 
    com = re.compile('[a-zA-Z]') 
    alphabet = com.findall(ticker)
    logger.info(f"alphabet: {alphabet}")

    logger.info(f"country: {country}")

    if len(alphabet)==0:
        if country == "South Korea":
            ticker += ".KS"
        elif country == "Japan":
            ticker += ".T"
    logger.info(f"ticker: {ticker}")
    
    stock = yf.Ticker(ticker)
    
    # get the price history for past 1 month
    history = stock.history(period="1mo")
    logger.info(f"history: {history}")
    
    result = f"## Trading History\n{history}"
    #history.reset_index().to_json(orient="split", index=False, date_format="iso")    
    
    result += f"\n\n## Financials\n{stock.financials}"    
    logger.info(f"financials: {stock.financials}")

    result += f"\n\n## Major Holders\n{stock.major_holders}"
    logger.info(f"major_holders: {stock.major_holders}")

    logger.info(f"result: {result}")

    return result

def generate_short_uuid(length=8):
    full_uuid = uuid.uuid4().hex
    return full_uuid[:length]

from rizaio import Riza
@tool
def code_drawer(code):
    """
    Execute a Python script for draw a graph.
    Since Python runtime cannot use external APIs, necessary data must be included in the code.
    The graph should use English exclusively for all textual elements.
    Do not save pictures locally bacause the runtime does not have filesystem.
    When a comparison is made, all arrays must be of the same length.
    code: the Python code was written in English
    return: the url of graph
    """ 
    # The Python runtime does not have filesystem access, but does include the entire standard library.
    # Make HTTP requests with the httpx or requests libraries.
    # Read input from stdin and write output to stdout."    
        
    code = re.sub(r"seaborn", "classic", code)
    code = re.sub(r"plt.savefig", "#plt.savefig", code)
    
    pre = f"os.environ[ 'MPLCONFIGDIR' ] = '/tmp/'\n"  # matplatlib
    post = """\n
import io
import base64
buffer = io.BytesIO()
plt.savefig(buffer, format='png')
buffer.seek(0)
image_base64 = base64.b64encode(buffer.getvalue()).decode()

print(image_base64)
"""
    code = pre + code + post    
    logger.info(f"code: {code}")
    
    result = ""
    try:     
        client = Riza()

        resp = client.command.exec(
            runtime_revision_id=chat.code_interpreter_id,
            language="python",
            code=code,
            env={
                "DEBUG": "true",
            }
        )
        output = dict(resp)
        #print(f"output: {output}") # includling exit_code, stdout, stderr

        if resp.exit_code > 0:
            logger.debug(f"non-zero exit code {resp.exit_code}")

        base64Img = resp.stdout

        byteImage = BytesIO(base64.b64decode(base64Img))

        image_name = generate_short_uuid()+'.png'
        url = chat.upload_to_s3(byteImage, image_name)
        logger.info(f"url: {url}")

        file_name = url[url.rfind('/')+1:]
        logger.info(f"file_name: {file_name}")

        global image_url
        image_url.append(path+'/'+s3_image_prefix+'/'+parse.quote(file_name))
        logger.info(f"image_url: {image_url}")

        result = f"생성된 그래프의 URL: {image_url}"

        # im = Image.open(BytesIO(base64.b64decode(base64Img)))  # for debuuing
        # im.save(image_name, 'PNG')

    except Exception:
        result = "그래프 생성에 실패했어요. 다시 시도해주세요."

        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    return result

@tool
def code_interpreter(code):
    """
    Execute a Python script to solve a complex question using code.    
    Since Python runtime cannot use external APIs, necessary data must be included in the code.
    The Python runtime does not have filesystem access, but does include the entire standard library.    
    code: the Python code was written in English
    return: the stdout value
    """ 
    # Make HTTP requests with the httpx or requests libraries.
    # Read input from stdin and write output to stdout."            
        
    pre = f"os.environ[ 'MPLCONFIGDIR' ] = '/tmp/'\n"  # matplatlib
    code = pre + code
    logger.info(f"code: {code}")
    
    result = ""
    try:     
        client = Riza()

        resp = client.command.exec(
            runtime_revision_id=chat.code_interpreter_id,
            language="python",
            code=code,
            env={
                "DEBUG": "true",
            }
        )
        output = dict(resp)
        logger.info(f"output: {output}") # includling exit_code, stdout, stderr

        if resp.exit_code > 0:
            logger.debug(f"non-zero exit code {resp.exit_code}")

        resp.stdout        
        result = f"프로그램 실행 결과: {resp.stdout}"

    except Exception:
        result = "프로그램 실행에 실패했습니다. 다시 시도해주세요."
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    logger.info(f"result: {result}")
    return result

repl = PythonAstREPLTool()

@tool
def repl_coder(code):
    """
    Use this to execute python code and do math. 
    If you want to see the output of a value, you should print it out with `print(...)`. This is visible to the user.
    code: the Python code was written in English
    """
    try:
        result = repl.run(code)
    except BaseException as e:
        return f"Failed to execute. Error: {repr(e)}"
    
    if result is None:
        result = "It didn't return anything."

    return result

@tool
def repl_drawer(code):
    """
    Execute a Python script for draw a graph.
    Since Python runtime cannot use external APIs, necessary data must be included in the code.
    The graph should use English exclusively for all textual elements.
    Do not save pictures locally bacause the runtime does not have filesystem.
    When a comparison is made, all arrays must be of the same length.
    code: the Python code was written in English
    return: the url of graph
    """ 
        
    code = re.sub(r"seaborn", "classic", code)
    code = re.sub(r"plt.savefig", "#plt.savefig", code)
    code = re.sub(r"plt.show", "#plt.show", code)

    post = """\n
import io
import base64
buffer = io.BytesIO()
plt.savefig(buffer, format='png')
buffer.seek(0)
image_base64 = base64.b64encode(buffer.getvalue()).decode()

print(image_base64)
"""
    code = code + post    
    logger.info(f"code: {code}")
    
    result = ""
    try:     
        resp = repl.run(code)

        base64Img = resp
        
        if base64Img:
            byteImage = BytesIO(base64.b64decode(base64Img))

            image_name = generate_short_uuid()+'.png'
            url = chat.upload_to_s3(byteImage, image_name)
            logger.info(f"url: {url}")

            file_name = url[url.rfind('/')+1:]
            logger.info(f"file_name: {file_name}")

            global image_url
            image_url.append(path+'/'+s3_image_prefix+'/'+parse.quote(file_name))
            logger.info(f"image_url: {image_url}")
            result = f"생성된 그래프의 URL: {image_url}"

            # im = Image.open(BytesIO(base64.b64decode(base64Img)))  # for debuuing
            # im.save(image_name, 'PNG')

    except Exception:
        result = "그래프 생성에 실패했어요. 다시 시도해주세요."
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")

    logger.info(f"result: {result}")
    return result

       

####################### LangGraph #######################
# Chat Agent Executor
#########################################################
def run_agent_executor(query, historyMode, st):
    logger.info(f"###### run_agent_executor ######")
    logger.info(f"historyMode: {historyMode}")
    
    class State(TypedDict):
        # messages: Annotated[Sequence[BaseMessage], operator.add]
        messages: Annotated[list, add_messages]

    if chat.internet_mode == "Eanble":
        # tools = [get_current_time, get_book_list, get_weather_info, search_by_tavily, search_by_knowledge_base, stock_data_lookup, code_drawer, code_interpreter]        
        tools = [get_current_time, get_book_list, get_weather_info, search_by_tavily, search_by_knowledge_base, stock_data_lookup, repl_drawer, repl_coder] 
    else:
        tools = [get_current_time, get_book_list, get_weather_info, search_by_knowledge_base, stock_data_lookup, repl_drawer, repl_coder] 

    chatModel = chat.get_chat(chat.reasoning_mode)     
    model = chatModel.bind_tools(tools)
    tool_node = ToolNode(tools)

    def should_continue(state: State) -> Literal["continue", "end"]:
        logger.info(f"###### should_continue ######")

        logger.info(f"state: {state}")
        messages = state["messages"]    

        last_message = messages[-1]
        logger.info(f"last_message: {last_message}")

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            logger.info(f"{last_message.content}")
            if chat.debug_mode=='Enable' and last_message.content:
                st.info(f"last_message: {last_message.content}")

            for message in last_message.tool_calls:
                args = message['args']
                if chat.debug_mode=='Enable': 
                    if "code" in args:                    
                        state_msg = f"tool name: {message['name']}"
                        utils.status(st, state_msg)                    
                        utils.stcode(st, args['code'])
                    
                    elif chat.model_type=='claude':
                        state_msg = f"tool name: {message['name']}, args: {message['args']}"
                        utils.status(st, state_msg)

            logger.info(f"--- CONTINUE: {last_message.tool_calls[-1]['name']} ---")
            return "continue"
        
        #if not last_message.tool_calls:
        else:
            # logger.info(f"Final: {last_message.content}")
            logger.info(f"--- END ---")
            return "end"
           
    def call_model(state: State, config):
        logger.info(f"###### call_model ######")
        logger.info(f"state: {state['messages']}")
                
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

                # extended thinking
                if chat.debug_mode=="Enable":
                    chat.show_extended_thinking(st, response)

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

                                if chat.debug_mode=="Enable":
                                    utils.status(st, status)
                                
                            elif re['type'] == 'tool_use':                
                                logger.info(f"--> {re['type']}: {re['name']}, {re['input']}")

                                if chat.debug_mode=="Enable":
                                    utils.status(st, f"{re['type']}: {re['name']}, {re['input']}")
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

    # initiate
    global reference_docs, contentList, image_url
    reference_docs = []
    contentList = []
    image_url = []

    inputs = [HumanMessage(content=query)]

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
    
    # msg = message.content
    result = app.invoke({"messages": inputs}, config)
    #print("result: ", result)

    msg = result["messages"][-1].content
    logger.info(f"msg: {msg}")

    if historyMode == "Enable":
        snapshot = app.get_state(config)
        # logger.info(f"snapshot.values: {snapshot.values}")
        messages = snapshot.values["messages"]
        for i, m in enumerate(messages):
            logger.info(f"{i} --> {m.content}")
        logger.info(f"userId: {chat.userId}")

    for i, doc in enumerate(reference_docs):
        logger.info(f"--> {i}: {doc}")
        
    reference = ""
    if reference_docs:
        reference = chat.get_references(reference_docs)

    msg = chat.extract_thinking_tag(msg, st)
    
    return msg+reference, image_url, reference_docs

####################### LangGraph #######################
# Agentic Workflow: Tool Use (utilizing partial tool)
#########################################################

"""
def run_agent_executor2(query, st):        
    class State(TypedDict):
        messages: Annotated[list, add_messages]
        answer: str

    tool_node = ToolNode(tools)
            
    def create_agent(llm, tools):        
        tool_names = ", ".join([tool.name for tool in tools])
        logger.info(f"tool_names: {tool_names}")

        system = (
            "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다."
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다."
            "모르는 질문을 받으면 솔직히 모른다고 말합니다."

            "Use the provided tools to progress towards answering the question."
            "If you are unable to fully answer, that's OK, another assistant with different tools "
            "will help where you left off. Execute what you can to make progress."
            "You have access to the following tools: {tool_names}."
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system",system),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        
        prompt = prompt.partial(tool_names=tool_names)
        
        return prompt | llm.bind_tools(tools)
    
    def agent_node(state, agent, name):
        logger.info(f"###### agent_node:{name} ######")

        last_message = state["messages"][-1]
        logger.info(f"last_message: {last_message}")
        if isinstance(last_message, ToolMessage) and last_message.content=="":    
            logger.info(f"last_message is empty")
            answer = get_basic_answer(state["messages"][0].content)  
            return {
                "messages": [AIMessage(content=answer)],
                "answer": answer
            }
        
        response = agent.invoke(state["messages"])
        logger.info(f"response: {response}")

        if "answer" in state:
            answer = state['answer']
        else:
            answer = ""

        if isinstance(response.content, list):      
            for re in response.content:
                if "type" in re:
                    if re['type'] == 'text':
                        logger.info(f"--> {re['type']}: {re['text']}")

                        status = re['text']
                        if status.find('<thinking>') != -1:
                            logger.info(f"Remove <thinking> tag.")
                            status = status[status.find('<thinking>')+11:status.find('</thinking>')]
                            logger.info(f"'status without tag: {status}")

                        if chat.debug_mode=="Enable":
                            st.info(status)

                    elif re['type'] == 'tool_use':                
                        logger.info(f"--> {re['type']}: name: {re['name']}, input: {re['input']}")

                        if chat.debug_mode=="Enable":
                            st.info(f"{re['type']}: name: {re['name']}, input: {re['input']}")
                    else:
                        logger.info(re)
                else: # answer
                    answer += '\n'+response.content
                    logger.info(response.content)
                    break

        response = AIMessage(**response.dict(exclude={"type", "name"}), name=name)     
        logger.info(f"message: {response}")
        
        return {
            "messages": [response],
            "answer": answer
        }
    
    def final_answer(state):
        logger.info(f"###### final_answer ######")  

        answer = ""        
        if "answer" in state:
            answer = state['answer']            
        else:
            answer = state["messages"][-1].content

        if answer.find('<thinking>') != -1:
            logger.info(f"Remove <thinking> tag.")
            answer = answer[answer.find('</thinking>')+12:]
        logger.info(f"answer: {answer}")
        
        return {
            "answer": answer
        }
    
    llm = chat.get_chat(extended_thinking="Disable")
    
    execution_agent = create_agent(llm, tools)
    
    execution_agent_node = functools.partial(agent_node, agent=execution_agent, name="execution_agent")
    
    def should_continue(state: State, config) -> Literal["continue", "end"]:
        logger.info(f"###### should_continue ######")
        messages = state["messages"]    
        # print('(should_continue) messages: ', messages)
        
        last_message = messages[-1]        
        if not last_message.tool_calls:
            logger.info(f"Final: {last_message.content}")
            logger.info(f"-- END ---")
            return "end"
        else:      
            logger.info(f"tool_calls: {last_message.tool_calls}")

            for message in last_message.tool_calls:
                logger.info(f"tool name: {message['name']}, args: {message['args']}")
                # update_state_message(f"calling... {message['name']}", config)

            logger.info(f"--- CONTINUE: {last_message.tool_calls[-1]['name']} ---")
            return "continue"

    def buildAgentExecutor():
        workflow = StateGraph(State)

        workflow.add_node("agent", execution_agent_node)
        workflow.add_node("action", tool_node)
        workflow.add_node("final_answer", final_answer)
        
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {
                "continue": "action",
                "end": "final_answer",
            },
        )
        workflow.add_edge("action", "agent")
        workflow.add_edge("final_answer", END)

        return workflow.compile()

    app = buildAgentExecutor()
            
    inputs = [HumanMessage(content=query)]
    config = {"recursion_limit": 50}
    
    msg = ""
    # for event in app.stream({"messages": inputs}, config, stream_mode="values"):   
    #     # print('event: ', event)
        
    #     if "answer" in event:
    #         msg = event["answer"]
    #     else:
    #         msg = event["messages"][-1].content
    #     # print('message: ', message)

    output = app.invoke({"messages": inputs}, config)
    logger.info(f"output: {output}")

    msg = output['answer']

    return msg, reference_docs
"""