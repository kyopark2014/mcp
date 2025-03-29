import asyncio
import info
import boto3

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_mcp_adapters.tools import load_mcp_tools
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

server_params = StdioServerParameters(
  command="python",
  args=["/Users/ksdyb/Documents/src/mcp/mcp-rag/rag-server.py"],
)

from mcp.client.stdio import stdio_client

async def run_agent():
  async with stdio_client(server_params) as (read, write):
    # Open an MCP session to interact with the rag_server.py tool.
    async with ClientSession(read, write) as session:
      # Initialize the session.
      await session.initialize()
      
      # Load tools
      tools = await load_mcp_tools(session)
      print(f"tools: {tools}")

    #   for tool in tools:
    #     print(f'tool: {tool}\n')
    #     print(f"name: {tool.name}")
              
    #     args_schema = tool.args_schema
    #     print(f"args_schema: {args_schema}")

    #     if hasattr(tool, 'description'):
    #         description = tool.description
    #         print(f"description: {description}")

    #     response_format = tool.response_format
    #     print(f"response_format: {response_format}")
      
      agent = create_react_agent(model, tools)
      
      # Run the agent.
      #agent_response = await agent.ainvoke({"messages": "What is the capital of France?"})
      #agent_response = await agent.ainvoke({"messages": "what's (4 + 6) x 14?"})
      agent_response = await agent.ainvoke({"messages": "보일러 에러코드에 대해 설명해주세요."})
      print(f"agent_response: {agent_response}")

      # Return the response.
      return agent_response["messages"][3].content

if __name__ == "__main__":
  result = asyncio.run(run_agent())
  print(f"result: {result}")
