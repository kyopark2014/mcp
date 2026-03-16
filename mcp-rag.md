## Knowledge Base 기반의 RAG

[mcp_server_retrieve.py](./application/mcp_server_retrieve.py)와 같이 Knowledge Base 기반으로 RAG를 제공하는 MCP를 구현할 수 있습니다. 실제 동작은 [mcp_retrieve.py](./application/mcp_retrieve.py)와 같이 구현합니다.

```python
bedrock_agent_runtime_client = boto3.client("bedrock-agent-runtime", region_name=bedrock_region)

def retrieve(query):
    response = bedrock_agent_runtime_client.retrieve(
        retrievalQuery={"text": query},
        knowledgeBaseId=knowledge_base_id,
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": number_of_results},
                },
            )
    
    retrieval_results = response.get("retrievalResults", [])
    
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
```

### MCP 설정

```java
{
   "mcpServers":{
      "kb_retriever":{
         "command":"python",
         "args":[
            "f""{workingDir}/mcp_server_retrieve.py"
         ]
      }
   }
}
```
