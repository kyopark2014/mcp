import traceback
import boto3
import os
import json
import re
import uuid
import base64
import info 
import utils
import langgraph_agent
import mcp_config
import csv
import PyPDF2
from langchain_core.documents import Document
from urllib import parse

from io import BytesIO
from PIL import Image
from langchain_aws import ChatBedrock
from botocore.config import Config
from botocore.exceptions import ClientError
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, AIMessageChunk
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

import logging
import sys

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("chat")

workingDir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(workingDir, "config.json")

# Simple memory class to replace ConversationBufferWindowMemory
class SimpleMemory:
    def __init__(self, k=5):
        self.k = k
        self.chat_memory = SimpleChatMemory()
    
    def load_memory_variables(self, inputs):
        return {"chat_history": self.chat_memory.messages[-self.k:] if len(self.chat_memory.messages) > self.k else self.chat_memory.messages}

class SimpleChatMemory:
    def __init__(self):
        self.messages = []
    
    def add_user_message(self, message):
        self.messages.append(HumanMessage(content=message))
    
    def add_ai_message(self, message):
        self.messages.append(AIMessage(content=message))
    
    def clear(self):
        self.messages = []

reasoning_mode = 'Disable'
debug_messages = []  # List to store debug messages

config = utils.load_config()
print(f"config: {config}")

projectName = config.get("projectName", "es")
bedrock_region = config.get("region", "ap-northeast-2")

accountId = config.get("accountId")
knowledge_base_name = config.get("knowledge_base_name")
s3_bucket = config.get("s3_bucket")
s3_prefix = "docs"
s3_image_prefix = "images"

path = config.get('sharing_url', '')
doc_prefix = "docs/"

MSG_LENGTH = 100    

model_name = "Claude 4 Sonnet"
model_type = "claude"
models = info.get_model_info(model_name)
number_of_models = len(models)
model_id = models[0]["model_id"]
debug_mode = "Enable"
skill_mode = "Disable"

aws_access_key = config.get('aws', {}).get('access_key_id')
aws_secret_key = config.get('aws', {}).get('secret_access_key')
aws_session_token = config.get('aws', {}).get('session_token')

reasoning_mode = 'Disable'
user_id = "mcp"

def update(modelName, debugMode, reasoningMode, skillMode):    
    global model_name, model_id, model_type, debug_mode, reasoning_mode
    global models, user_id, skill_mode

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

    if skill_mode != skillMode:
        skill_mode = skillMode
        logger.info(f"skill_mode: {skill_mode}")

    # logger.info(f"mcp.env updated: {mcp_env}")

map_chain = dict() 
checkpointers = dict() 
memorystores = dict() 

memory_chain = None
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
        memory_chain = SimpleMemory(k=5)
        map_chain[user_id] = memory_chain

        checkpointer = MemorySaver()
        memorystore = InMemoryStore()

        checkpointers[user_id] = checkpointer
        memorystores[user_id] = memorystore

def clear_chat_history():
    global memory_chain
    # Initialize memory_chain if it doesn't exist
    if memory_chain is None:
        initiate()
    
    if memory_chain and hasattr(memory_chain, 'chat_memory'):
        memory_chain.chat_memory.clear()
    else:
        memory_chain = SimpleMemory(k=5)
    map_chain[user_id] = memory_chain

def save_chat_history(text, msg):
    global memory_chain
    # Initialize memory_chain if it doesn't exist
    if memory_chain is None:
        initiate()
    
    if memory_chain and hasattr(memory_chain, 'chat_memory'):
        memory_chain.chat_memory.add_user_message(text)
        if len(msg) > MSG_LENGTH:
            memory_chain.chat_memory.add_ai_message(msg[:MSG_LENGTH])                          
        else:
            memory_chain.chat_memory.add_ai_message(msg) 

