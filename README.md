# MCP Application 구현하기

MCP(Model Context Protocol)은 생성형 AI application이 외부 데이터를 활용하는 주요한 인터페이스로 빠르게 확산되고 있습니다. 2024년 11월에 Anthropic의 오픈소스 프로젝트로 시작되었고, 현재 Cursor뿐 아니라 OpenAI에서도 지원하고 있습니다. 여기에서는 [MCP with LangChain](https://github.com/langchain-ai/langchain-mcp-adapters)을 이용하여 LangGraph로 만든 application이 MCP를 활용하는 방법에 대해 설명합니다. 여기서 구현한 RAG는 Amazon의 완전관리형 RAG 서비스인 Knowledge base로 구현되었으므로, 문서의 텍스트 추출, 동기화, chunking과 같은 작업을 손쉽게 수행할 수 있으며, 멀티모달을 이용해 이미지/표를 분석할 수 있습니다. 여기에서는 MCP server에서 RAG에 손쉽게 접근할 수 있도록 AWS Lambda를 이용해 API를 구성하였습니다.


아래 architecture는 AWS 환경에서 MCP를 포함한 Agent를 구성하는것을 보여줍니다. Agent는 MCP server/client 구조를 활용하여 외부의 데이터 소스를 활용할 수 있습니다. MCP client는 MCP server와 JSON-RPC 프로토콜에 기반하여 stdio/SSE로 통신을 수행합니다. Stdio 사용시 MCP Server는 python, java와 같은 코드로 구성이 되고, client에서 요청이 오면 RAG나 인터넷등을 이용해 데이터를 수집하거나 전달하는 역할을 수행합니다. SSE로 할 경우에 MCP client와 server는 IP로 통신을 하게 됩니다. 여기서는 Streamlit을 이용해 application의 UI를 구성하고, 사용자는 ALB - CloudFront를 이용해 HTTPS 방식으로 브라우저를 통해 application을 이용합니다. 또한, 여기에서는 커스터마이징이 유리한 LangGraph를 이용해 MCP 기반의 application을 개발하는것을 설명합니다. 

<img src="https://github.com/user-attachments/assets/a263f0fa-22f1-483b-8936-a59429ace173" width="750">


## MCP 활용

### MCP Basic

사용자는 자신의 Computer에 설치된 Claude Desktop, Cursor와 같은 AI 도구뿐 아니라 주로 Agent형태로 개발된 어플리케이션을 통해 MCP 서버에 연결할 수 있습니다. MCP server는 MCP client의 요청에 자신이 할수 있는 기능을 capability로 제공하고 client의 요청을 수행합니다. MCP server는 local computer의 파일이나 데이터베이스를 조회할 수 있을뿐 아니라 인터넷에 있는 외부 서버의 API를 이용해 필요한 정보를 조회할 수 있습니다. MCP Client는 Server와 JSON-RPC 2.0 프로토콜을 이용해 연결되는데, stdio나 SSE (Server-Sent Events)을 선택하여, Host의 요청을 MCP에 전달할 수 있고, 응답을 받아서 활용할 수 있습니다.  

<img src="https://github.com/user-attachments/assets/36d2d24c-865b-4b71-b708-5c611ab7785e" width="750">


MCP의 주요 요소의 정의와 동작은 아래와 같습니다.

- MCP Hosts: MCP 프로토콜을 통해 데이터에 접근하는 프로그램/AI 도구로서 Claude Desktop, Cursor, User Agent Application이 해당됩니다.
- MCP Clients: MCP Server와 1:1로 연결을 수행하는 Client로서 MCP Server와 stdio 또는 SSE 방식으로 연결할 수 있습니다.
- MCP Servers: 표준화된 MCP를 통해 Client에 Tool의 Capability를 알려주는 경량 프로그램으로 Local Computer의 파일이나 데이터베이스를 조회할 수 있고, 외부 API를 이용해 정보를 조회할 수 있습니다.
- Local data sources: MCP 서버가 접근할 수 있는 데이터베이스와 로컬 데이터
- Remote services: API를 통해 접근 가능한 외부 시스템

MCP를 사용하면 아래와 같은 장점이 있습니다.

- 표준화된 방식으로 다양한 데이터 소스에 접근 가능합니다.
- 애플리케이션 코드 변경 없이 MCP 서버 업데이트를 통한 새로운 기능 추가할 수 있습니다.
- 조직 전반에 걸쳐 AI 지원 및 확장이 용이합니다.


[MCP Server Components](https://www.philschmid.de/mcp-introduction)에는 아래와 같은 항목이 있습니다. 

- Tools (Model-controlled): LLM이 특정 작업을 수행하기 위해 호출할 수 있는 기능(도구)으로서, API와 같이 특정한 action을 수행합니다. 

```python
tools = await session.list_tools()
```

- Resources (Application-controlled): 생성형 AI 어플리케이션이 접근 할 수 있는 데이터 소스입니다. 복잡한 계산(significant computation)이나 부작용(side effect)없이 데이터를 가져올 수 있습니다. 

```python
resources = await session.list_resources()
```

- Prompts (User-controlled): tool나 resource를 사용할때에 이용하는 사전 정의된 템플렛으로서 추론(inference)전에 선택할 수 있습니다.

```python
prompts = await session.list_prompts()
```
  
### LangChain MCP Adapter

[LangChain MCP Adapter](https://github.com/langchain-ai/langchain-mcp-adapters)는 MCP를 LangGraph agent와 함께 사용할 수 있게 해주는 경량의 랩퍼(lightweight wrapper)로서 MIT 기반의 오픈소스입니다. MCP Adapter의 주된 역할은 MCP server를 위한 tool들을 정의하고, MCP client에서 tools의 정보를 조회하고 LangGraph의 tool node로 정의하여 활용할 수 있도록 도와줍니다. 

#### 사전 준비

MCP와 LangChain MCP Adapter를 아래와 같이 설치합니다.

```text
pip install mcp langchain-mcp-adapters
```

#### MCP Server

RAG 검색을 위한 MCP server는 아래와 같이 정의할 수 있습니다. Server의 transport를 "stdio"로 지정하면 server를 지속 실행시키지 않더라도, client가 server의 python code를 직접 실행할 수 있어서 편리합니다. 

```python
from mcp.server.fastmcp import FastMCP 

mcp = FastMCP(
    name = "Search",
    instructions=(
        "You are a helpful assistant. "
        "You can search the documentation for the user's question and provide the answer."
    ),
) 

@mcp.tool()
def search(keyword: str) -> str:
    "search keyword"

    return retrieve_knowledge_base(keyword)

if __name__ =="__main__":
    print(f"###### main ######")
    mcp.run(transport="stdio")
```

Server는 요청이 들어오면, retrieve_knowledge_base()로 RAG 검색을 수행합니다. Server의 python code는 경량(lightweight)이어야 하므로, 아래와 같이 lambda를 trigger하는 방식으로 구성하였습니다. Lambda에서는 retrieve, grade, generation의 동작을 수행합니다. 아래와 같이 "model_name"을 지정할 수 있고, 필요에 따라서는 "grading"을 선택적으로 사용할 수 있습니다. 또한 병렬처리로 속도를 빠르게 하고 싶은 경우에은 "multi_region"을 "Enable"로 설정합니다. 상세한 코드는 [lambda-rag](./lambda-rag/lambda_function.py)를 참조합니다. 

```python
def retrieve_knowledge_base(query):
    lambda_client = boto3.client(
        service_name='lambda',
        region_name=bedrock_region
    )
    functionName = f"lambda-rag-for-{projectName}"
    payload = {
        'function': 'search_rag',
        'knowledge_base_name': knowledge_base_name,
        'keyword': query,
        'top_k': numberOfDocs,
        'grading': "Enable",
        'model_name': model_name,
        'multi_region': multi_region
    }
    output = lambda_client.invoke(
        FunctionName=functionName,
        Payload=json.dumps(payload),
    )
    payload = json.load(output['Payload'])
    return payload['response'], []
```

[Drug discovery](https://github.com/kyopark2014/mcp/blob/main/drug-discovery.md)와 관련하여, [arXiv](./application/mcp_server_arxiv.py), [ChEMBL](./application/mcp_server_chembl.py), [ClinicalTrials.gov](./application/mcp_server_clinicaltrial.py), [PubMed](./application/mcp_server_pubmed.py)을 지원하고 있습니다.

#### MCP Client

MCP client이 하나의 MCP server만 볼 경우에는 아래와 같이 stdio_client와 StdioServerParameters를 이용해 구현할 수 있습니다. MCP server에 대한 정보는 config.json에서 읽어오거나 streamlit에서 사용자가 입력한 정보를 사용할 수 있습니다. load_mcp_server_parameters()에서는 mcp_json을 읽어와서 [StdioServerParameters](https://github.com/langchain-ai/langchain-mcp-adapters)을 구성합니다. config.json의 MCP server에 대한 정보는 AWS CDK로 배포후 생성되는 output에서 가져옵니다.

```python
from mcp import ClientSession, StdioServerParameters

def load_mcp_server_parameters():
    mcp_json = json.loads(mcp_config)
    mcpServers = mcp_json.get("mcpServers")

    command = ""
    args = []
    if mcpServers is not None:
        for server in mcpServers:
            config = mcpServers.get(server)
            if "command" in config:
                command = config["command"]
            if "args" in config:
                args = config["args"]
            break

    return StdioServerParameters(
        command=command,
        args=args
    )
```

아래와 같이 MCP server에 대한 정보로 stdio_client를 구성합니다. 이때 tools에 대한 정보를 load_mcp_tools로 가져옵니다. Agent에서는 tool 정보를 bind하고 ainvoke를 이용해 요청된 동작을 수행합니다. 

```python
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

async def mcp_rag_agent_single(query, st):
    server_params = load_mcp_server_parameters()

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            with st.status("thinking...", expanded=True, state="running") as status:       
                agent = create_agent(tools)
                agent_response = await agent.ainvoke({"messages": query})                

                result = agent_response["messages"][-1].content
            st.markdown(result)
            st.session_state.messages.append({
                "role": "assistant", 
                "content": result
            })            
            return result
```

MCP client는 아래와 같이 실행합니다. 비동기적으로 실행하기 위해서 asyncio를 이용하였습니다.  이후 사용자가 UI에서 MCP Config를 업데이트하면 정보를 업데이트 할 수 있습니다. 

```python
asyncio.run(mcp_rag_agent_single(query, st))
```

서버 정보가 여럿인 경우에 [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters)에서 제공하는 MultiServerMCPClient을 이용합니다. 먼저, 아래와 같이 서버 정보를 가져옵니다. 

```python
def load_multiple_mcp_server_parameters():
    mcp_json = json.loads(mcp_config)
    mcpServers = mcp_json.get("mcpServers")

    server_info = {}
    if mcpServers is not None:
        command = ""
        args = []
        for server in mcpServers:
            config = mcpServers.get(server)
            if "command" in config:
                command = config["command"]
            if "args" in config:
                args = config["args"]

            server_info[server] = {
                "command": command,
                "args": args,
                "transport": "stdio"
            }
    return server_info
```

이후 아래와 같이 MCP server정보와 MultiServerMCPClient로 client를 정의합니다. MCP server로 부터 가져온 tool 정보는 client.get_tools()로 가져와서 agent를 생성할 때에 사용합니다. Single MCP server와 마찬가지로 ainvoke로 실행하여 결과를 얻을 수 있습니다. 

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
asyncio.run(mcp_rag_agent_multiple(query, st))

async def mcp_rag_agent_multiple(query, st):
    server_params = load_multiple_mcp_server_parameters()
    async with  MultiServerMCPClient(server_params) as client:
        with st.status("thinking...", expanded=True, state="running") as status:                       
            tools = client.get_tools()
            agent = create_agent(tools)
            response = await agent.ainvoke({"messages": query})
            result = response["messages"][-1].content

        st.markdown(result)
        st.session_state.messages.append({
            "role": "assistant", 
            "content": result
        })
    return result
```

여기서는 customize가 용이하도록 agent를 정의하였습니다.

```python
def create_agent(tools):
    tool_node = ToolNode(tools)

    chatModel = get_chat(extended_thinking="Disable")
    model = chatModel.bind_tools(tools)

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    def call_model(state: State, config):
        system = (
            "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다."
            "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다."
            "모르는 질문을 받으면 솔직히 모른다고 말합니다."
            "한국어로 답변하세요."
        )
        try:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", system),
                    MessagesPlaceholder(variable_name="messages"),
                ]
            )
            chain = prompt | model                
            response = chain.invoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: State) -> Literal["continue", "end"]:
        messages = state["messages"]    
        last_message = messages[-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "continue"        
        else:
            return "end"

    def buildChatAgent():
        workflow = StateGraph(State)
        workflow.add_node("agent", call_model)
        workflow.add_node("action", tool_node)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {
                "continue": "action",
                "end": END,
            },
        )
        workflow.add_edge("action", "agent")
        return workflow.compile() 
    
    return buildChatAgent()
```

## MCP Servers의 활용

[Model Context Protocol servers](https://github.com/modelcontextprotocol/servers)에서도 아래와 같은 서버들에 대한 정보를 제공하고 있습니다.

- [Perplexity Ask MCP Server](https://github.com/ppl-ai/modelcontextprotocol)
- [Riza MCP Server](https://github.com/riza-io/riza-mcp)
- [Tavily MCP Server](https://github.com/tavily-ai/tavily-mcp)

[Smithery](https://smithery.ai/)에서 MCP server를 찾아보고 필요한 서버를 찾으면 접속할 수 있는 MCP 서버 정보를 JSON 형태로 조회할 수 있습니다. 

<img src="https://github.com/user-attachments/assets/62e534ee-88bd-4f9f-a4ff-129522fd834f" width="500">

[Smithery - Google Search Server](https://smithery.ai/server/@gradusnikov/google-search-mcp-server)에서 확인한 구글 검색용 MCP 서버 정보는 아래와 같습니다. 검색엔진 ID와 API Key를 필요로 합니다. 

```java
{
  "mcpServers": {
    "google-search-mcp-server": {
      "command": "npx",
      "args": [
        "-y",
        "@smithery/cli@latest",
        "run",
        "@gradusnikov/google-search-mcp-server",
        "--config",
        "{\"googleCseId\":\"b5cd8c527fbd64b72\",\"googleApiKey\":\"AIzbSyDQlYpck8-9TbBSuxoew1luOGVB6unRPNk\"}"
      ]
    }
  }
}
```

아래와 같이 json 형식의 서버정보를 업데이트 할 수 있습니다. 아래에서는 [mcp-server.py](./application/mcp-server.py)에서 정의한 search를 이용하고 있습니다.

```java
{
  "mcpServers": {
    "search": {
      "command": "python",
      "args": [
        "application/mcp-server.py"
      ]
    }
  }
}
```

### 실행하기

Output의 environmentformcprag의 내용을 복사하여 application/config.json을 생성합니다. "aws configure"로 credential이 설정되어 있어야합니다. 만약 visual studio code 사용자라면 config.json 파일은 아래 명령어를 사용합니다.

```text
code application/config.json
```

venv로 환경을 구성하면 편리합니다. 아래와 같이 환경을 설정합니다.

```text
python -m venv venv
source venv/bin/activate
```

이후 다운로드 받은 github 폴더로 이동한 후에 아래와 같이 필요한 패키지를 추가로 설치 합니다.

```text
pip install -r requirements.txt
```

[deployment.md](./deployment.md)에 따라 AWS CDK로 Lambda, Knowledge base, Opensearch Serverless와 보안에 필요한 IAM Role을 설치합니다. 이후 아래와 같은 명령어로 streamlit을 실행합니다. 

```text
streamlit run application/app.py
```


### EC2에 배포하기

EC2가 private subnet에 있으므로 Session Manger로 접속합니다. 이때 설치는 ec2-user로 진행되었으므로 아래와 같이 code를 업데이트합니다.

```text
sudo runuser -l ec2-user -c 'cd /home/ec2-user/mcp && git pull'
```

이제 아래와 같이 docker를 빌드합니다.

```text
sudo runuser -l ec2-user -c "cd mcp && docker build -t streamlit-app ."
```

빌드가 완료되면 "sudo docker ps"로 docker id를 확인후에 "sudo docker kill" 명령어로 종료합니다.

![noname](https://github.com/user-attachments/assets/4afb2af8-d092-4aaa-813a-65975375f7d4)

이후 아래와 같이 다시 실행합니다.

```text
sudo runuser -l ec2-user -c 'docker run -d -p 8501:8501 streamlit-app'
```

만약 console에서 debugging할 경우에는 -d 옵션없이 아래와 같이 실행합니다.

```text
sudo runuser -l ec2-user -c 'docker run -p 8501:8501 streamlit-app'
```


### MCP Inspector

Development Mode에서 mcp server를 테스트 하기 위해 MCP inspector를 이용할 수 있습니다. 아래와 같이 cli를 설치합니다. 

```text
pip install 'mcp[cli]'
```

이후 아래와 같이 실행하면 쉽게 mcp-server.py의 동작을 테스트 할 수 있습니다. 실행시 http://localhost:5173 와 같은 URL을 제공합니다.

```text
mcp dev mcp-server.py
```

### AWS Cost Analysis

MCP tool로서 아래와 같이 AWS cost 정보를 가져와서 분석할 수 있습니다.

```python
from datetime import datetime, timedelta
import pandas as pd

def get_cost_analysis(days: str=30):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)    
    ce = boto3.client('ce')
    service_response = ce.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='MONTHLY',
        Metrics=['UnblendedCost'],
        GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
    )        
    service_costs = pd.DataFrame([
        {
            'SERVICE': group['Keys'][0],
            'cost': float(group['Metrics']['UnblendedCost']['Amount'])
        }
        for group in service_response['ResultsByTime'][0]['Groups']
    ])
        
    # region cost
    region_response = ce.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='MONTHLY',
        Metrics=['UnblendedCost'],
        GroupBy=[{'Type': 'DIMENSION', 'Key': 'REGION'}]
    )
    region_costs = pd.DataFrame([
        {
            'REGION': group['Keys'][0],
            'cost': float(group['Metrics']['UnblendedCost']['Amount'])
        }
        for group in region_response['ResultsByTime'][0]['Groups']
    ])
        
    # Daily Cost
    daily_response = ce.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='DAILY',
        Metrics=['UnblendedCost'],
        GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
    )    
    daily_costs = []
    for time_period in daily_response['ResultsByTime']:
        date = time_period['TimePeriod']['Start']
        for group in time_period['Groups']:
            daily_costs.append({
                'date': date,
                'SERVICE': group['Keys'][0],
                'cost': float(group['Metrics']['UnblendedCost']['Amount'])
            })    
    daily_costs_df = pd.DataFrame(daily_costs)
        
    return {
        'service_costs': service_costs,
        'region_costs': region_costs,
        'daily_costs': daily_costs_df
    }
