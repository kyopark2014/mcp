import traceback
import boto3
import os
import json
import re
import uuid
import base64
import info 
import PyPDF2
import csv
import utils
import strands_agent
import langgraph_agent
import mcp_config

from io import BytesIO
from PIL import Image
from langchain_aws import ChatBedrock
from botocore.config import Config
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain.memory import ConversationBufferWindowMemory
from langchain.docstore.document import Document
from tavily import TavilyClient  
from urllib import parse
from pydantic.v1 import BaseModel, Field
from langchain_core.output_parsers import StrOutputParser
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, AIMessageChunk
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from multiprocessing import Process, Pipe

import logging
import sys

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)

def ignore_urllib3_io_error(exctype, value, traceback):
    if exctype == ValueError and "I/O operation on closed file" in str(value):
        return
    sys.__excepthook__(exctype, value, traceback)

sys.excepthook = ignore_urllib3_io_error

logger = logging.getLogger("chat")

reasoning_mode = 'Disable'
debug_messages = []  # List to store debug messages

config = utils.load_config()
print(f"config: {config}")

bedrock_region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "mcp-rag"
accountId = config["accountId"] if "accountId" in config else None

if accountId is None:
    raise Exception ("No accountId")
region = config["region"] if "region" in config else "us-west-2"
logger.info(f"region: {region}")

s3_prefix = 'docs'
s3_image_prefix = 'images'

knowledge_base_role = config["knowledge_base_role"] if "knowledge_base_role" in config else None
if knowledge_base_role is None:
    raise Exception ("No Knowledge Base Role")

collectionArn = config["collectionArn"] if "collectionArn" in config else None
if collectionArn is None:
    raise Exception ("No collectionArn")

vectorIndexName = projectName

opensearch_url = config["opensearch_url"] if "opensearch_url" in config else None
if opensearch_url is None:
    raise Exception ("No OpenSearch URL")

path = config["sharing_url"] if "sharing_url" in config else None
if path is None:
    raise Exception ("No Sharing URL")

s3_arn = config["s3_arn"] if "s3_arn" in config else None
if s3_arn is None:
    raise Exception ("No S3 ARN")

s3_bucket = config["s3_bucket"] if "s3_bucket" in config else None
if s3_bucket is None:
    raise Exception ("No storage!")

knowledge_base_name = projectName
numberOfDocs = 4

MSG_LENGTH = 100    

doc_prefix = s3_prefix+'/'

model_name = "Claude 3.5 Sonnet"
model_type = "claude"
models = info.get_model_info(model_name)
number_of_models = len(models)
model_id = models[0]["model_id"]
debug_mode = "Enable"
multi_region = "Disable"

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

reasoning_mode = 'Disable'
grading_mode = 'Disable'
agent_type = 'langgraph'
user_id = agent_type # for testing

def update(modelName, debugMode, multiRegion, reasoningMode, gradingMode, agentType):    
    global model_name, model_id, model_type, debug_mode, multi_region, reasoning_mode, grading_mode
    global models, user_id, agent_type

    # load mcp.env    
    mcp_env = utils.load_mcp_env()
    
    if model_name != modelName:
        model_name = modelName
        logger.info(f"model_name: {model_name}")
        
        models = info.get_model_info(model_name)
        model_id = models[0]["model_id"]
        model_type = models[0]["model_type"]
                                
    if debug_mode != debugMode:
        debug_mode = debugMode        
        logger.info(f"debug_mode: {debug_mode}")

    if reasoning_mode != reasoningMode:
        reasoning_mode = reasoningMode
        logger.info(f"reasoning_mode: {reasoning_mode}")    

    if multi_region != multiRegion:
        multi_region = multiRegion
        logger.info(f"multi_region: {multi_region}")
        mcp_env['multi_region'] = multi_region

    if grading_mode != gradingMode:
        grading_mode = gradingMode
        logger.info(f"grading_mode: {grading_mode}")            
        mcp_env['grading_mode'] = grading_mode

    if agent_type != agentType:
        agent_type = agentType
        logger.info(f"agent_type: {agent_type}")

        logger.info(f"agent_type changed, update memory variables.")
        user_id = agent_type
        logger.info(f"user_id: {user_id}")
        mcp_env['user_id'] = user_id

    # update mcp.env    
    utils.save_mcp_env(mcp_env)
    # logger.info(f"mcp.env updated: {mcp_env}")

def update_mcp_env():
    mcp_env = utils.load_mcp_env()
    
    mcp_env['multi_region'] = multi_region
    mcp_env['grading_mode'] = grading_mode
    user_id = agent_type
    mcp_env['user_id'] = user_id

    utils.save_mcp_env(mcp_env)
    logger.info(f"mcp.env updated: {mcp_env}")

map_chain = dict() 
checkpointers = dict() 
memorystores = dict() 

checkpointer = MemorySaver()
memorystore = InMemoryStore()

def initiate():
    global memory_chain, checkpointer, memorystore, checkpointers, memorystores

    if user_id in map_chain:  
        logger.info(f"memory exist. reuse it!")
        memory_chain = map_chain[user_id]

        checkpointer = checkpointers[user_id]
        memorystore = memorystores[user_id]
    else: 
        logger.info(f"memory not exist. create new memory!")
        memory_chain = ConversationBufferWindowMemory(memory_key="chat_history", output_key='answer', return_messages=True, k=5)
        map_chain[user_id] = memory_chain

        checkpointer = MemorySaver()
        memorystore = InMemoryStore()

        checkpointers[user_id] = checkpointer
        memorystores[user_id] = memorystore

def clear_chat_history():
    global memory_chain
    memory_chain = []
    map_chain[user_id] = memory_chain

def save_chat_history(text, msg):
    memory_chain.chat_memory.add_user_message(text)
    if len(msg) > MSG_LENGTH:
        memory_chain.chat_memory.add_ai_message(msg[:MSG_LENGTH])                          
    else:
        memory_chain.chat_memory.add_ai_message(msg) 