selected_chat = 0
def get_max_output_tokens(model_id: str = "") -> int:
    """Return the max output tokens based on the model ID."""
    if "claude-4" in model_id or "claude-sonnet-4" in model_id or "claude-opus-4" in model_id or "claude-haiku-4" in model_id:
        return 16384
    return 8192

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
        maxOutputTokens = get_max_output_tokens(modelId)
    else:
        maxOutputTokens = 5120  # 5k
    number_of_models = len(models)

    logger.info(f"LLM: {selected_chat}, bedrock_region: {bedrock_region}, modelId: {modelId}, model_type: {model_type}")

    if profile['model_type'] == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif profile['model_type'] == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 
    elif profile['model_type'] == 'openai':
        STOP_SEQUENCE = "" 
                          
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

    if profile['model_type'] != 'openai' and extended_thinking=='Enable':
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
    elif profile['model_type'] != 'openai' and extended_thinking=='Disable':
        parameters = {
            "max_tokens":maxOutputTokens,     
            "temperature":0.1,
            "top_k":250,
            "stop_sequences": [STOP_SEQUENCE]
        }
    elif profile['model_type'] == 'openai':
        parameters = {
            "max_tokens":maxOutputTokens,     
            "temperature":0.1,
            "top_k":250,
        }

    chat = ChatBedrock(   # new chat model
        model_id=modelId,
        client=boto3_bedrock, 
        model_kwargs=parameters,
        region_name=bedrock_region
    )
    
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
    
reference_docs = []

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

def upload_to_s3(file_bytes, file_name):
    """
    Upload a file to S3 and return the URL
    """

    try:
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
    elif profile['model_type'] == 'openai':
        STOP_SEQUENCE = "" 
                          
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

    if profile['model_type'] != 'openai':
        parameters = {
            "max_tokens":maxOutputTokens,     
            "temperature":0.1,
            "top_k":250,
            "stop_sequences": [STOP_SEQUENCE]
        }
    else:
        parameters = {
            "max_tokens":maxOutputTokens,     
            "temperature":0.1,
            "top_k":250
        }

    chat = ChatBedrock(   # new chat model
        model_id=modelId,
        client=boto3_bedrock, 
        model_kwargs=parameters,
    )        
    
    return chat

def show_extended_thinking(st, result):
    # logger.info(f"result: {result}")
    if "thinking" in result.response_metadata:
        if "text" in result.response_metadata["thinking"]:
            thinking = result.response_metadata["thinking"]["text"]
            st.info(thinking)

####################### LangChain #######################
# General Conversation
#########################################################
def general_conversation(query):
    global memory_chain
    initiate()  # Initialize memory_chain
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
                
    if memory_chain and hasattr(memory_chain, 'load_memory_variables'):
        history = memory_chain.load_memory_variables({})["chat_history"]
        # Ensure history starts with a HumanMessage (Bedrock Converse API requirement)
        if history and isinstance(history[0], AIMessage):
            history = history[1:]
    else:
        history = []

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

def summary_image(img_base64, instruction):      
    llm = get_chat(extended_thinking=reasoning_mode)

    if instruction:
        logger.info(f"instruction: {instruction}")
        query = f"{instruction}. <result> tag를 붙여주세요. 한국어로 답변하세요."
        
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

####################### LangChain #######################
# Image Summarization
#########################################################
def summarize_image(image_content, prompt, st):
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
            
    # if len(extracted_text) > 10:
    #     contents = f"## 이미지 분석\n\n{image_summary}\n\n## 추출된 텍스트\n\n{extracted_text}"
    # else:
    #     contents = f"## 이미지 분석\n\n{image_summary}"
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

if aws_access_key and aws_secret_key:
    bedrock_agent_runtime_client = boto3.client(
        "bedrock-agent-runtime",
        region_name=bedrock_region,
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        aws_session_token=aws_session_token,
    )
else:
    bedrock_agent_runtime_client = boto3.client(
        "bedrock-agent-runtime",
        region_name=bedrock_region
    )