```

cost의 상기 3가지 결과를 그래프로 사용하기 위해서는 아래 패키지 설치가 필요합니다.

```text
pip install -U kaleido
```

### MCP Image Generation

[mcp_server_image_generation.py](./application/mcp_server_image_generation.py)과 같이 mcp_generate_image와 mcp_generate_image_with_colors을 tool로 등록합니다. 

MCP config는 아래와 같이 설정합니다. [mcp_config.py](./application/mcp_config.py)을 참조합니다.

```java
{
    "mcpServers": {
        "imageGeneration": {
            "command": "python",
            "args": [
                "application/mcp_server_image_generation.py"
            ]
        }
    }
}
```

이후 [mcp_nova_canvas.py](./application/mcp_nova_canvas.py)와 같이 이미지를 생성합니다.

```python
async def mcp_generate_image(ctx, prompt, negative_prompt, filename, width, height, quality, cfg_scale, seed, number_of_images):
    """Generate an image using Amazon Nova Canvas with text prompt."""
    
    response = await generate_image_with_text(
        prompt=prompt,
        negative_prompt=negative_prompt,
        filename=filename,
        width=width,
        height=height,
        quality=quality,
        cfg_scale=cfg_scale,
        seed=seed,
        number_of_images=number_of_images
    )

    return {
        "url": [f'{path}' for path in response.paths]
    } 