def create_object(key, body):
    """
    Create an object in S3 and return the URL. If the file already exists, append the new content.
    """
    
    # Content-Type based on file extension
    content_type = 'application/octet-stream'  # default value
    if key.endswith('.html'):
        content_type = 'text/html'
    elif key.endswith('.md'):
        content_type = 'text/markdown'
    
    if aws_access_key and aws_secret_key:
        s3_client = boto3.client(
            service_name='s3',
            region_name=bedrock_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
        )
    else:
        s3_client = boto3.client(
            service_name='s3',
            region_name=bedrock_region,
        )
        
    s3_client.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=body,
        ContentType=content_type
    )  

def updata_object(key, body, direction):
    """
    Create an object in S3 and return the URL. If the file already exists, append the new content.
    """
    if aws_access_key and aws_secret_key:
        s3_client = boto3.client(
            service_name='s3',
            region_name=bedrock_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
        )
    else:
        s3_client = boto3.client(
            service_name='s3',
            region_name=bedrock_region,
        )

    try:
        # Check if file exists
        try:
            response = s3_client.get_object(Bucket=s3_bucket, Key=key)
            existing_body = response['Body'].read().decode('utf-8')
            # Append new content to existing content

            if direction == 'append':
                updated_body = existing_body + '\n' + body
            else: # prepend
                updated_body = body + '\n' + existing_body
        except s3_client.exceptions.NoSuchKey:
            # File doesn't exist, use new body as is
            updated_body = body
            
        # Content-Type based on file extension
        content_type = 'application/octet-stream'  # default value
        if key.endswith('.html'):
            content_type = 'text/html'
        elif key.endswith('.md'):
            content_type = 'text/markdown'
            
        # Upload the updated content
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=key,
            Body=updated_body,
            ContentType=content_type
        )
        
    except Exception as e:
        logger.error(f"Error updating object in S3: {str(e)}")
        raise e

selected_chat = 0
def get_chat(extended_thinking):
    global selected_chat, model_type

    logger.info(f"models: {models}")
    logger.info(f"selected_chat: {selected_chat}")
    
    profile = models[selected_chat]
    # print('profile: ', profile)
        
    bedrock_region =  profile['bedrock_region']
    modelId = profile['model_id']
    model_type = profile['model_type']
    if model_type == 'claude':
        maxOutputTokens = 4096 # 4k
    else:
        maxOutputTokens = 5120 # 5k
    number_of_models = len(models)

    logger.info(f"LLM: {selected_chat}, bedrock_region: {bedrock_region}, modelId: {modelId}, model_type: {model_type}")

    if profile['model_type'] == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif profile['model_type'] == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 
                          
    # bedrock   
    if aws_access_key and aws_secret_key:
        boto3_bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=bedrock_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
            config=Config(
                retries = {
                    'max_attempts': 30
                }
            )
        )
    else:
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

def print_doc(i, doc):
    if len(doc.page_content)>=100:
        text = doc.page_content[:100]
    else:
        text = doc.page_content
            
    logger.info(f"{i}: {text}, metadata:{doc.metadata}")

def translate_text(text):
    chat = get_chat(extended_thinking=reasoning_mode)

    system = (
        "You are a helpful assistant that translates {input_language} to {output_language} in <article> tags. Put it in <result> tags."
    )
    human = "<article>{text}</article>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    if isKorean(text)==False :
        input_language = "English"
        output_language = "Korean"
    else:
        input_language = "Korean"
        output_language = "English"
                        
    chain = prompt | chat    
    try: 
        result = chain.invoke(
            {
                "input_language": input_language,
                "output_language": output_language,
                "text": text,
            }
        )
        msg = result.content
        logger.info(f"translated text: {msg}")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")      
        raise Exception ("Not able to request to LLM")

    return msg[msg.find('<result>')+8:len(msg)-9] # remove <result> tag
    
def check_grammer(text):
    chat = get_chat(extended_thinking=reasoning_mode)

    if isKorean(text)==True:
        system = (
            "다음의 <article> tag안의 문장의 오류를 찾아서 설명하고, 오류가 수정된 문장을 답변 마지막에 추가하여 주세요."
        )
    else: 
        system = (
            "Here is pieces of article, contained in <article> tags. Find the error in the sentence and explain it, and add the corrected sentence at the end of your answer."
        )
        
    human = "<article>{text}</article>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    chain = prompt | chat    
    try: 
        result = chain.invoke(
            {
                "text": text
            }
        )
        
        msg = result.content
        logger.info(f"result of grammer correction: {msg}")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")       
        raise Exception ("Not able to request to LLM")
    
    return msg

reference_docs = []
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
        region_name=bedrock_region,
    )

# api key for weather
weather_api_key = ""
try:
    get_weather_api_secret = secretsmanager.get_secret_value(
        SecretId=f"openweathermap-{projectName}"
    )
    #print('get_weather_api_secret: ', get_weather_api_secret)
    secret = json.loads(get_weather_api_secret['SecretString'])
    #print('secret: ', secret)
    weather_api_key = secret['weather_api_key']

except Exception as e:
    raise e

# api key to use LangSmith
langsmith_api_key = ""
try:
    get_langsmith_api_secret = secretsmanager.get_secret_value(
        SecretId=f"langsmithapikey-{projectName}"
    )
    #print('get_langsmith_api_secret: ', get_langsmith_api_secret)
    secret = json.loads(get_langsmith_api_secret['SecretString'])
    #print('secret: ', secret)
    langsmith_api_key = secret['langsmith_api_key']
    langchain_project = secret['langchain_project']
except Exception as e:
    raise e

if langsmith_api_key:
    os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = langchain_project
    
def tavily_search(query, k):
    docs = []    
    try:
        tavily_client = TavilyClient(api_key=utils.tavily_key)
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
    
def traslation(chat, text, input_language, output_language):
    system = (
        "You are a helpful assistant that translates {input_language} to {output_language} in <article> tags." 
        "Put it in <result> tags."
    )
    human = "<article>{text}</article>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    chain = prompt | chat    
    try: 
        result = chain.invoke(
            {
                "input_language": input_language,
                "output_language": output_language,
                "text": text,
            }
        )
        
        msg = result.content
        # print('translated text: ', msg)
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")     
        raise Exception ("Not able to request to LLM")

    return msg[msg.find('<result>')+8:len(msg)-9] # remove <result> tag