knowledge_base_id = config.get('knowledge_base_id')
number_of_results = 4

def retrieve(query):
    global knowledge_base_id
    
    try:
        response = bedrock_agent_runtime_client.retrieve(
            retrievalQuery={"text": query},
            knowledgeBaseId=knowledge_base_id,
                retrievalConfiguration={
                    "vectorSearchConfiguration": {"numberOfResults": number_of_results},
                },
            )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        
        # Update knowledge_base_id only when ResourceNotFoundException occurs
        if error_code == "ResourceNotFoundException":
            logger.warning(f"ResourceNotFoundException occurred: {e}")
            logger.info("Attempting to update knowledge_base_id...")
            
            bedrock_region_local = config.get('region', 'us-west-2')
            projectName_local = config.get('projectName')

            # Create bedrock-agent client with same credentials as bedrock-agent-runtime client
            if aws_access_key and aws_secret_key:
                bedrock_agent_client = boto3.client(
                    "bedrock-agent",
                    region_name=bedrock_region_local,
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    aws_session_token=aws_session_token,
                )
            else:
                bedrock_agent_client = boto3.client("bedrock-agent", region_name=bedrock_region_local)
            knowledge_base_list = bedrock_agent_client.list_knowledge_bases()
            
            updated = False
            for knowledge_base in knowledge_base_list.get("knowledgeBaseSummaries", []):
                if knowledge_base["name"] == projectName_local:
                    new_knowledge_base_id = knowledge_base["knowledgeBaseId"]
                    knowledge_base_id = new_knowledge_base_id

                    config['knowledge_base_id'] = new_knowledge_base_id
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(config, f, ensure_ascii=False, indent=4)
                    
                    logger.info(f"Updated knowledge_base_id to: {new_knowledge_base_id}")
                    updated = True
                    break
            
            if updated:
                # Retry after updating knowledge_base_id
                try:
                    response = bedrock_agent_runtime_client.retrieve(
                        retrievalQuery={"text": query},
                        knowledgeBaseId=knowledge_base_id,
                        retrievalConfiguration={
                            "vectorSearchConfiguration": {"numberOfResults": number_of_results},
                        },
                    )
                    logger.info("Retry successful after updating knowledge_base_id")
                except Exception as retry_error:
                    logger.error(f"Retry failed after updating knowledge_base_id: {retry_error}")
                    raise
            else:
                logger.error(f"Could not find knowledge base with name: {projectName_local}")
                raise
        else:
            # Re-raise other errors that are not ResourceNotFoundException
            logger.error(f"Error retrieving: {e}")
            raise
    except Exception as e:
        # Re-raise other exceptions that are not ClientError
        logger.error(f"Unexpected error retrieving: {e}")
        raise
    
    # logger.info(f"response: {response}")
    retrieval_results = response.get("retrievalResults", [])
    # logger.info(f"retrieval_results: {retrieval_results}")

    json_docs = []
    for result in retrieval_results:
        text = url = name = None
        if "content" in result:
            content = result["content"]
            if "text" in content:
                text = content["text"]

        if "location" in result:
            location = result["location"]
            if "s3Location" in location:
                uri = location["s3Location"]["uri"] if location["s3Location"]["uri"] is not None else ""
                
                name = uri.split("/")[-1]
                encoded_name = parse.quote(name)                
                url = f"{path}/{doc_prefix}{encoded_name}"
                
            elif "webLocation" in location:
                url = location["webLocation"]["url"] if location["webLocation"]["url"] is not None else ""
                name = "WEB"

        json_docs.append({
            "contents": text,              
            "reference": {
                "url": url,                   
                "title": name,
                "from": "RAG"
            }
        })
    logger.info(f"json_docs: {json_docs}")

    return json.dumps(json_docs, ensure_ascii=False)
 