```

MCP의 image_generation로 부터 얻은 결과는 아래와 같이 표시합니다. 상세한 내용은 [chat.py](./application/chat.py)을 참고하세요.

```python
def show_status_message(response, st):
    image_url = []
    for i, re in enumerate(response):
        logger.info(f"message[{i}]: {re}")
        if i==len(response)-1:
            break
        if isinstance(re, ToolMessage):
          tool_result = json.loads(re.content)
          logger.info(f"tool_result: {tool_result}")

          if "url" in tool_result:
              st.info(f"URL: {tool_result['url']}")

              urls = tool_result['url']
              for url in urls:
                  image_url.append(url)
                  st.image(url)
    return image_url
```

### MCP AWS Diagram

[AWS Diagram MCP Server](https://awslabs.github.io/mcp/servers/aws-diagram-mcp-server/)을 이용하면 AWS Diagram을 그릴 수 있습니다. 상세한 내용은 [mcp_config.py](./application/mcp_config.py)을 참조합니다.

이때 사용하는 MCP Config는 아래와 같습니다.

```python
{
    "mcpServers": {
        "awslabs.aws-diagram-mcp-server": {
            "command": "uvx",
            "args": ["awslabs.aws-diagram-mcp-server"],
            "env": {
                "FASTMCP_LOG_LEVEL": "ERROR"
            },
        }
    }
}
```

Diagram을 그리기 위해서는 [Graphviz](https://www.graphviz.org/download/)를 따라서 graphviz를 설치합니다. Mac에서는 아래 명령어를 사용합니다.

```text
brew install graphviz
```

### MCP AWS Documentation

[AWS Documentation MCP Server](https://awslabs.github.io/mcp/servers/aws-documentation-mcp-server/)을 이용하여 AWS 문서들을 조회할 수 있습니다. 이때 사용하는 MCP config는 아래와 같습니다. 상세한 내용은 [mcp_config.py](./application/mcp_config.py)을 참조합니다.

```java
{
    "mcpServers": {
        "awslabs.aws-documentation-mcp-server": {
            "command": "uvx",
            "args": ["awslabs.aws-documentation-mcp-server@latest"],
            "env": {
                "FASTMCP_LOG_LEVEL": "ERROR"
            }
        }
    }
}
```

## Memory 

Chatbot은 연속적인 사용자의 상호작용을 통해 사용자의 경험을 향상시킬수 있습니다. 이를 위해 이전 대화의 내용을 새로운 대화에서 활용할 수 있어야하며, 일반적으로 chatbot은 sliding window를 이용해 새로운 transaction마다 이전 대화내용을 context로 제공해야 했습니다. 여기에서는 필요한 경우에만 이전 대화내용을 참조할 수 있도록 short term/long term 메모리를 MCP를 이용해 활용합니다. 이렇게 하면 context에 불필요한 이전 대화가 포함되지 않아서 사용자의 의도를 명확히 반영하고 비용도 최적화 할 수 있습니다. 

아래 architecture에서는 MCP로 short/long term meory를 활용하는 방법을 설명합니다. [AgentCore memory]를 이용하면 별도의 DB를 만들어서 관리하지 않아도 생성형 AI 애플리케이션에 필요한 short/long term memory를 활용할 수 있습니다. 대화중 발생하는 transaction은 short-term memory에 저장되며, 주로 최근 n개의 메시지를 가져오는 방식으로 활용됩니다. 대화중 중요한 정보는 long-term memory에 저장됩니다. 이때 namespace를 이용해 저장되는 위치와 검색의 범위를 조정할 수 있습니다. Long-term memory는 prompt를 가진 strategy을 이용해 사용자의 메시지로부터 필요한 정보를 추출합니다. 추출 과정에서는 Amazon Bedrock의 Claude나 OpenAI의 OSS 같은 모델을 활용할 수 있습니다. Long-term memory를 지원하는 MCP를 활용하면 대화중에 필요한 정보를 가져와서 활용할 수 있습니다.

<img src="./contents/memory.png" width="700">


### Short Term Memory

Short term memory를 위해서는 대화 transaction을 아래와 같이 agentcore의 memory에 저장합니다. 상세한 코드는 [agentcore_memory.py](./application/agentcore_memory.py)을 참조합니다.

```python
def save_conversation_to_memory(memory_id, actor_id, session_id, query, result):
    event_timestamp = datetime.now(timezone.utc)
    conversation = [
        (query, "USER"),
        (result, "ASSISTANT")
    ]
    memory_result = memory_client.create_event(
        memory_id=memory_id,
        actor_id=actor_id, 
        session_id=session_id, 
        event_timestamp=event_timestamp,
        messages=conversation
    )