def get_parallel_processing_chat(models, selected):
    global model_type
    profile = models[selected]
    bedrock_region =  profile['bedrock_region']
    modelId = profile['model_id']
    model_type = profile['model_type']
    maxOutputTokens = 4096
    logger.info(f'selected_chat: {selected}, bedrock_region: {bedrock_region}, modelId: {modelId}, model_type: {model_type}')

    if profile['model_type'] == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif profile['model_type'] == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 
                          
    # bedrock   
    if aws_access_key and aws_secret_key:
        boto3_bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=bedrock_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
            config=Config(
                retries = {
                    'max_attempts': 30
                }
            )
        )
    else:
        boto3_bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=bedrock_region,
            config=Config(
                retries = {
                    'max_attempts': 30
                }
            )
        )

    parameters = {
        "max_tokens":maxOutputTokens,     
        "temperature":0.1,
        "top_k":250,
        "top_p":0.9,
        "stop_sequences": [STOP_SEQUENCE]
    }
    # print('parameters: ', parameters)

    chat = ChatBedrock(   # new chat model
        model_id=modelId,
        client=boto3_bedrock, 
        model_kwargs=parameters,
    )        
    return chat

def print_doc(i, doc):
    if len(doc.page_content)>=100:
        text = doc.page_content[:100]
    else:
        text = doc.page_content
            
    logger.info(f"{i}: {text}, metadata:{doc.metadata}")

def grade_document_based_on_relevance(conn, question, doc, models, selected):     
    chat = get_parallel_processing_chat(models, selected)
    retrieval_grader = get_retrieval_grader(chat)
    score = retrieval_grader.invoke({"question": question, "document": doc.page_content})
    # print(f"score: {score}")
    
    grade = score.binary_score    
    if grade == 'yes':
        logger.info(f"---GRADE: DOCUMENT RELEVANT---")
        conn.send(doc)
    else:  # no
        logger.info(f"--GRADE: DOCUMENT NOT RELEVANT---")
        conn.send(None)
    
    conn.close()

def grade_documents_using_parallel_processing(question, documents):
    global selected_chat
    
    filtered_docs = []    

    processes = []
    parent_connections = []
    
    for i, doc in enumerate(documents):
        #print(f"grading doc[{i}]: {doc.page_content}")        
        parent_conn, child_conn = Pipe()
        parent_connections.append(parent_conn)
            
        process = Process(target=grade_document_based_on_relevance, args=(child_conn, question, doc, models, selected_chat))
        processes.append(process)
        
        selected_chat = selected_chat + 1
        if selected_chat == number_of_models:
            selected_chat = 0
    for process in processes:
        process.start()
            
    for parent_conn in parent_connections:
        relevant_doc = parent_conn.recv()

        if relevant_doc is not None:
            filtered_docs.append(relevant_doc)

    for process in processes:
        process.join()
    
    return filtered_docs

class GradeDocuments(BaseModel):
    """Binary score for relevance check on retrieved documents."""

    binary_score: str = Field(description="Documents are relevant to the question, 'yes' or 'no'")

def get_retrieval_grader(chat):
    system = """You are a grader assessing relevance of a retrieved document to a user question. \n 
    If the document contains keyword(s) or semantic meaning related to the question, grade it as relevant. \n
    Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question."""

    grade_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("human", "Retrieved document: \n\n {document} \n\n User question: {question}"),
        ]
    )
    
    # from langchain_core.output_parsers import PydanticOutputParser  # not supported for Nova
    # parser = PydanticOutputParser(pydantic_object=GradeDocuments)
    # retrieval_grader = grade_prompt | chat | parser

    structured_llm_grader = chat.with_structured_output(GradeDocuments)
    retrieval_grader = grade_prompt | structured_llm_grader
    return retrieval_grader

def show_extended_thinking(st, result):
    # logger.info(f"result: {result}")
    if "thinking" in result.response_metadata:
        if "text" in result.response_metadata["thinking"]:
            thinking = result.response_metadata["thinking"]["text"]
            st.info(thinking)

def grade_documents(question, documents):
    logger.info(f"###### grade_documents ######")
    
    logger.info(f"start grading...")
    
    filtered_docs = []
    if multi_region == 'Enable':  # parallel processing        
        filtered_docs = grade_documents_using_parallel_processing(question, documents)

    else:
        # Score each doc    
        llm = get_chat(extended_thinking="Disable")
        retrieval_grader = get_retrieval_grader(llm)
        for i, doc in enumerate(documents):
            # print('doc: ', doc)
            print_doc(i, doc)
            
            score = retrieval_grader.invoke({"question": question, "document": doc.page_content})
            # print("score: ", score)
            
            grade = score.binary_score
            # print("grade: ", grade)
            # Document relevant
            if grade.lower() == "yes":
                logger.info(f"---GRADE: DOCUMENT RELEVANT---")
                filtered_docs.append(doc)
            # Document not relevant
            else:
                logger.info(f"---GRADE: DOCUMENT NOT RELEVANT---")
                # We do not include the document in filtered_docs
                # We set a flag to indicate that we want to run web search
                continue

    return filtered_docs

####################### LangChain #######################
# General Conversation
#########################################################
def general_conversation(query):
    llm = get_chat(extended_thinking=reasoning_mode)

    system = (
        "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
        "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다." 
        "모르는 질문을 받으면 솔직히 모른다고 말합니다."
    )
    
    human = "Question: {input}"
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system), 
        MessagesPlaceholder(variable_name="history"), 
        ("human", human)
    ])
                
    history = memory_chain.load_memory_variables({})["chat_history"]

    chain = prompt | llm | StrOutputParser()
    try: 
        stream = chain.stream(
            {
                "history": history,
                "input": query,
            }
        )  
        logger.info(f"stream: {stream}")
            
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")      
        raise Exception ("Not able to request to LLM: "+err_msg)
        
    return stream

