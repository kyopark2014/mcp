import traceback
import json
import time
import boto3
import utils
import os

from langchain_aws import AmazonKnowledgeBasesRetriever
from urllib import parse
from langchain.docstore.document import Document
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

import logging
import sys
logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("knowledge_base")

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

config = utils.load_config()

# variables
projectName = config["projectName"] if "projectName" in config else "mcp-rag"

vectorIndexName = projectName
knowledge_base_name = projectName
bedrock_region = config["region"] if "region" in config else "us-west-2"
region = config["region"] if "region" in config else "us-west-2"
logger.info(f"region: {region}")
s3_bucket = config["s3_bucket"] if "s3_bucket" in config else None
if s3_bucket is None:
    raise Exception ("No storage!")

parsingModelArn = f"arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
embeddingModelArn = f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"

collectionArn = config["collectionArn"] if "collectionArn" in config else None
if collectionArn is None:
    raise Exception ("No collectionArn")

knowledge_base_role = config["knowledge_base_role"] if "knowledge_base_role" in config else None
if knowledge_base_role is None:
    raise Exception ("No Knowledge Base Role")

s3_arn = config["s3_arn"] if "s3_arn" in config else None
if s3_arn is None:
    raise Exception ("No S3 ARN")

path = config["sharing_url"] if "sharing_url" in config else None
if path is None:
    raise Exception ("No Sharing URL")

opensearch_url = config["opensearch_url"] if "opensearch_url" in config else None
if opensearch_url is None:
    raise Exception ("No OpenSearch URL")

credentials = boto3.Session().get_credentials()
service = "aoss" 
awsauth = AWSV4SignerAuth(credentials, region, service)

def print_doc(i, doc):
    if len(doc.page_content)>=100:
        text = doc.page_content[:100]
    else:
        text = doc.page_content
            
    logger.info(f"{i}: {text}, metadata:{doc.metadata}")

s3_prefix = 'docs'
doc_prefix = s3_prefix+'/'

# Knowledge Base
knowledge_base_id = ""
data_source_id = ""

os_client = OpenSearch(
    hosts = [{
        'host': opensearch_url.replace("https://", ""), 
        'port': 443
    }],
    http_auth=awsauth,
    use_ssl = True,
    verify_certs = True,
    connection_class=RequestsHttpConnection,
)

def is_not_exist(index_name):    
    logger.info(f"index_name: {index_name}")
        
    if os_client.indices.exists(index=index_name):
        logger.info(f"use exist index: {index_name}")
        return False
    else:
        logger.info(f"no index: {index_name}")
        return True
    
