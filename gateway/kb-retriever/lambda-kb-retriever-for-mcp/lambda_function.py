import json
import boto3
import os

knowledge_base_id = os.environ.get('KNOWLEDGE_BASE_ID', '')
number_of_results = 5

bedrock_agent_runtime_client = boto3.client("bedrock-agent-runtime")

def retrieve(query: str) -> str:
    response = bedrock_agent_runtime_client.retrieve(
        retrievalQuery={"text": query},
        knowledgeBaseId=knowledge_base_id,
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": number_of_results},
            },
        )
    
    # print(f"response: {response}")
    retrieval_results = response.get("retrievalResults", [])
    # print(f"retrieval_results: {retrieval_results}")

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
                # encoded_name = parse.quote(name)                
                # url = f"{path}/{doc_prefix}{encoded_name}"
                url = uri # TODO: add path and doc_prefix
                
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
    print(f"json_docs: {json_docs}")

    return json.dumps(json_docs, ensure_ascii=False)

def lambda_handler(event, context):
    print(f"event: {event}")
    print(f"context: {context}")

    toolName = context.client_context.custom['bedrockAgentCoreToolName']
    print(f"context.client_context: {context.client_context}")
    print(f"Original toolName: {toolName}")
    
    delimiter = "___"
    if delimiter in toolName:
        toolName = toolName[toolName.index(delimiter) + len(delimiter):]
    print(f"Converted toolName: {toolName}")

    keyword = event.get('keyword')
    print(f"keyword: {keyword}")

    if toolName == 'retrieve':
        result = retrieve(keyword)
        print(f"result: {result}")
        return {
            'statusCode': 200, 
            'body': result
        }
    else:
        return {
            'statusCode': 200, 
            'body': f"{toolName} is not supported"
        }