def upload_to_s3(file_bytes, file_name):
    """
    Upload a file to S3 and return the URL
    """
    try:
        if aws_access_key and aws_secret_key:
            s3_client = boto3.client(
                service_name='s3',
                region_name=bedrock_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                aws_session_token=aws_session_token,
            )
        else:
            s3_client = boto3.client(
                service_name='s3',
                region_name=bedrock_region,
            )

        # Generate a unique file name to avoid collisions
        #timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        #unique_id = str(uuid.uuid4())[:8]
        #s3_key = f"uploaded_images/{timestamp}_{unique_id}_{file_name}"

        content_type = utils.get_contents_type(file_name)       
        logger.info(f"content_type: {content_type}") 

        if content_type == "image/jpeg" or content_type == "image/png":
            s3_key = f"{s3_image_prefix}/{file_name}"
        else:
            s3_key = f"{s3_prefix}/{file_name}"
        
        user_meta = {  # user-defined metadata
            "content_type": content_type,
            "model_name": model_name
        }
        
        response = s3_client.put_object(
            Bucket=s3_bucket, 
            Key=s3_key, 
            ContentType=content_type,
            Metadata = user_meta,
            Body=file_bytes            
        )
        logger.info(f"upload response: {response}")

        #url = f"https://{s3_bucket}.s3.amazonaws.com/{s3_key}"
        url = path+'/'+s3_image_prefix+'/'+parse.quote(file_name)
        return url
    
    except Exception as e:
        err_msg = f"Error uploading to S3: {str(e)}"
        logger.info(f"{err_msg}")
        return None

def upload_to_s3_artifacts(file_bytes, file_name):
    """
    Upload a file to S3 and return the URL
    """
    try:
        if aws_access_key and aws_secret_key:
            s3_client = boto3.client(
                service_name='s3',
                region_name=bedrock_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                aws_session_token=aws_session_token
            )
        else:
            s3_client = boto3.client(
                service_name='s3',
                region_name=bedrock_region
        )

        content_type = utils.get_contents_type(file_name)       
        logger.info(f"content_type: {content_type}") 

        s3_key = f"artifacts/{file_name}"
        
        user_meta = {  # user-defined metadata
            "content_type": content_type,
            "model_name": model_name
        }
        
        response = s3_client.put_object(
            Bucket=s3_bucket, 
            Key=s3_key, 
            ContentType=content_type,
            Metadata = user_meta,
            Body=file_bytes            
        )
        logger.info(f"upload response: {response}")

        url = path+'/artifacts/'+parse.quote(file_name)
        return url
    
    except Exception as e:
        err_msg = f"Error uploading to S3: {str(e)}"
        logger.info(f"{err_msg}")
        return None

def extract_and_display_s3_images(text, s3_client):
    """
    Extract S3 URLs from text, download images, and return them for display
    """
    s3_pattern = r"https://[\w\-\.]+\.s3\.amazonaws\.com/[\w\-\./]+"
    s3_urls = re.findall(s3_pattern, text)

    images = []
    for url in s3_urls:
        try:
            bucket = url.split(".s3.amazonaws.com/")[0].split("//")[1]
            key = url.split(".s3.amazonaws.com/")[1]

            response = s3_client.get_object(Bucket=bucket, Key=key)
            image_data = response["Body"].read()

            image = Image.open(BytesIO(image_data))
            images.append(image)

        except Exception as e:
            err_msg = f"Error downloading image from S3: {str(e)}"
            logger.info(f"{err_msg}")
            continue

    return images

# load csv documents from s3
def load_csv_document(s3_file_name):
    s3r = boto3.resource("s3")
    doc = s3r.Object(s3_bucket, s3_prefix+'/'+s3_file_name)

    lines = doc.get()['Body'].read().decode('utf-8').split('\n')   # read csv per line
    logger.info(f"prelinspare: {len(lines)}")
        
    columns = lines[0].split(',')  # get columns
    #columns = ["Category", "Information"]  
    #columns_to_metadata = ["type","Source"]
    logger.info(f"columns: {columns}")
    
    docs = []
    n = 0
    for row in csv.DictReader(lines, delimiter=',',quotechar='"'):
        # print('row: ', row)
        #to_metadata = {col: row[col] for col in columns_to_metadata if col in row}
        values = {k: row[k] for k in columns if k in row}
        content = "\n".join(f"{k.strip()}: {v.strip()}" for k, v in values.items())
        doc = Document(
            page_content=content,
            metadata={
                'name': s3_file_name,
                'row': n+1,
            }
            #metadata=to_metadata
        )
        docs.append(doc)
        n = n+1
    logger.info(f"docs[0]: {docs[0]}")

    return docs

def get_summary(docs):    
    llm = get_chat(extended_thinking=reasoning_mode)

    text = ""
    for doc in docs:
        text = text + doc
    
    if isKorean(text)==True:
        system = (
            "다음의 <article> tag안의 문장을 요약해서 500자 이내로 설명하세오."
        )
    else: 
        system = (
            "Here is pieces of article, contained in <article> tags. Write a concise summary within 500 characters."
        )
    
    human = "<article>{text}</article>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    chain = prompt | llm    
    try: 
        result = chain.invoke(
            {
                "text": text
            }
        )
        
        summary = result.content
        logger.info(f"esult of summarization: {summary}")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}") 
        raise Exception ("Not able to request to LLM")
    
    return summary

# load documents from s3 for pdf and txt
def load_document(file_type, s3_file_name):
    s3r = boto3.resource("s3")
    doc = s3r.Object(s3_bucket, s3_prefix+'/'+s3_file_name)
    logger.info(f"s3_bucket: {s3_bucket}, s3_prefix: {s3_prefix}, s3_file_name: {s3_file_name}")
    
    contents = ""
    if file_type == 'pdf':
        contents = doc.get()['Body'].read()
        reader = PyPDF2.PdfReader(BytesIO(contents))
        
        raw_text = []
        for page in reader.pages:
            raw_text.append(page.extract_text())
        contents = '\n'.join(raw_text)    
        
    elif file_type == 'txt' or file_type == 'md':        
        contents = doc.get()['Body'].read().decode('utf-8')
        
    logger.info(f"contents: {contents}")
    new_contents = str(contents).replace("\n"," ") 
    logger.info(f"length: {len(new_contents)}")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", " ", ""],
        length_function = len,
    ) 
    texts = text_splitter.split_text(new_contents) 
    if texts:
        logger.info(f"exts[0]: {texts[0]}")
    
    return texts