```

이후, 대화중에 사용자의 이전 대화정보가 필요하다면, [mcp_server_short_term_memory.py](./application/mcp_server_short_term_memory.py)와 같이 memory, actor, session로 max_results 만큼의 이전 대화를 조회하여 활용합니다.  

```python
events = client.list_events(
    memory_id=memory_id,
    actor_id=actor_id,
    session_id=session_id,
    max_results=max_results
)
```

### Long Term Memory

Long term meory를 위해 필요한 정보에는 memory, actor, session, namespace가 있습니다. 아래와 같이 이미 저장된 값이 있다면 가져오고, 없다면 생성합니다. 상세한 코드는 [langgraph_agent.py](./application/langgraph_agent.py)을 참조합니다.

```python
# initate memory variables
memory_id, actor_id, session_id, namespace = agentcore_memory.load_memory_variables(chat.user_id)
logger.info(f"memory_id: {memory_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")

if memory_id is None:
    # retrieve memory id
    memory_id = agentcore_memory.retrieve_memory_id()
    logger.info(f"memory_id: {memory_id}")        
    
    # create memory if not exists
    if memory_id is None:
        memory_id = agentcore_memory.create_memory(namespace)
    
    # create strategy if not exists
    agentcore_memory.create_strategy_if_not_exists(memory_id=memory_id, namespace=namespace, strategy_name=chat.user_id)

    # save memory variables
    agentcore_memory.update_memory_variables(
        user_id=chat.user_id, 
        memory_id=memory_id, 
        actor_id=actor_id, 
        session_id=session_id, 
        namespace=namespace)
