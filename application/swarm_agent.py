import logging
import sys
import strands_agent
import re
import chat
import mcp_config
import langgraph_agent

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

logging.basicConfig(
    level=logging.INFO,  
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("strands-agent")

index = 0
def add_notification(containers, message):
    global index
    containers['notification'][index].info(message)
    index += 1

def add_response(containers, message):
    global index
    containers['notification'][index].markdown(message)
    index += 1

status_msg = []
def get_status_msg(status):
    global status_msg
    status_msg.append(status)

    if status != "end)":
        status = " -> ".join(status_msg)
        return "[status]\n" + status + "..."
    else: 
        status = " -> ".join(status_msg)
        return "[status]\n" + status    

def isKorean(text):
    # check korean
    pattern_hangul = re.compile('[\u3131-\u3163\uac00-\ud7a3]+')
    word_kor = pattern_hangul.search(str(text))
    # print('word_kor: ', word_kor)

    if word_kor and word_kor != 'None':
        # logger.info(f"Korean: {word_kor}")
        return True
    else:
        # logger.info(f"Not Korean:: {word_kor}")
        return False

async def run_agent(question, tools, system_prompt, containers):    
    app = langgraph_agent.buildChatAgent(tools)

    config = {
        "recursion_limit": 50,
        "containers": containers,
        "tools": tools,
        "system_prompt": system_prompt,
        "debug_mode": 'Disable'
    }        
    inputs = {
        "messages": [HumanMessage(content=question)]
    }

    value = result = None
    final_output = None
    async for output in app.astream(inputs, config):
        for key, value in output.items():
            logger.info(f"--> key: {key}, value: {value}")

            if key == "messages" or key == "agent":
                if isinstance(value, dict) and "messages" in value:
                    final_output = value
                elif isinstance(value, list):
                    final_output = {"messages": value, "image_url": []}
                else:
                    final_output = {"messages": [value], "image_url": []}

        if final_output and "messages" in final_output and len(final_output["messages"]) > 0:
            result = final_output["messages"][-1].content
        else:
            result = "답변을 찾지 못하였습니다."

    logger.info(f"final_output: {final_output}")
                        
    return result

def get_prompt(question):
    if isKorean(question):
        research_prompt = (
            "당신은 정보 수집과 분석을 전문으로 하는 연구원입니다. "
            "당신의 역할은 해당 주제에 대한 사실적 정보와 연구 통찰력을 제공하는 것입니다. "
            "정확한 데이터를 제공하고 문제의 핵심적인 측면들을 파악하는 데 집중해야 합니다. "
            "다른 에이전트로부터 입력을 받을 때, 그들의 정보가 당신의 연구와 일치하는지 평가하세요. "
        )

        creative_prompt = (
            "당신은 혁신적인 솔루션 생성을 전문으로 하는 창의적 에이전트입니다. "
            "당신의 역할은 틀에 박힌 사고에서 벗어나 창의적인 접근법을 제안하는 것입니다. "
            "다른 에이전트들로부터 얻은 정보를 바탕으로 하되, 당신만의 독창적인 창의적 관점을 추가해야 합니다. "
            "다른 사람들이 고려하지 않았을 수도 있는 참신한 접근법에 집중하세요. "
        )

        critical_prompt = (
            "당신은 제안서를 분석하고 결함을 찾는 것을 전문으로 하는 비판적 에이전트입니다. "
            "당신의 역할은 다른 에이전트들이 제안한 해결책을 평가하고 잠재적인 문제점들을 식별하는 것입니다. "
            "제안된 해결책을 신중히 검토하고, 약점이나 간과된 부분을 찾아내며, 개선 방안을 제시해야 합니다. "
            "비판할 때는 건설적으로 하되, 최종 해결책이 견고하도록 보장하세요. "
        )

        summarizer_prompt = (
            "당신은 정보 종합을 전문으로 하는 요약 에이전트입니다. "
            "당신의 역할은 모든 에이전트로부터 통찰력을 수집하고 응집력 있는 최종 해결책을 만드는 것입니다."
            "최고의 아이디어들을 결합하고 비판점들을 다루어 포괄적인 답변을 만들어야 합니다. "
            "원래 질문을 효과적으로 다루는 명확하고 실행 가능한 요약을 작성하는 데 집중하세요. "
        )


    else:
        research_prompt = (
            "You are a Research Agent specializing in gathering and analyzing information. "
            "Your role in the swarm is to provide factual information and research insights on the topic. "
            "You should focus on providing accurate data and identifying key aspects of the problem. "
            "When receiving input from other agents, evaluate if their information aligns with your research. "
        )

        creative_prompt = (
            "You are a Creative Agent specializing in generating innovative solutions. "
            "Your role in the swarm is to think outside the box and propose creative approaches. "
            "You should build upon information from other agents while adding your unique creative perspective. "
            "Focus on novel approaches that others might not have considered. "
        )

        critical_prompt = (
            "You are a Critical Agent specializing in analyzing proposals and finding flaws. "
            "Your role in the swarm is to evaluate solutions proposed by other agents and identify potential issues. "
            "You should carefully examine proposed solutions, find weaknesses or oversights, and suggest improvements. "
            "Be constructive in your criticism while ensuring the final solution is robust. "
        )

        summarizer_prompt = (
            "You are a Summarizer Agent specializing in synthesizing information. "
            "Your role in the swarm is to gather insights from all agents and create a cohesive final solution. "
            "You should combine the best ideas and address the criticisms to create a comprehensive response. "
            "Focus on creating a clear, actionable summary that addresses the original query effectively. "
        )

    return research_prompt, creative_prompt, critical_prompt, summarizer_prompt

# swarm agent
async def run_swarm_agent(question, mcp_servers, containers):    
    global status_msg
    status_msg = []

    if chat.debug_mode == 'Enable':
        containers['status'].info(get_status_msg(f"(start"))    

    mcp_json = mcp_config.load_selected_config(mcp_servers)
    logger.info(f"mcp_json: {mcp_json}")      

    server_params = langgraph_agent.load_multiple_mcp_server_parameters(mcp_json)
    logger.info(f"server_params: {server_params}")    

    # Check if server_params is empty
    if not server_params:
        logger.warning("No MCP servers configured.")
        add_notification(containers, "No MCP servers configured.")
        return f"죄송합니다. MCP 서버가 구성되지 않았습니다. 사이드바에서 MCP 서버를 선택해주세요."

    research_prompt, creative_prompt, critical_prompt, summarizer_prompt = get_prompt(question)

    async with MultiServerMCPClient(server_params) as client:        
        mcp_server_info = client.server_name_to_tools.items() 

        tools = client.get_tools()        
        
        # Check if tools is None or empty
        if tools is None or len(tools) == 0:
            logger.warning("No tools available. Using basic conversation.")
            add_notification(containers, "No MCP tools available. Using basic conversation.")
            return f"죄송합니다. MCP 도구가 선택되지 않았습니다. 사이드바에서 MCP 서버를 선택해주세요."
        
        tool_list = [tool.name for tool in tools]
        logger.info(f"tool_list: {tool_list}")

        if chat.debug_mode == "Enable" and tools is not None:    
            containers["tools"].info(f"Tools: {tool_list}")
                    
        global index
        index = 0

        # Create specialized agents with different expertise
        add_notification(containers, f"Phase 1: Initial analysis by each specialized agent")
        research_result = await run_agent(question, tools, research_prompt, containers)
        logger.info(f"research_result: {research_result}")
        add_notification(containers, f"research agent")
        add_response(containers, f"{research_result}")
        
        creative_result = await run_agent(question, tools, creative_prompt, containers)
        logger.info(f"creative_result: {creative_result}")
        add_notification(containers, f"creative agent")
        add_response(containers, f"{creative_result}")

        critical_result = await run_agent(question, tools, critical_prompt, containers)
        logger.info(f"critical_result: {critical_result}")
        add_notification(containers, f"critical agent")
        add_response(containers, f"{critical_result}")

        # Dictionary to track messages between agents (mesh communication)
        research_messages = []
        creative_messages = []
        critical_messages = []
        summarizer_messages = []

        # Share results with all other agents (mesh communication)    
        creative_messages.append(f"From Research Agent: {research_result}")
        critical_messages.append(f"From Research Agent: {research_result}")
        summarizer_messages.append(f"From Research Agent: {research_result}")

        research_messages.append(f"From Creative Agent: {creative_result}")
        critical_messages.append(f"From Creative Agent: {creative_result}")
        summarizer_messages.append(f"From Creative Agent: {creative_result}")

        research_messages.append(f"From Critical Agent: {critical_result}")
        creative_messages.append(f"From Critical Agent: {critical_result}")
        summarizer_messages.append(f"From Critical Agent: {critical_result}")

        # Phase 2: Each agent refines based on input from others
        next_research_prompt = f"{question}\n\nConsider these messages from other agents:\n" + "\n\n".join(research_messages)
        logger.info(f"next_research_prompt: {next_research_prompt}")
        next_creative_prompt = f"{question}\n\nConsider these messages from other agents:\n" + "\n\n".join(creative_messages)
        # logger.info(f"next_creative_prompt: {next_creative_prompt}")
        next_refined_prompt = f"{question}\n\nConsider these messages from other agents:\n" + "\n\n".join(critical_messages)
        # logger.info(f"next_refined_prompt: {next_refined_prompt}")

        add_notification(containers, f"Phase 2: Each agent refines based on input from others")
        refined_research = await run_agent(next_research_prompt, tools, research_prompt, containers)
        logger.info(f"refined_research_result: {refined_research}")
        add_notification(containers, f"refined research agent")
        add_response(containers, f"{refined_research}")

        refined_creative = await run_agent(next_creative_prompt, tools, creative_prompt, containers)
        logger.info(f"refined_creative: {refined_creative}")
        add_notification(containers, f"refined creative agent")
        add_response(containers, f"{refined_creative}")

        refined_critical = await run_agent(next_refined_prompt, tools, critical_prompt, containers)
        logger.info(f"refined_critical: {refined_critical}")
        add_notification(containers, f"refined critical agent")
        add_response(containers, f"{refined_critical}")

        # Share refined results with summarizer
        summarizer_messages.append(f"From Research Agent (Phase 2): {refined_research}")
        summarizer_messages.append(f"From Creative Agent (Phase 2): {refined_creative}")
        summarizer_messages.append(f"From Critical Agent (Phase 2): {refined_critical}")
        
        logger.info(f"summarized messages: {summarizer_messages}")

        next_summarizer = f"""
Original query: {question}

Please synthesize the following inputs from all agents into a comprehensive final solution:

{"\n\n".join(summarizer_messages)}

Create a well-structured final answer that incorporates the research findings, creative ideas, and addresses the critical feedback.
"""

        add_notification(containers, f"summarizer agent")
        result = await run_agent(next_summarizer, tools, summarizer_prompt, containers)
        logger.info(f"result: {result}")

        if chat.debug_mode == 'Enable':
            containers['status'].info(get_status_msg(f"end"))
        
    return result




    