def summary_of_code(code, mode):
    if mode == 'py':
        system = (
            "다음의 <article> tag에는 python code가 있습니다."
            "code의 전반적인 목적에 대해 설명하고, 각 함수의 기능과 역할을 자세하게 한국어 500자 이내로 설명하세요."
        )
    elif mode == 'js':
        system = (
            "다음의 <article> tag에는 node.js code가 있습니다." 
            "code의 전반적인 목적에 대해 설명하고, 각 함수의 기능과 역할을 자세하게 한국어 500자 이내로 설명하세요."
        )
    else:
        system = (
            "다음의 <article> tag에는 code가 있습니다."
            "code의 전반적인 목적에 대해 설명하고, 각 함수의 기능과 역할을 자세하게 한국어 500자 이내로 설명하세요."
        )
    
    human = "<article>{code}</article>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    llm = get_chat(extended_thinking=reasoning_mode)

    chain = prompt | llm    
    try: 
        result = chain.invoke(
            {
                "code": code
            }
        )
        
        summary = result.content
        logger.info(f"result of code summarization: {summary}")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")        
        raise Exception ("Not able to request to LLM")
    
    return summary

def summary_image(img_base64, instruction):      
    llm = get_chat(extended_thinking=reasoning_mode)

    if instruction:
        logger.info(f"instruction: {instruction}")
        query = f"{instruction}. <result> tag를 붙여주세요."
        
    else:
        query = "이미지가 의미하는 내용을 풀어서 자세히 알려주세요. markdown 포맷으로 답변을 작성합니다."
    
    messages = [
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}", 
                    },
                },
                {
                    "type": "text", "text": query
                },
            ]
        )
    ]
    
    for attempt in range(5):
        logger.info(f"attempt: {attempt}")
        try: 
            result = llm.invoke(messages)
            
            extracted_text = result.content
            # print('summary from an image: ', extracted_text)
            break
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")                    
            raise Exception ("Not able to request to LLM")
        
    return extracted_text

def extract_text(img_base64):    
    multimodal = get_chat(extended_thinking=reasoning_mode)
    query = "텍스트를 추출해서 markdown 포맷으로 변환하세요. <result> tag를 붙여주세요."
    
    extracted_text = ""
    messages = [
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}", 
                    },
                },
                {
                    "type": "text", "text": query
                },
            ]
        )
    ]
    
    for attempt in range(5):
        logger.info(f"attempt: {attempt}")
        try: 
            result = multimodal.invoke(messages)
            
            extracted_text = result.content
            # print('result of text extraction from an image: ', extracted_text)
            break
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")                    
            # raise Exception ("Not able to request to LLM")
    
    logger.info(f"Extracted_text: {extracted_text}")
    if len(extracted_text)<10:
        extracted_text = "텍스트를 추출하지 못하였습니다."    

    return extracted_text

fileId = uuid.uuid4().hex
# print('fileId: ', fileId)
def get_summary_of_uploaded_file(file_name, st):
    file_type = file_name[file_name.rfind('.')+1:len(file_name)]            
    logger.info(f"file_type: {file_type}")
    
    if file_type == 'csv':
        docs = load_csv_document(file_name)
        contexts = []
        for doc in docs:
            contexts.append(doc.page_content)
        logger.info(f"contexts: {contexts}")
    
        msg = get_summary(contexts)

    elif file_type == 'pdf' or file_type == 'txt' or file_type == 'md' or file_type == 'pptx' or file_type == 'docx':
        texts = load_document(file_type, file_name)

        if len(texts):
            docs = []
            for i in range(len(texts)):
                docs.append(
                    Document(
                        page_content=texts[i],
                        metadata={
                            'name': file_name,
                            # 'page':i+1,
                            'url': path+'/'+doc_prefix+parse.quote(file_name)
                        }
                    )
                )
            logger.info(f"docs[0]: {docs[0]}") 
            logger.info(f"docs size: {len(docs)}")

            contexts = []
            for doc in docs:
                contexts.append(doc.page_content)
            logger.info(f"contexts: {contexts}")

            msg = get_summary(contexts)
        else:
            msg = "문서 로딩에 실패하였습니다."
        
    elif file_type == 'py' or file_type == 'js':
        s3r = boto3.resource("s3")
        doc = s3r.Object(s3_bucket, s3_prefix+'/'+file_name)
        
        contents = doc.get()['Body'].read().decode('utf-8')
        
        #contents = load_code(file_type, object)                
                        
        msg = summary_of_code(contents, file_type)                  
        
    elif file_type == 'png' or file_type == 'jpeg' or file_type == 'jpg':
        logger.info(f"multimodal: {file_name}")
        
        if aws_access_key and aws_secret_key:
            s3_client = boto3.client(
                service_name='s3',
                region_name=bedrock_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                aws_session_token=aws_session_token,
            )
        else:
            s3_client = boto3.client(
                service_name='s3',
                region_name=bedrock_region,
            )

        if debug_mode=="Enable":
            status = "이미지를 가져옵니다."
            logger.info(f"status: {status}")
            st.info(status)
            
        image_obj = s3_client.get_object(Bucket=s3_bucket, Key=s3_prefix+'/'+file_name)
        # print('image_obj: ', image_obj)
        
        image_content = image_obj['Body'].read()
        img = Image.open(BytesIO(image_content))
        
        width, height = img.size 
        logger.info(f"width: {width}, height: {height}, size: {width*height}")
        
        # Image resizing and size verification
        isResized = False
        max_size = 5 * 1024 * 1024  # 5MB in bytes
        
        # Initial resizing (based on pixel count)
        while(width*height > 2000000):  # Limit to approximately 2M pixels
            width = int(width/2)
            height = int(height/2)
            isResized = True
            logger.info(f"width: {width}, height: {height}, size: {width*height}")
        
        if isResized:
            img = img.resize((width, height))
        
        # Base64 크기 확인 및 추가 리사이징
        max_attempts = 5
        for attempt in range(max_attempts):
            buffer = BytesIO()
            img.save(buffer, format="PNG", optimize=True)
            img_bytes = buffer.getvalue()
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            
            # Base64 크기 확인 (실제 전송될 크기)
            base64_size = len(img_base64.encode('utf-8'))
            logger.info(f"attempt {attempt + 1}: base64_size = {base64_size} bytes")
            
            if base64_size <= max_size:
                break
            else:
                # 크기가 여전히 크면 더 작게 리사이징
                width = int(width * 0.8)
                height = int(height * 0.8)
                img = img.resize((width, height))
                logger.info(f"resizing to {width}x{height} due to size limit")
        
        if base64_size > max_size:
            logger.warning(f"Image still too large after {max_attempts} attempts: {base64_size} bytes")
            raise Exception(f"이미지 크기가 너무 큽니다. 5MB 이하의 이미지를 사용해주세요.")
               
        # extract text from the image
        if debug_mode=="Enable":
            status = "이미지에서 텍스트를 추출합니다."
            logger.info(f"status: {status}")
            st.info(status)
        
        text = extract_text(img_base64)
        # print('extracted text: ', text)

        if text.find('<result>') != -1:
            extracted_text = text[text.find('<result>')+8:text.find('</result>')] # remove <result> tag
            # print('extracted_text: ', extracted_text)
        else:
            extracted_text = text

        if debug_mode=="Enable":
            logger.info(f"### 추출된 텍스트\n\n{extracted_text}")
            print('status: ', status)
            st.info(status)
    
        if debug_mode=="Enable":
            status = "이미지의 내용을 분석합니다."
            logger.info(f"status: {status}")
            st.info(status)

        image_summary = summary_image(img_base64, "")
        logger.info(f"image summary: {image_summary}")
            
        if len(extracted_text) > 10:
            contents = f"## 이미지 분석\n\n{image_summary}\n\n## 추출된 텍스트\n\n{extracted_text}"
        else:
            contents = f"## 이미지 분석\n\n{image_summary}"
        logger.info(f"image content: {contents}")

        msg = contents

    global fileId
    fileId = uuid.uuid4().hex
    # print('fileId: ', fileId)

    return msg