```

생성형 AI 애플리케이션에서는 대화중 필요한 메모리 정보가 있다면 이를 MCP를 이용해 조회합니다. [mcp_server_long_term_memory.py](./application/mcp_server_long_term_memory.py)에서는 long term memory를 이용해 대화 이벤트를 저장하거나 조회할 수 있습니다. 아래는 신규로 레코드를 생성하는 방법입니다.

```python
response = create_event(
    memory_id=memory_id,
    actor_id=actor_id,
    session_id=session_id,
    content=content,
    event_timestamp=datetime.now(timezone.utc),
)
event_data = response.get("event", {}) if isinstance(response, dict) else {}
```

대화에 필요한 정보는 아래와 같이 조회합니다.

```python
contents = []
response = retrieve_memory_records(
    memory_id=memory_id,
    namespace=namespace,
    search_query=query,
    max_results=max_results,
    next_token=next_token,
)
relevant_data = {}
if isinstance(response, dict):
    if "memoryRecordSummaries" in response:
        relevant_data["memoryRecordSummaries"] = response["memoryRecordSummaries"]    
    for memory_record_summary in relevant_data["memoryRecordSummaries"]:
        json_content = memory_record_summary["content"]["text"]
        content = json.loads(json_content)
        contents.append(content)
```

"내가 다니는 회사에 대해 소개해줘"라고 질문하면 long term memory에서 사용자에 대한 정보를 가져와서 아래와 같은 결과를 보여줍니다.

<img width="719" height="721" alt="image" src="https://github.com/user-attachments/assets/da23b49e-5a4b-402f-b314-62211bb59b30" />



## 실행 결과

### MCP로 RAG를 조회하여 활용하기

[error_code.pdf](./contents/error_code.pdf)을 다운로드 한 후에 파일을 업로드합니다. 이후 아래와 같이 "보일러 에러중 수압과 관련된 에러 코드를 검색해주세요."와 같이 입력하면 mcp를 이용해 tool의 정보를 가져오고, search tool로 얻어진 정보를 이용해 아래와 같은 정보를 보여줄 수 있습니다. 이때 search tool은 lambda를 실행하는데 lambda에서는 완전 관리형 RAG 서비스인 knowledge base를 이용하여 검색어를 조회하고 관련성을 평가한 후에 관련된 문서만을 전달합니다. Agent는 RAG를 조회하여 얻어진 정보로 답변을 아래와 같이 구합니다.

<img src="https://github.com/user-attachments/assets/01b5e47f-ada1-405e-8455-3d3ce260cb41" width="650">

### MCP로 인터넷 검색을 하여 활용하기

[smithery-Tavily](https://smithery.ai/server/mcp-tavily)에 접속하여 환경에 맞는 설정값을 얻어옵니다. 아래는 Mac/Linux의 JSON format의 접속 정보입니다.

```java
{
  "mcpServers": {
    "mcp-tavily": {
      "command": "npx",
      "args": [
        "-y",
        "@smithery/cli@latest",
        "run",
        "mcp-tavily",
        "--key",
        "132c5abd-6f2e-4e42-89a1-d0b1fcb75613"
      ]
    }
  }
}
```

아래는 기본 설정된 RAG를 위한 정보입니다.

```java
{
  "mcpServers": {
    "search": {
      "command": "python",
      "args": [
        "application/mcp-server.py"
      ]
    }
  }
}
```

아래는 multiple mcp server를 설정시 config 입니다.

```python
{
   "mcpServers":{
      "RAG":{
         "command":"python",
         "args":[
            "application/mcp-server.py"
         ]
      },
      "mcp-tavily":{
         "command":"npx",
         "args":[
            "-y",
            "@smithery/cli@latest",
            "run",
            "mcp-tavily",
            "--key",
            "132c5abd-6f2e-4e42-89a1-d0b1fcb75613"
         ]
      }
   }
}
```

이 정보를 아래와 같이 왼쪽 메뉴의 MCP Config에 복사합니다.

<img src="https://github.com/user-attachments/assets/0e054f8e-4356-42e0-a70e-636af8d377c8" width="300">


이후 메뉴에서 "Agent"를 선택후에 아래와 같이 "강남역 맛집은?"라고 입력후 결과를 확인합니다.

<img src="https://github.com/user-attachments/assets/8275bf94-2f46-475d-9eea-02568e70199b" width="650">

### AWS Cost Analysis

"지난 한달간의 AWS 비용을 요약해주세요." 입력후에 결과를 확인합니다.

<img src="https://github.com/user-attachments/assets/5794def3-47fd-498f-8074-0d970bee1c99" width="650">


### 이미지 생성

왼쪽 메뉴에서 Agent를 선택하고, MCP config로 "image generation"을 선택한 후에 "노을이 지는 아름다운 강변을 달리기하는 사람을 그려주세요."라고 입력 후에 결과를 확인합니다.

<img src="https://github.com/user-attachments/assets/a4147b0f-86d2-4042-83bb-9c9b61e51a2f" width="650">

### AWS Architecture 그리기

메뉴에서 "Agent(Chat)"를 선택하고 MCP로 "aws diagram"를 고른 후, "Amazon S3로 web hosting을 하기 위한 architecture를 추천해주세요."와 "Cognito를 이용해 인증할수 있도록 해주세요."으로 순차적으로 명령을 하면 아래와 같은 결과를 얻을 수 있습니다.

![noname](https://github.com/user-attachments/assets/04191a61-746f-4852-ad2a-e77b6af7cedc)

### Code Interpreter의 활용

"strawberry의 r의 갯수는?"로 질문하면 아래와 같이 Tools 리스트에서 "repl_coder"가 선택되어 활용됩니다.

<img src="https://github.com/user-attachments/assets/2575d4b1-8871-4677-a982-82d60ec6036a" width="650">

### Storage

Tool에서 "aws storage"를 선택하고, "내 s3 전체 사용량은?"이라고 질문합니다. 이때의 결과는 아래와 같습니다. 

<img src="https://github.com/user-attachments/assets/a9e41d68-6a2a-4cda-a264-58cc3124f51d" width="650">

"내 aws strorage 사용량은?"이라고 질문하면, S3, EFS, EBS의 용량을 확인하여 아래와 같이 답변할 수 있습니다.

<img src="https://github.com/user-attachments/assets/4c390cee-fd91-487e-ba0d-8b99fd7389ae" width="650">

## Reference 

[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

[Using MCP with LangGraph agents](https://www.youtube.com/watch?v=OX89LkTvNKQ)

[MCP From Scratch](https://mirror-feeling-d80.notion.site/MCP-From-Scratch-1b9808527b178040b5baf83a991ed3b2)

[Understanding MCP From Scratch](https://www.youtube.com/watch?v=CDjjaTALI68)

[LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)


["Vibe Coding" LangGraph apps with llms.txt and MCP](https://www.youtube.com/watch?v=fk2WEVZfheI)

[MCP LLMS-TXT Documentation Server](https://github.com/langchain-ai/mcpdoc)



[MCP - For Server Developers](https://modelcontextprotocol.io/quickstart/server)

[Model Context Protocol (MCP) and Amazon Bedrock](https://community.aws/content/2uFvyCPQt7KcMxD9ldsJyjZM1Wp/model-context-protocol-mcp-and-amazon-bedrock)

[Model Context Protocol servers](https://github.com/modelcontextprotocol/servers)

[Langchain.js MCP Adapter](https://www.linkedin.com/posts/langchain_mcp-adapters-released-introducing-our-activity-7308925375160467457-_BPL/?utm_source=share&utm_medium=member_android&rcm=ACoAAA5jTp0BX-JuOkof3Ak56U3VlXjQVT43NzQ)

[Using LangChain With Model Context Protocol (MCP)](https://cobusgreyling.medium.com/using-langchain-with-model-context-protocol-mcp-e89b87ee3c4c)

  
[Desktop Commander MCP](https://github.com/wonderwhy-er/DesktopCommanderMCP)

[Smithery](https://smithery.ai/)

[Cursor AI 말고, 나만의 #MCP 에이전트 앱 만들어 보기!](https://www.youtube.com/watch?v=ISrYHGg2C2c)

[The Top 7 MCP-Supported AI Frameworks](https://medium.com/@amosgyamfi/the-top-7-mcp-supported-ai-frameworks-a8e5030c87ab)

[Drug Discovery Agent based on Amazon Bedrock](https://github.com/hsr87/drug-discovery-agent)

[Price Per Token](https://pricepertoken.com/)

[Claude Code Subagents Collection](https://github.com/wshobson/agents)


[Claude Code Subagents Collection](https://github.com/wshobson/agents)