def run_rag_with_knowledge_base(query, st):
    global reference_docs, contentList
    reference_docs = []
    contentList = []

    # retrieve
    if debug_mode == "Enable":
        st.info(f"RAG 검색을 수행합니다. 검색어: {query}")  

    json_docs = retrieve(query)    
    logger.info(f"json_docs: {json_docs}")

    relevant_docs = json.loads(json_docs)

    relevant_context = ""
    for doc in relevant_docs:
        relevant_context += f"{doc['contents']}\n\n"

    # change format to document
    st.info(f"{len(relevant_docs)}개의 관련된 문서를 얻었습니다.")

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
    
    if relevant_docs:
        ref = "\n\n### Reference\n"
        for i, doc in enumerate(relevant_docs):
            page_content = doc["contents"][:100].replace("\n", "")
            ref += f"{i+1}. [{doc["reference"]['title']}]({doc["reference"]['url']}), {page_content}...\n"    
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

def update_streaming_result(containers, message, type):
    global streaming_index
    streaming_index = index

    if containers is not None:
        if type == "markdown":
            containers['notification'][streaming_index].markdown(message)
        elif type == "info":
            containers['notification'][streaming_index].info(message)
def update_tool_notification(containers, tool_index, message):
    if containers is not None:
        containers['notification'][tool_index].info(message)

tool_info_list = dict()
tool_input_list = dict()
tool_name_list = dict()

sharing_url = config["sharing_url"] if "sharing_url" in config else None
s3_prefix = "docs"
capture_prefix = "captures"