####################### LangChain #######################
# Image Summarization
#########################################################
def get_image_summarization(object_name, prompt, st):
    # load image
    if aws_access_key and aws_secret_key:
        s3_client = boto3.client(
            service_name='s3',
            region_name=bedrock_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
        )
    else:
        s3_client = boto3.client(
            service_name='s3',
            region_name=bedrock_region,
        )

    if debug_mode=="Enable":
        status = "이미지를 가져옵니다."
        logger.info(f"status: {status}")
        st.info(status)
                
    image_obj = s3_client.get_object(Bucket=s3_bucket, Key=s3_image_prefix+'/'+object_name)
    # print('image_obj: ', image_obj)
    
    image_content = image_obj['Body'].read()
    img = Image.open(BytesIO(image_content))
    
    width, height = img.size 
    logger.info(f"width: {width}, height: {height}, size: {width*height}")
    
    # 이미지 리사이징 및 크기 확인
    isResized = False
    max_size = 5 * 1024 * 1024  # 5MB in bytes
    
    # Initial resizing (based on pixel count)
    while(width*height > 2000000):  # Limit to approximately 2M pixels
        width = int(width/2)
        height = int(height/2)
        isResized = True
        logger.info(f"width: {width}, height: {height}, size: {width*height}")
    
    if isResized:
        img = img.resize((width, height))
    
    # Base64 size verification and additional resizing
    max_attempts = 5
    for attempt in range(max_attempts):
        buffer = BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        img_bytes = buffer.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        
        # Base64 size verification (actual transmission size)
        base64_size = len(img_base64.encode('utf-8'))
        logger.info(f"attempt {attempt + 1}: base64_size = {base64_size} bytes")
        
        if base64_size <= max_size:
            break
        else:
            # Resize smaller if still too large
            width = int(width * 0.8)
            height = int(height * 0.8)
            img = img.resize((width, height))
            logger.info(f"resizing to {width}x{height} due to size limit")
    
    if base64_size > max_size:
        logger.warning(f"Image still too large after {max_attempts} attempts: {base64_size} bytes")
        raise Exception(f"이미지 크기가 너무 큽니다. 5MB 이하의 이미지를 사용해주세요.")

    # extract text from the image
    if debug_mode=="Enable":
        status = "이미지에서 텍스트를 추출합니다."
        logger.info(f"status: {status}")
        st.info(status)

    text = extract_text(img_base64)
    logger.info(f"extracted text: {text}")

    if text.find('<result>') != -1:
        extracted_text = text[text.find('<result>')+8:text.find('</result>')] # remove <result> tag
        # print('extracted_text: ', extracted_text)
    else:
        extracted_text = text
    
    if debug_mode=="Enable":
        status = f"### 추출된 텍스트\n\n{extracted_text}"
        logger.info(f"status: {status}")
        st.info(status)
    
    if debug_mode=="Enable":
        status = "이미지의 내용을 분석합니다."
        logger.info(f"status: {status}")
        st.info(status)

    image_summary = summary_image(img_base64, prompt)
    
    if text.find('<result>') != -1:
        image_summary = image_summary[image_summary.find('<result>')+8:image_summary.find('</result>')]
    logger.info(f"image summary: {image_summary}")
            
    if len(extracted_text) > 10:
        contents = f"## 이미지 분석\n\n{image_summary}\n\n## 추출된 텍스트\n\n{extracted_text}"
    else:
        contents = f"## 이미지 분석\n\n{image_summary}"
    logger.info(f"image contents: {contents}")

    return contents


