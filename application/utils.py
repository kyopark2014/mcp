import logging
import sys
import json
import traceback
import boto3

from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-basic")

def load_config():
    config = None
    
    with open("application/config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

bedrock_region = config['region']
projectName = config['projectName']

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

def load_mcp_env():
    with open("application/mcp.env", "r", encoding="utf-8") as f:
        mcp_env = json.load(f)
    return mcp_env

def save_mcp_env(mcp_env):
    with open("application/mcp.env", "w", encoding="utf-8") as f:
        json.dump(mcp_env, f)

# api key to get weather information in agent
secretsmanager = boto3.client(
    service_name='secretsmanager',
    region_name=bedrock_region
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

# api key to use Tavily Search
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

        else:
            logger.info(f"tavily_key is required.")
except Exception as e: 
    logger.info(f"Tavily credential is required: {e}")
    raise e

# api key to use firecrawl Search
firecrawl_key = ""
try:
    get_firecrawl_secret = secretsmanager.get_secret_value(
        SecretId=f"firecrawlapikey-{projectName}"
    )
    secret = json.loads(get_firecrawl_secret['SecretString'])

    if "firecrawl_api_key" in secret:
        firecrawl_key = secret['firecrawl_api_key']
        # print('firecrawl_api_key: ', firecrawl_key)
except Exception as e: 
    logger.info(f"Firecrawl credential is required: {e}")
    raise e

# api key to use perplexity Search
perplexity_key = ""
try:
    get_perplexity_api_secret = secretsmanager.get_secret_value(
        SecretId=f"perplexityapikey-{projectName}"
    )
    #print('get_perplexity_api_secret: ', get_perplexity_api_secret)
    secret = json.loads(get_perplexity_api_secret['SecretString'])
    #print('secret: ', secret)

    if "perplexity_api_key" in secret:
        perplexity_key = secret['perplexity_api_key']
        #print('perplexity_api_key: ', perplexity_api_key)

except Exception as e: 
    logger.info(f"perplexity credential is required: {e}")
    raise e
