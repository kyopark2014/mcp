import json
import boto3
import traceback
import logging
import sys
import utils
import os

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-rag")

config = utils.load_config()

bedrock_region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "mcp-rag"
accountId = config["accountId"] if "accountId" in config else None
if accountId is None:
    raise Exception ("No accountId")
region = config["region"] if "region" in config else "us-west-2"
logger.info(f"region: {region}")

numberOfDocs = 3
model_name = "Claude 3.5 Haiku"
knowledge_base_name = projectName

def retrieve_knowledge_base(query):
    lambda_client = boto3.client(
        service_name='lambda',
        region_name=bedrock_region
    )

    functionName = f"knowledge-base-for-{projectName}"
    logger.info(f"functionName: {functionName}")

    mcp_env = utils.load_mcp_env()
    grading_mode = mcp_env['grading_mode']
    logger.info(f"grading_mode: {grading_mode}")
    multi_region = mcp_env['multi_region']
    logger.info(f"multi_region: {multi_region}")

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