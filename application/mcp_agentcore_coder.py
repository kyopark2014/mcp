import logging
import sys
import boto3
import time
import os
import re
import uuid
import base64
from io import BytesIO
from urllib import parse
import json

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("agentcore-coder")

aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

client = boto3.client(
    "bedrock-agentcore", 
    region_name=aws_region,
    endpoint_url=f"https://bedrock-agentcore.{aws_region}.amazonaws.com"
)

sessionId = None
def create_code_interpreter_sessionId():
    session_id = None
    response = client.list_code_interpreter_sessions(
        codeInterpreterIdentifier='aws.codeinterpreter.v1',
        maxResults=5,
        status='READY'
    )
    items = response['items']

    if items is not None:
        for item in items:
            session_id = item['sessionId']
            break
    
    if session_id is None:  # still no sessionId
        logger.info("No ready sessions found")
        response = client.start_code_interpreter_session(
            codeInterpreterIdentifier='aws.codeinterpreter.v1',
            name="agentcore-code-session",
            sessionTimeoutSeconds=900
        )
        logger.info(f"response of start_code_interpreter_session: {response}")
        session_id = response['sessionId']

    return session_id

def get_code_interpreter_sessionId():
    global sessionId
    if sessionId is None:
        sessionId = create_code_interpreter_sessionId()
        logger.info(f"sessionId: {sessionId}")
    else:
        logger.info(f"sessionId: {sessionId}")
        try:
            response = client.get_code_interpreter_session(
                codeInterpreterIdentifier='aws.codeinterpreter.v1',
                sessionId=sessionId
            )
            logger.info(f"response of get_code_interpreter_session: {response}")        

            status = response['status']
            logger.info(f"status: {status}")
            if status != 'READY':
                logger.info(f"sessionId: {sessionId} is not ready")
                sessionId = create_code_interpreter_sessionId()
                time.sleep(5)
        except Exception as e:
            logger.info(f"error of get_code_interpreter_session: {e}")
            sessionId = create_code_interpreter_sessionId()

    return sessionId

def agentcore_coder(code: str):
    """
    Use this to execute python code and do math. 
    If you want to see the output of a value, you should print it out with `print(...)`. This is visible to the user.
    code: the Python code was written in English
    """
    
    # get the sessionId
    sessionId = get_code_interpreter_sessionId()
    
    execute_response = client.invoke_code_interpreter(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=sessionId,
        name="executeCode",
        arguments={
            "language": "python",
            "code": code
        }
    )
    logger.info(f"execute_response: {execute_response}")

    # Extract and print the text output from the stream
    result_text = ""
    for event in execute_response['stream']:
        if 'result' in event:
            result = event['result']
            if 'content' in result:
                for content_item in result['content']:
                    if content_item['type'] == 'text':
                        result_text = content_item['text']
                        logger.info(f"result: {result_text}")

    # stop the session
    # client.stop_code_interpreter_session(
    #     codeInterpreterIdentifier="aws.codeinterpreter.v1",
    #     sessionId=sessionId
    # )
    return result_text

def get_contents_type(file_name):
    if file_name.lower().endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    elif file_name.lower().endswith((".pdf")):
        content_type = "application/pdf"
    elif file_name.lower().endswith((".txt")):
        content_type = "text/plain"
    elif file_name.lower().endswith((".csv")):
        content_type = "text/csv"
    elif file_name.lower().endswith((".ppt", ".pptx")):
        content_type = "application/vnd.ms-powerpoint"
    elif file_name.lower().endswith((".doc", ".docx")):
        content_type = "application/msword"
    elif file_name.lower().endswith((".xls")):
        content_type = "application/vnd.ms-excel"
    elif file_name.lower().endswith((".py")):
        content_type = "text/x-python"
    elif file_name.lower().endswith((".js")):
        content_type = "application/javascript"
    elif file_name.lower().endswith((".md")):
        content_type = "text/markdown"
    elif file_name.lower().endswith((".png")):
        content_type = "image/png"
    else:
        content_type = "no info"    
    return content_type


def load_config():
    config = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

bedrock_region = config['region']
projectName = config['projectName']
s3_bucket = config['s3_bucket']
path = config["sharing_url"] if "sharing_url" in config else None

s3_prefix = 'docs'
s3_image_prefix = 'images'
model_name = "Claude 3.5 Sonnet"

def upload_to_s3(file_bytes, file_name):
    """
    Upload a file to S3 and return the URL
    """
    try:
        s3_client = boto3.client(
            service_name='s3',
            region_name=bedrock_region,
        )

        content_type = get_contents_type(file_name)       
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

def generate_short_uuid(length=8):
    full_uuid = uuid.uuid4().hex
    return full_uuid[:length]

def agentcore_drawer(code: str):
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

    # get the sessionId
    sessionId = get_code_interpreter_sessionId()
    
    execute_response = client.invoke_code_interpreter(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=sessionId,
        name="executeCode",
        arguments={
            "language": "python",
            "code": code
        }
    )
    logger.info(f"execute_response: {execute_response}")

    # Extract and print the text output from the stream
    result_text = ""
    for event in execute_response['stream']:
        if 'result' in event:
            result = event['result']
            if 'content' in result:
                for content_item in result['content']:
                    if content_item['type'] == 'text':
                        result_text = content_item['text']
                        logger.info(f"result: {result_text}")
    
    base64Img = result_text
            
    if base64Img:
        byteImage = BytesIO(base64.b64decode(base64Img))

        image_name = generate_short_uuid()+'.png'
        url = upload_to_s3(byteImage, image_name)
        logger.info(f"url: {url}")

        file_name = url[url.rfind('/')+1:]
        logger.info(f"file_name: {file_name}")

        image_url = path+'/'+s3_image_prefix+'/'+parse.quote(file_name)
        logger.info(f"image_url: {image_url}")

    return {
        "path": image_url
    }