def initiate_knowledge_base():
    global knowledge_base_id, data_source_id
    #########################
    # opensearch index
    #########################
    if(is_not_exist(vectorIndexName)):
        logger.info(f"creating opensearch index... {vectorIndexName}")   
        body={ 
            'settings':{
                "index.knn": True,
                "index.knn.algo_param.ef_search": 512,
                'analysis': {
                    'analyzer': {
                        'my_analyzer': {
                            'char_filter': ['html_strip'], 
                            'tokenizer': 'nori',
                            'filter': ['nori_number','lowercase','trim','my_nori_part_of_speech'],
                            'type': 'custom'
                        }
                    },
                    'tokenizer': {
                        'nori': {
                            'decompound_mode': 'mixed',
                            'discard_punctuation': 'true',
                            'type': 'nori_tokenizer'
                        }
                    },
                    "filter": {
                        "my_nori_part_of_speech": {
                            "type": "nori_part_of_speech",
                            "stoptags": [
                                    "E", "IC", "J", "MAG", "MAJ",
                                    "MM", "SP", "SSC", "SSO", "SC",
                                    "SE", "XPN", "XSA", "XSN", "XSV",
                                    "UNA", "NA", "VSV"
                            ]
                        }
                    }
                },
            },
            'mappings': {
                'properties': {
                    'vector_field': {
                        'type': 'knn_vector',
                        'dimension': 1024,
                        'method': {
                            "name": "hnsw",
                            "engine": "faiss",
                            "parameters": {
                                "ef_construction": 512,
                                "m": 16
                            }
                        }                  
                    },
                    "AMAZON_BEDROCK_METADATA": {"type": "text", "index": False},
                    "AMAZON_BEDROCK_TEXT": {"type": "text"},
                }
            }
        }

        try: # create index
            response = os_client.indices.create(
                index=vectorIndexName,
                body=body
            )
            logger.info(f"opensearch index was created: {response}")

            # delay 5 seconds
            time.sleep(5)
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")                
            #raise Exception ("Not able to create the index")
            
    #########################
    # knowledge base
    #########################
    logger.info(f"knowledge_base_name: {knowledge_base_name}")
    logger.info(f"collectionArn: {collectionArn}")
    logger.info(f"vectorIndexName: {vectorIndexName}")
    logger.info(f"embeddingModelArn: {embeddingModelArn}")
    logger.info(f"knowledge_base_role: {knowledge_base_role}")
    try: 
        if aws_access_key and aws_secret_key:   
            client = boto3.client(
                service_name='bedrock-agent',
                region_name=bedrock_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                aws_session_token=aws_session_token,
            )
        else:
            client = boto3.client(
                service_name='bedrock-agent',
                region_name=bedrock_region
            )
            
        response = client.list_knowledge_bases(
            maxResults=10
        )
        logger.info(f"(list_knowledge_bases) response: {response}")
        
        if "knowledgeBaseSummaries" in response:
            summaries = response["knowledgeBaseSummaries"]
            for summary in summaries:
                if summary["name"] == knowledge_base_name:
                    knowledge_base_id = summary["knowledgeBaseId"]
                    logger.info(f"prepknowledge_base_idare: {knowledge_base_id}")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")
    
    if not knowledge_base_id:
        logger.info(f"creating knowledge base...")  
        for atempt in range(3):
            tag_name = projectName
            try:
                response = client.create_knowledge_base(
                    name=knowledge_base_name,
                    description="Knowledge base based on OpenSearch",
                    roleArn=knowledge_base_role,
                    tags={
                        tag_name: 'true'
                    },
                    knowledgeBaseConfiguration={
                        'type': 'VECTOR',
                        'vectorKnowledgeBaseConfiguration': {
                            'embeddingModelArn': embeddingModelArn,
                            'embeddingModelConfiguration': {
                                'bedrockEmbeddingModelConfiguration': {
                                    'dimensions': 1024
                                }
                            },
                            'supplementalDataStorageConfiguration': {
                            'storageLocations': [{
                                    'type': 'S3',
                                    's3Location': {
                                        'uri': f"s3://{s3_bucket}"
                                    }
                                }]
                            }
                        }
                    },
                    storageConfiguration={
                        'type': 'OPENSEARCH_SERVERLESS',
                        'opensearchServerlessConfiguration': {
                            'collectionArn': collectionArn,
                            'fieldMapping': {
                                'metadataField': 'AMAZON_BEDROCK_METADATA',
                                'textField': 'AMAZON_BEDROCK_TEXT',
                                'vectorField': 'vector_field'
                            },
                            'vectorIndexName': vectorIndexName
                        }
                    }                    
                )   
                logger.info(f"(create_knowledge_base) response: {response}")
            
                if 'knowledgeBaseId' in response['knowledgeBase']:
                    knowledge_base_id = response['knowledgeBase']['knowledgeBaseId']
                    break
                else:
                    knowledge_base_id = ""    
            except Exception:
                    err_msg = traceback.format_exc()
                    logger.info(f"error message: {err_msg}")
                    time.sleep(5)
                    logger.info(f"retrying... {atempt}")
                    #raise Exception ("Not able to create the knowledge base")      
                
    logger.info(f"knowledge_base_name: {knowledge_base_name}, knowledge_base_id: {knowledge_base_id}")    
    
    #########################
    # data source      
    #########################
    data_source_name = s3_bucket  
    try: 
        response = client.list_data_sources(
            knowledgeBaseId=knowledge_base_id,
            maxResults=10
        )        
        logger.info(f"(list_data_sources) response: {response}")
        
        if 'dataSourceSummaries' in response:
            for data_source in response['dataSourceSummaries']:
                logger.info(f"data_source: {data_source}")
                if data_source['name'] == data_source_name:
                    data_source_id = data_source['dataSourceId']
                    logger.info(f"data_source_id: {data_source_id}")
                    break    
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")
        
    if not data_source_id:
        logger.info(f"creating data source...")
        try:
            response = client.create_data_source(
                dataDeletionPolicy='RETAIN',
                dataSourceConfiguration={
                    's3Configuration': {
                        'bucketArn': s3_arn,
                        'inclusionPrefixes': [ 
                            s3_prefix+'/',
                        ]
                    },
                    'type': 'S3'
                },
                description = f"S3 data source: {s3_bucket}",
                knowledgeBaseId = knowledge_base_id,
                name = data_source_name,
                vectorIngestionConfiguration={
                    'chunkingConfiguration': {
                        'chunkingStrategy': 'HIERARCHICAL',
                        'hierarchicalChunkingConfiguration': {
                            'levelConfigurations': [
                                {
                                    'maxTokens': 1500
                                },
                                {
                                    'maxTokens': 300
                                }
                            ],
                            'overlapTokens': 60
                        }
                    },
                    'parsingConfiguration': {
                        'bedrockFoundationModelConfiguration': {
                            'modelArn': parsingModelArn,
                            'parsingModality': 'MULTIMODAL'
                        },
                        'parsingStrategy': 'BEDROCK_FOUNDATION_MODEL'
                        # 'bedrockDataAutomationConfiguration': {
                        #     'parsingModality': 'MULTIMODAL'
                        # },
                        # 'parsingStrategy': 'BEDROCK_DATA_AUTOMATION'
                    }
                }
            )
            logger.info(f"create_data_source) response: {response}")
            
            if 'dataSource' in response:
                if 'dataSourceId' in response['dataSource']:
                    data_source_id = response['dataSource']['dataSourceId']
                    logger.info(f"data_source_id: {data_source_id}")
                    
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")
            #raise Exception ("Not able to create the data source")
    
    logger.info(f"data_source_name: {data_source_name}, data_source_id: {data_source_id}")
            