####################### Bedrock Agent #######################
# RAG using Lambda
############################################################# 
def get_rag_prompt(text):
    # print("###### get_rag_prompt ######")
    llm = get_chat(extended_thinking=reasoning_mode)
    # print('model_type: ', model_type)
    
    if model_type == "nova":
        if isKorean(text)==True:
            system = (
                "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
                "다음의 Reference texts을 이용하여 user의 질문에 답변합니다."
                "모르는 질문을 받으면 솔직히 모른다고 말합니다."
                "답변의 이유를 풀어서 명확하게 설명합니다."
            )
        else: 
            system = (
                "You will be acting as a thoughtful advisor."
                "Provide a concise answer to the question at the end using reference texts." 
                "If you don't know the answer, just say that you don't know, don't try to make up an answer."
                "You will only answer in text format, using markdown format is not allowed."
            )    
    
        human = (
            "Question: {question}"

            "Reference texts: "
            "{context}"
        ) 
        
    elif model_type == "claude":
        if isKorean(text)==True:
            system = (
                "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
                "다음의 <context> tag안의 참고자료를 이용하여 상황에 맞는 구체적인 세부 정보를 충분히 제공합니다." 
                "모르는 질문을 받으면 솔직히 모른다고 말합니다."
                "답변의 이유를 풀어서 명확하게 설명합니다."
                "결과는 <result> tag를 붙여주세요."
            )
        else: 
            system = (
                "You will be acting as a thoughtful advisor."
                "Here is pieces of context, contained in <context> tags." 
                "If you don't know the answer, just say that you don't know, don't try to make up an answer."
                "You will only answer in text format, using markdown format is not allowed."
                "Put it in <result> tags."
            )    

        human = (
            "<question>"
            "{question}"
            "</question>"

            "<context>"
            "{context}"
            "</context>"
        )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    rag_chain = prompt | llm

    return rag_chain
 
def retrieve_knowledge_base(query):
    if aws_access_key and aws_secret_key:
        lambda_client = boto3.client(
            service_name='lambda',
            region_name=bedrock_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_session_token,
        )
    else:
        lambda_client = boto3.client(
            service_name='lambda',
            region_name=bedrock_region,
        )

    functionName = f"knowledge-base-for-{projectName}"
    logger.info(f"functionName: {functionName}")

    try:
        payload = {
            'function': 'search_rag',
            'knowledge_base_name': knowledge_base_name,
            'keyword': query,
            'top_k': numberOfDocs,
            'grading': grading_mode,
            'model_name': model_name,
            'multi_region': multi_region
        }
        logger.info(f"payload: {payload}")

        output = lambda_client.invoke(
            FunctionName=functionName,
            Payload=json.dumps(payload),
        )
        payload = json.load(output['Payload'])
        logger.info(f"response: {payload['response']}")
        
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")       

    return payload['response']

def get_reference_docs(docs):    
    reference_docs = []
    for doc in docs:
        reference = doc.get("reference")
        reference_docs.append(
            Document(
                page_content=doc.get("contents"),
                metadata={
                    'name': reference.get("title"),
                    'url': reference.get("url"),
                    'from': reference.get("from")
                },
            )
        )     
    return reference_docs

def run_rag_with_knowledge_base(query, st):
    global reference_docs, contentList
    reference_docs = []
    contentList = []

    # retrieve
    if debug_mode == "Enable":
        st.info(f"RAG 검색을 수행합니다. 검색어: {query}")  

    relevant_context = retrieve_knowledge_base(query)    
    logger.info(f"relevant_context: {relevant_context}")
    
    # change format to document
    reference_docs = get_reference_docs(json.loads(relevant_context))
    st.info(f"{len(reference_docs)}개의 관련된 문서를 얻었습니다.")

    rag_chain = get_rag_prompt(query)
                       
    msg = ""    
    try: 
        result = rag_chain.invoke(
            {
                "question": query,
                "context": relevant_context                
            }
        )
        logger.info(f"result: {result}")

        msg = result.content        
        if msg.find('<result>')!=-1:
            msg = msg[msg.find('<result>')+8:msg.find('</result>')]        
               
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")                    
        raise Exception ("Not able to request to LLM")
    
    if reference_docs:
        logger.info(f"reference_docs: {reference_docs}")
        ref = "\n\n### Reference\n"
        for i, reference in enumerate(reference_docs):
            ref += f"{i+1}. [{reference.metadata['name']}]({reference.metadata['url']}), {reference.page_content[:100]}...\n"    
        logger.info(f"ref: {ref}")
        msg += ref
    
    return msg, reference_docs
   
def extract_thinking_tag(response, st):
    if response.find('<thinking>') != -1:
        status = response[response.find('<thinking>')+10:response.find('</thinking>')]
        logger.info(f"gent_thinking: {status}")
        
        if debug_mode=="Enable":
            st.info(status)

        if response.find('<thinking>') == 0:
            msg = response[response.find('</thinking>')+12:]
        else:
            msg = response[:response.find('<thinking>')]
        logger.info(f"msg: {msg}")
    else:
        msg = response

    return msg

streaming_index = None
index = 0
def add_notification(containers, message):
    global index

    if index == streaming_index:
        index += 1

    if containers is not None:
        containers['notification'][index].info(message)
    index += 1

def update_streaming_result(containers, message):
    global streaming_index
    streaming_index = index 

    if containers is not None:
        containers['notification'][streaming_index].markdown(message)

def update_tool_notification(containers, tool_index, message):
    if containers is not None:
        containers['notification'][tool_index].info(message)

tool_info_list = dict()
tool_result_list = dict()

