import asyncio
import info
import boto3

from langchain.mcp import MCPAdapter
from langgraph.prebuilt import create_react_agent
from langchain_aws import ChatBedrock
from botocore.config import Config

multi_region = "Disable"
model_name = "Claude 3.7 Sonnet"
models = info.get_model_info(model_name)
number_of_models = len(models)
selected_chat = 0

def get_chat(extended_thinking):
    global selected_chat, model_type

    profile = models[selected_chat]
    # print('profile: ', profile)
        
    bedrock_region =  profile['bedrock_region']
    modelId = profile['model_id']
    model_type = profile['model_type']
    if model_type == 'claude':
        maxOutputTokens = 4096 # 4k
    else:
        maxOutputTokens = 5120 # 5k
    print(f'LLM: {selected_chat}, bedrock_region: {bedrock_region}, modelId: {modelId}, model_type: {model_type}')

    if profile['model_type'] == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif profile['model_type'] == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 
                          
    # bedrock   
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
        print(f"extended_thinking: {extended_thinking}")
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

model = get_chat(extended_thinking="Disable")

MCP_SERVERS = {
  "mcpServers": {
    "math": {
      "transport": "stdio",
      "command": "python",
      "args": ["mcp-server.py"],
    }
  }
}

async def run_agent():
  async with MCPAdapter(MCP_SERVERS) as adapter:
    tools = await adapter.list_tools()
    print(f"tools: {tools}")
    agent = create_react_agent(model, tools)
    agent_response = await agent.ainvoke({"messages": "what's (4 + 6) x 14?"})
    print(f"agent_response: {agent_response}")
    return agent_response["messages"][3].content

if __name__ == "__main__":
  result = asyncio.run(run_agent())
  print(result)