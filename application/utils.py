import logging
import sys
import json
import traceback
import boto3
import os

from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("utils")

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

def load_config():
    config = None
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        config = {}
        
        project_name = "mcp"

        session = boto3.Session()
        region = session.region_name

        sts_client = boto3.client("sts", region_name=region)
        account_id = sts_client.get_caller_identity()["Account"]

        config['projectName'] = project_name
        config['accountId'] = account_id
        config['region'] = region

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    
    return config

config = load_config()

bedrock_region = config.get('region', 'us-west-2')
accountId = config.get('accountId', None)
if accountId is None:
    session = boto3.Session()
    region = session.region_name
    
    sts_client = boto3.client("sts", region_name=region)
    accountId = sts_client.get_caller_identity()["Account"]
    config['accountId'] = accountId

projectName = config.get('projectName', 'mcp')

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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_env_path = os.path.join(script_dir, "mcp.env")
    
    with open(mcp_env_path, "r", encoding="utf-8") as f:
        mcp_env = json.load(f)
    return mcp_env

def save_mcp_env(mcp_env):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_env_path = os.path.join(script_dir, "mcp.env")
    
    with open(mcp_env_path, "w", encoding="utf-8") as f:
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
    #logger.info('get_weather_api_secret: ', get_weather_api_secret)
    secret = json.loads(get_weather_api_secret['SecretString'])
    #logger.info('secret: ', secret)
    weather_api_key = secret['weather_api_key']
    if weather_api_key:
        os.environ["OPENWEATHERMAP_API_KEY"] = weather_api_key

except Exception as e:
    # raise e
    pass

# api key to use Tavily Search
tavily_key = tavily_api_wrapper = ""
try:
    get_tavily_api_secret = secretsmanager.get_secret_value(
        SecretId=f"tavilyapikey-{projectName}"
    )
    #logger.info('get_tavily_api_secret: ', get_tavily_api_secret)
    secret = json.loads(get_tavily_api_secret['SecretString'])
    #logger.info('secret: ', secret)

    if "tavily_api_key" in secret:
        tavily_key = secret['tavily_api_key']
        #logger.info('tavily_api_key: ', tavily_api_key)

        if tavily_key:
            tavily_api_wrapper = TavilySearchAPIWrapper(tavily_api_key=tavily_key)
            os.environ["TAVILY_API_KEY"] = tavily_key

        else:
            logger.info(f"tavily_key is required.")
except Exception as e: 
    logger.info(f"Tavily credential is required: {e}")
    # raise e
    pass

# api key to use firecrawl Search
firecrawl_key = ""
try:
    get_firecrawl_secret = secretsmanager.get_secret_value(
        SecretId=f"firecrawlapikey-{projectName}"
    )
    secret = json.loads(get_firecrawl_secret['SecretString'])

    if "firecrawl_api_key" in secret:
        firecrawl_key = secret['firecrawl_api_key']
        # logger.info('firecrawl_api_key: ', firecrawl_key)
except Exception as e: 
    logger.info(f"Firecrawl credential is required: {e}")
    # raise e
    pass

# api key to use perplexity Search
perplexity_key = ""
try:
    get_perplexity_api_secret = secretsmanager.get_secret_value(
        SecretId=f"perplexityapikey-{projectName}"
    )
    #logger.info('get_perplexity_api_secret: ', get_perplexity_api_secret)
    secret = json.loads(get_perplexity_api_secret['SecretString'])
    #logger.info('secret: ', secret)

    if "perplexity_api_key" in secret:
        perplexity_key = secret['perplexity_api_key']
        #logger.info('perplexity_api_key: ', perplexity_api_key)

except Exception as e: 
    logger.info(f"perplexity credential is required: {e}")
    # raise e
    pass

# api key to use nova act
nova_act_key = ""
try:
    get_nova_act_api_secret = secretsmanager.get_secret_value(
        SecretId=f"novaactapikey-{projectName}"
    )
    #logger.info('get_perplexity_api_secret: ', get_perplexity_api_secret)
    secret = json.loads(get_nova_act_api_secret['SecretString'])
    #logger.info('secret: ', secret)

    if "nova_act_api_key" in secret:
        nova_act_key = secret['nova_act_api_key']
        #logger.info('nova_act_api_key: ', nova_act_api_key)

except Exception as e: 
    logger.info(f"nova act credential is required: {e}")
    # raise e
    pass

# api key to use Notion
notion_api_key = ""
try:
    get_notion_api_secret = secretsmanager.get_secret_value(
        SecretId=f"notionapikey-{projectName}"
    )
    secret = json.loads(get_notion_api_secret['SecretString'])

    if "notion_api_key" in secret:
        notion_api_key = secret['notion_api_key']

        if notion_api_key:
            os.environ["NOTION_API_KEY"] = notion_api_key
        else:
            logger.info(f"notion_api_key is required.")
except Exception as e:
    logger.info(f"Notion credential is required: {e}")
    pass

# api key for slack
slack_bot_token = ""
slack_team_id = ""
try:
    get_slack_secret = secretsmanager.get_secret_value(
        SecretId=f"slackapikey-{projectName}"
    )
    secret = json.loads(get_slack_secret['SecretString'])
    slack_bot_token = secret.get('slack_bot_token', '')
    slack_team_id = secret.get('slack_team_id', '')
    if slack_bot_token:
        os.environ["SLACK_BOT_TOKEN"] = slack_bot_token
    if slack_team_id:
        os.environ["SLACK_TEAM_ID"] = slack_team_id
except Exception as e:
    logger.info(f"Slack credential is required: {e}")
    pass

def status(st, str):
    st.info(str)
def stcode(st, code):
    st.code(code)