initiate_knowledge_base()

def retrieve_documents_from_knowledge_base(query, top_k):
    relevant_docs = []
    if knowledge_base_id:    
        retriever = AmazonKnowledgeBasesRetriever(
            knowledge_base_id=knowledge_base_id, 
            retrieval_config={"vectorSearchConfiguration": {
                "numberOfResults": top_k,
                "overrideSearchType": "HYBRID"   # SEMANTIC
            }},
            region_name=bedrock_region
        )
        
        try: 
            documents = retriever.invoke(query)
            # print('documents: ', documents)
            logger.info(f"--> docs from knowledge base")
            for i, doc in enumerate(documents):
                print_doc(i, doc)
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")    
            raise Exception ("Not able to request to LLM: "+err_msg)
        
        relevant_docs = []
        for doc in documents:
            content = ""
            if doc.page_content:
                content = doc.page_content
            
            score = doc.metadata["score"]
            
            link = ""
            if "s3Location" in doc.metadata["location"]:
                link = doc.metadata["location"]["s3Location"]["uri"] if doc.metadata["location"]["s3Location"]["uri"] is not None else ""
                
                # print('link:', link)    
                pos = link.find(f"/{doc_prefix}")
                name = link[pos+len(doc_prefix)+1:]
                encoded_name = parse.quote(name)
                # print('name:', name)
                link = f"{path}/{doc_prefix}{encoded_name}"
                
            elif "webLocation" in doc.metadata["location"]:
                link = doc.metadata["location"]["webLocation"]["url"] if doc.metadata["location"]["webLocation"]["url"] is not None else ""
                name = "WEB"

            url = link
            logger.info(f"url: {url}")
            
            relevant_docs.append(
                Document(
                    page_content=content,
                    metadata={
                        'name': name,
                        'score': score,
                        'url': url,
                        'from': 'RAG'
                    },
                )
            )    
    return relevant_docs

def sync_data_source():
    if knowledge_base_id and data_source_id:
        try:
            if aws_access_key and aws_secret_key:
                bedrock_client = boto3.client(
                    service_name='bedrock-agent',
                    region_name=bedrock_region,
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    aws_session_token=aws_session_token,
                )
            else:
                bedrock_client = boto3.client(
                    service_name='bedrock-agent',
                    region_name=bedrock_region
                )
                
            response = bedrock_client.start_ingestion_job(
                knowledgeBaseId=knowledge_base_id,
                dataSourceId=data_source_id
            )
            logger.info(f"(start_ingestion_job) response: {response}")
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")


    