def get_tool_info(tool_name, tool_content):
    tool_references = []    
    urls = []
    content = ""
    
    # OpenSearch
    if tool_name == "SearchIndexTool": 
        if ":" in tool_content:
            extracted_json_data = tool_content.split(":", 1)[1].strip()
            try:
                json_data = json.loads(extracted_json_data)
                # logger.info(f"extracted_json_data: {extracted_json_data[:200]}")
            except json.JSONDecodeError:
                logger.info("JSON parsing error")
                json_data = {}
        else:
            json_data = {}
        
        if "hits" in json_data:
            hits = json_data["hits"]["hits"]
            if hits:
                logger.info(f"hits[0]: {hits[0]}")

            for hit in hits:
                text = hit["_source"]["text"]
                metadata = hit["_source"]["metadata"]
                
                content += f"{text}\n\n"

                filename = metadata["name"].split("/")[-1]
                # logger.info(f"filename: {filename}")
                
                content_part = text.replace("\n", "")
                tool_references.append({
                    "url": metadata["url"], 
                    "title": filename,
                    "content": content_part[:100] + "..." if len(content_part) > 100 else content_part
                })
                
        logger.info(f"content: {content}")
        
    # aws document
    elif tool_name == "search_documentation":
        try:
            # tool_content가 리스트인 경우 처리 (예: [{'type': 'text', 'text': '...'}])
            if isinstance(tool_content, list):
                # 리스트의 첫 번째 항목에서 text 필드 추출
                if len(tool_content) > 0 and isinstance(tool_content[0], dict) and 'text' in tool_content[0]:
                    tool_content = tool_content[0]['text']
                else:
                    logger.info(f"Unexpected list format: {tool_content}")
                    return content, urls, tool_references
            
            # tool_content가 문자열인 경우 JSON 파싱
            if isinstance(tool_content, str):
                json_data = json.loads(tool_content)
            elif isinstance(tool_content, dict):
                json_data = tool_content
            else:
                logger.info(f"Unexpected tool_content type: {type(tool_content)}")
                return content, urls, tool_references
            
            # search_results 배열에서 결과 추출
            search_results = json_data.get('search_results', [])
            if not search_results:
                # search_results가 없으면 json_data 자체가 배열일 수 있음
                if isinstance(json_data, list):
                    search_results = json_data
                else:
                    logger.info(f"No search_results found in JSON data")
                    return content, urls, tool_references
            
            for item in search_results:
                logger.info(f"item: {item}")
                
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        logger.info(f"Failed to parse item as JSON: {item}")
                        continue
                
                if isinstance(item, dict) and 'url' in item and 'title' in item:
                    url = item['url']
                    title = item['title']
                    content_text = item.get('context', '')[:100] + "..." if len(item.get('context', '')) > 100 else item.get('context', '')
                    tool_references.append({
                        "url": url,
                        "title": title,
                        "content": content_text
                    })
                else:
                    logger.info(f"Invalid item format: {item}")
                    
        except json.JSONDecodeError as e:
            logger.info(f"JSON parsing error: {e}, tool_content: {tool_content}")
            pass
        except Exception as e:
            logger.info(f"Unexpected error in search_documentation: {e}, tool_content type: {type(tool_content)}")
            pass

        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")
            
    # aws-knowledge
    elif tool_name == "aws___read_documentation":
        logger.info(f"#### {tool_name} ####")
        if isinstance(tool_content, dict):
            json_data = tool_content
        elif isinstance(tool_content, list):
            json_data = tool_content
        else:
            json_data = json.loads(tool_content)
        
        logger.info(f"json_data: {json_data}")
        payload = json_data["response"]["payload"]
        if "content" in payload:
            payload_content = payload["content"]
            if "result" in payload_content:
                result = payload_content["result"]
                logger.info(f"result: {result}")
                if isinstance(result, str) and "AWS Documentation from" in result:
                    logger.info(f"Processing AWS Documentation format: {result}")
                    try:
                        # Extract URL from "AWS Documentation from https://..."
                        url_start = result.find("https://")
                        if url_start != -1:
                            # Find the colon after the URL (not inside the URL)
                            url_end = result.find(":", url_start)
                            if url_end != -1:
                                # Check if the colon is part of the URL or the separator
                                url_part = result[url_start:url_end]
                                # If the colon is immediately after the URL, use it as separator
                                if result[url_end:url_end+2] == ":\n":
                                    url = url_part
                                    content_start = url_end + 2  # Skip the colon and newline
                                else:
                                    # Try to find the actual URL end by looking for space or newline
                                    space_pos = result.find(" ", url_start)
                                    newline_pos = result.find("\n", url_start)
                                    if space_pos != -1 and newline_pos != -1:
                                        url_end = min(space_pos, newline_pos)
                                    elif space_pos != -1:
                                        url_end = space_pos
                                    elif newline_pos != -1:
                                        url_end = newline_pos
                                    else:
                                        url_end = len(result)
                                    
                                    url = result[url_start:url_end]
                                    content_start = url_end + 1
                                
                                # Remove trailing colon from URL if present
                                if url.endswith(":"):
                                    url = url[:-1]
                                
                                # Extract content after the URL
                                if content_start < len(result):
                                    content_text = result[content_start:].strip()
                                    # Truncate content for display
                                    display_content = content_text[:100] + "..." if len(content_text) > 100 else content_text
                                    display_content = display_content.replace("\n", "")
                                    
                                    tool_references.append({
                                        "url": url,
                                        "title": "AWS Documentation",
                                        "content": display_content
                                    })
                                    content += content_text + "\n\n"
                                    logger.info(f"Extracted URL: {url}")
                                    logger.info(f"Extracted content length: {len(content_text)}")
                    except Exception as e:
                        logger.error(f"Error parsing AWS Documentation format: {e}")
        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")

    elif tool_name in ("memory_search", "memory_get"):
        pass

    else:        
        try:
            if isinstance(tool_content, dict):
                json_data = tool_content
            elif isinstance(tool_content, list):
                json_data = tool_content
            else:
                json_data = json.loads(tool_content)
            
            logger.info(f"json_data: {json_data}")
            if isinstance(json_data, dict) and "path" in json_data:  # path
                path = json_data["path"]
                if isinstance(path, list):
                    for url in path:
                        urls.append(url)
                else:
                    urls.append(path)
            elif isinstance(json_data, list):  # Parse JSON from text field when json_data is a list
                for item in json_data:
                    if isinstance(item, dict) and "text" in item:
                        try:
                            text_json = json.loads(item["text"])
                            if isinstance(text_json, dict) and "path" in text_json:
                                path = text_json["path"]
                                if isinstance(path, list):
                                    for url in path:
                                        urls.append(url)
                                else:
                                    urls.append(path)
                        except (json.JSONDecodeError, TypeError):
                            pass            


            if isinstance(json_data, dict):
                for item in json_data:
                    logger.info(f"item: {item}")
                    if "reference" in item and "contents" in item:
                        url = item["reference"]["url"]
                        title = item["reference"]["title"]
                        content_text = item["contents"][:100] + "..." if len(item["contents"]) > 100 else item["contents"]
                        tool_references.append({
                            "url": url,
                            "title": title,
                            "content": content_text
                        })
            elif isinstance(json_data, list):
                logger.info(f"json_data is a list: {json_data}")
                for item in json_data:
                    if isinstance(item, dict) and "text" in item:
                        try:
                            # text 필드 안의 JSON 문자열 파싱
                            text_json = json.loads(item["text"])
                            if isinstance(text_json, list):
                                # 파싱된 JSON이 리스트인 경우
                                for ref_item in text_json:
                                    if isinstance(ref_item, dict) and "reference" in ref_item and "contents" in ref_item:
                                        url = ref_item["reference"]["url"]
                                        title = ref_item["reference"]["title"]
                                        content_text = ref_item["contents"][:100] + "..." if len(ref_item["contents"]) > 100 else ref_item["contents"]
                                        tool_references.append({
                                            "url": url,
                                            "title": title,
                                            "content": content_text
                                        })
                            elif isinstance(text_json, dict) and "reference" in text_json and "contents" in text_json:
                                # 파싱된 JSON이 딕셔너리인 경우
                                url = text_json["reference"]["url"]
                                title = text_json["reference"]["title"]
                                content_text = text_json["contents"][:100] + "..." if len(text_json["contents"]) > 100 else text_json["contents"]
                                tool_references.append({
                                    "url": url,
                                    "title": title,
                                    "content": content_text
                                })
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(f"Failed to parse text JSON: {e}")
                            pass
                    elif isinstance(item, dict) and "reference" in item and "contents" in item:
                        # 리스트 항목이 직접 reference를 가지고 있는 경우
                        url = item["reference"]["url"]
                        title = item["reference"]["title"]
                        content_text = item["contents"][:100] + "..." if len(item["contents"]) > 100 else item["contents"]
                        tool_references.append({
                            "url": url,
                            "title": title,
                            "content": content_text
                        })
                
            logger.info(f"tool_references: {tool_references}")

        except json.JSONDecodeError:
            pass

    return content, urls, tool_references