async def run_strands_agent(query, mcp_servers, history_mode, containers):
    global tool_list, index
    tool_list = []
    index = 0

    # # initate memory variables
    # memory_id, actor_id, session_id, namespace = agentcore_memory.load_memory_variables(chat.user_id)
    # logger.info(f"memory_id: {memory_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")

    # if memory_id is None:
    #     # retrieve memory id
    #     memory_id = agentcore_memory.retrieve_memory_id()
    #     logger.info(f"memory_id: {memory_id}")        
        
    #     # create memory if not exists
    #     if memory_id is None:
    #         logger.info(f"Memory will be created...")
    #         memory_id = agentcore_memory.create_memory(namespace)
    #         logger.info(f"Memory was created... {memory_id}")
        
    #     # create strategy if not exists
    #     agentcore_memory.create_strategy_if_not_exists(
    #         memory_id=memory_id, namespace=namespace, strategy_name=chat.user_id)

    #     # save memory variables
    #     agentcore_memory.update_memory_variables(
    #         user_id=chat.user_id, 
    #         memory_id=memory_id, 
    #         actor_id=actor_id, 
    #         session_id=session_id, 
    #         namespace=namespace)
    
    # initiate agent
    await strands_agent.initiate_agent(
        system_prompt=None, 
        strands_tools=strands_agent.strands_tools, 
        mcp_servers=mcp_servers, 
        historyMode='Disable'
    )
    logger.info(f"tool_list: {tool_list}")    

    # run agent    
    with strands_agent.mcp_manager.get_active_clients(mcp_servers) as _:
        agent_stream = strands_agent.agent.stream_async(query)

        final_result = current = ""
        async for event in agent_stream:
            text = ""            
            if "data" in event:
                text = event["data"]
                logger.info(f"[data] {text}")
                current += text
                update_streaming_result(containers, current)

            elif "result" in event:
                final = event["result"]                
                message = final.message
                if message:
                    content = message.get("content", [])
                    result = content[0].get("text", "")
                    logger.info(f"[result] {result}")
                    final_result = result

            elif "current_tool_use" in event:
                current_tool_use = event["current_tool_use"]
                logger.info(f"current_tool_use: {current_tool_use}")
                name = current_tool_use.get("name", "")
                input = current_tool_use.get("input", "")
                toolUseId = current_tool_use.get("toolUseId", "")

                text = f"name: {name}, input: {input}"
                logger.info(f"[current_tool_use] {text}")

                if toolUseId not in tool_info_list: # new tool info
                    index += 1
                    current = ""
                    logger.info(f"new tool info: {toolUseId} -> {index}")
                    tool_info_list[toolUseId] = index
                    add_notification(containers, f"Tool: {name}, Input: {input}")
                else: # overwrite tool info if already exists
                    logger.info(f"overwrite tool info: {toolUseId} -> {tool_info_list[toolUseId]}")
                    containers['notification'][tool_info_list[toolUseId]].info(f"Tool: {name}, Input: {input}")

            elif "message" in event:
                message = event["message"]
                logger.info(f"[message] {message}")

                if "content" in message:
                    content = message["content"]
                    logger.info(f"tool content: {content}")
                    if "toolResult" in content[0]:
                        toolResult = content[0]["toolResult"]
                        toolUseId = toolResult["toolUseId"]
                        toolContent = toolResult["content"]
                        toolResult = toolContent[0].get("text", "")
                        logger.info(f"[toolResult] {toolResult}, [toolUseId] {toolUseId}")
                        add_notification(containers, f"Tool Result: {str(toolResult)}")
            
            elif "contentBlockDelta" or "contentBlockStop" or "messageStop" or "metadata" in event:
                pass

            else:
                logger.info(f"event: {event}")

        image_url = []
        return final_result, image_url
    
    # save event to memory
    # if memory_id is not None and result:
    #     agentcore_memory.save_conversation_to_memory(memory_id, actor_id, session_id, query, result) 



async def run_langgraph_agent(query, mcp_servers, history_mode, containers):
    # initate memory variables    
    # memory_id, actor_id, session_id, namespace = agentcore_memory.load_memory_variables(user_id)
    # logger.info(f"memory_id: {memory_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")

    # if memory_id is None:
    #     # retrieve memory id
    #     memory_id = agentcore_memory.retrieve_memory_id()
    #     logger.info(f"memory_id: {memory_id}")        
        
    #     # create memory if not exists
    #     if memory_id is None:
    #         logger.info(f"Memory will be created...")
    #         memory_id = agentcore_memory.create_memory(namespace)
    #         logger.info(f"Memory was created... {memory_id}")
        
    #     # create strategy if not exists
    #     agentcore_memory.create_strategy_if_not_exists(memory_id=memory_id, namespace=namespace, strategy_name=user_id)

    #     # save memory variables
    #     agentcore_memory.update_memory_variables(
    #         user_id=user_id, 
    #         memory_id=memory_id, 
    #         actor_id=actor_id, 
    #         session_id=session_id, 
    #         namespace=namespace)

    mcp_json = mcp_config.load_selected_config(mcp_servers)
    logger.info(f"mcp_json: {mcp_json}")

    server_params = langgraph_agent.load_multiple_mcp_server_parameters(mcp_json)
    logger.info(f"server_params: {server_params}")    

    client = MultiServerMCPClient(server_params)
    tools = await client.get_tools()
    
    tool_list = [tool.name for tool in tools]
    logger.info(f"tool_list: {tool_list}")

    app = langgraph_agent.buildChatAgentWithHistory(tools)
    config = {
        "recursion_limit": 50,
        "configurable": {"thread_id": user_id},
        "tools": tools,
        "system_prompt": None
    }
    
    inputs = {
        "messages": [HumanMessage(content=query)]
    }
            
    result = ""
    tool_used = False  # Track if tool was used
    async for output in app.astream(inputs, config, stream_mode="messages"):
        logger.info(f"output: {output}")

        # Handle tuple output (message, metadata)
        if isinstance(output, tuple) and len(output) > 0 and isinstance(output[0], AIMessageChunk):
            message = output[0]            
            if isinstance(message.content, list):
                for content_item in message.content:
                    if isinstance(content_item, dict):
                        if content_item.get('type') == 'text':
                            text_content = content_item.get('text', '')
                            logger.info(f"text_content: {text_content}")
                            
                            # If tool was used, start fresh result
                            if tool_used:
                                result = text_content
                                tool_used = False
                            else:
                                result += text_content
                                
                            logger.info(f"result: {result}")
                    
                            update_streaming_result(containers, result)

                        elif content_item.get('type') == 'tool_use':
                            tool_name = content_item.get('name', '')
                            toolUseId = content_item.get('id', '')
                            input = content_item.get('input', {})   
                            logger.info(f"tool_name: {tool_name}, input: {input}, toolUseId: {toolUseId}")

                            if tool_name:
                                add_notification(containers, f"Tool: {tool_name}, Input: {input}")
        
        elif isinstance(output, tuple) and len(output) > 0 and isinstance(output[0], ToolMessage):
            message = output[0]
            logger.info(f"ToolMessage: {message.name}, {message.content}")
            toolResult = message.content
            toolUseId = message.tool_call_id
            logger.info(f"toolResult: {toolResult}, toolUseId: {toolUseId}")
            add_notification(containers, f"Tool Result: {toolResult}")
            tool_used = True
    
    if not result:
        result = "답변을 찾지 못하였습니다."        
    logger.info(f"result: {result}")

    image_url = []
    return result, image_url