async def run_langgraph_agent(query, mcp_servers, history_mode, containers):
    global index, streaming_index
    index = 0

    image_url = []
    references = []

    mcp_json = mcp_config.load_selected_config(mcp_servers)
    logger.info(f"mcp_json: {mcp_json}")

    server_params = langgraph_agent.load_multiple_mcp_server_parameters(mcp_json)
    logger.info(f"server_params: {server_params}")    

    try:
        client = MultiServerMCPClient(server_params)
        logger.info(f"MCP client created successfully")
        
        tools = await client.get_tools()
        logger.info(f"get_tools() returned: {tools}")

        builtin_tools = langgraph_agent.get_builtin_tools()
        logger.info(f"builtin_tools: {builtin_tools}")

        if skill_mode == "Enable":        
            tool_names = {tool.name for tool in tools}
            for bt in builtin_tools:
                if bt.name not in tool_names:
                    tools.append(bt)
                else:
                    logger.info(f"builtin_tool {bt.name} already in tools")
            
        if tools is None:
            logger.error("tools is None - MCP client failed to get tools")
            tools = []
        
        tool_list = [tool.name for tool in tools] if tools else []
        logger.info(f"tool_list: {tool_list}")
        
    except Exception as e:
        logger.error(f"Error creating MCP client or getting tools: {e}")                        
        tools = []
        tool_list = []        

    # If no tools available, use general conversation
    if not tools:
        logger.warning("No tools available, using general conversation mode")
        result = "MCP 설정을 확인하세요."
        if containers is not None:
            containers['notification'][0].markdown(result)
        return result, image_url
    
    if history_mode == "Enable":
        app = langgraph_agent.buildChatAgentWithHistory(tools)
        config = {
            "recursion_limit": 50,
            "configurable": {"thread_id": user_id},
            "tools": tools,
            "system_prompt": None
        }
    else:
        app = langgraph_agent.buildChatAgent(tools)
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
    tool_name = toolUseId = ""
    async for stream in app.astream(inputs, config, stream_mode="messages"):
        if isinstance(stream[0], AIMessageChunk):
            message = stream[0]    
            input = {}        
            if isinstance(message.content, list):
                for content_item in message.content:
                    if isinstance(content_item, dict):
                        if content_item.get('type') == 'text':
                            text_content = content_item.get('text', '')
                            # logger.info(f"text_content: {text_content}")
                            
                            # If tool was used, start fresh result
                            if tool_used:
                                result = text_content
                                tool_used = False
                            else:
                                result += text_content
                                
                            # logger.info(f"result: {result}")                
                            update_streaming_result(containers, result, "markdown")

                        elif content_item.get('type') == 'tool_use':
                            # logger.info(f"content_item: {content_item}")      
                            if 'id' in content_item and 'name' in content_item:
                                toolUseId = content_item.get('id', '')
                                tool_name = content_item.get('name', '')
                                logger.info(f"tool_name: {tool_name}, toolUseId: {toolUseId}")
                                streaming_index = index
                                index += 1
                                                                    
                            if 'partial_json' in content_item:
                                partial_json = content_item.get('partial_json', '')
                                #logger.info(f"partial_json: {partial_json}")
                                
                                if toolUseId not in tool_input_list:
                                    tool_input_list[toolUseId] = ""                                
                                tool_input_list[toolUseId] += partial_json
                                input = tool_input_list[toolUseId]
                                # logger.info(f"input: {input}")

                                # logger.info(f"tool_name: {tool_name}, input: {input}, toolUseId: {toolUseId}")
                                update_streaming_result(containers, f"Tool: {tool_name}, Input: {input}", "info")
                        
        elif isinstance(stream[0], ToolMessage):
            message = stream[0]
            logger.info(f"ToolMessage: {message.name}, {message.content}")
            tool_name = message.name
            toolResult = message.content
            toolUseId = message.tool_call_id
            logger.info(f"toolResult: {toolResult}, toolUseId: {toolUseId}")
            add_notification(containers, f"Tool Result: {toolResult}")
            tool_used = True
            
            content, urls, refs = get_tool_info(tool_name, toolResult)
            if refs:
                for r in refs:
                    references.append(r)
                logger.info(f"refs: {refs}")
            if urls:
                for url in urls:
                    image_url.append(url)
                logger.info(f"urls: {urls}")

            if content:
                logger.info(f"content: {content}")        
    
    if not result:
        result = "답변을 찾지 못하였습니다."        
    logger.info(f"result: {result}")

    if references:
        ref = "\n\n### Reference\n"
        for i, reference in enumerate(references):
            page_content = reference['content'][:100].replace("\n", "")
            ref += f"{i+1}. [{reference['title']}]({reference['url']}), {page_content}...\n"    
        result += ref
    
    if containers is not None:
        containers['notification'][index].markdown(result)
    
    return result, image_url
