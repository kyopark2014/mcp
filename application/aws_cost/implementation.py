"""This file was generated using `langgraph-gen` version 0.0.3.

This file provides a placeholder implementation for the corresponding stub.

Replace the placeholder implementation with your own logic.
"""

from typing_extensions import TypedDict

from aws_cost.stub import CostAgent

from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from datetime import datetime, timedelta
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.constants import START, END
from langchain_core.runnables.graph import CurveStyle, MermaidDrawMethod, NodeStyles
from pydantic import BaseModel, Field

import pandas as pd
import plotly.express as px
import plotly.io as pio
import boto3
import logging
import sys
import base64
import random
import chat
import os
import json
import traceback
import asyncio
import aws_cost.reflection_agent as reflection_agent

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("cost_analysis")

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

def get_url(figure, prefix):
    # Convert fig_pie to base64 image
    img_bytes = pio.to_image(figure, format="png")
    base64_image = base64.b64encode(img_bytes).decode('utf-8')

    random_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
    image_filename = f'{prefix}_{random_id}.png'
    
    # Convert base64 string back to bytes for S3 upload
    image_bytes = base64.b64decode(base64_image)
    url = chat.upload_to_s3(image_bytes, image_filename)
    logger.info(f"Uploaded image to S3: {url}")
    
    return url

def get_prompt_template(prompt_name: str) -> str:
    template = open(os.path.join(os.path.dirname(__file__), f"{prompt_name}.md")).read()
    # logger.info(f"template: {template}")
    return template

def get_summary(figure, instruction):
    img_bytes = pio.to_image(figure, format="png")
    base64_image = base64.b64encode(img_bytes).decode('utf-8')
    
    summary = chat.summary_image(base64_image, instruction)

    summary = summary.split("<result>")[1].split("</result>")[0]
    logger.info(f"summary: {summary}")

    return summary

# Reflection
class Reflection(BaseModel):
    missing: str = Field(description="Critique of what is missing.")
    advisable: str = Field(description="Critique of what is helpful for better answer")
    superfluous: str = Field(description="Critique of what is superfluous")

class Research(BaseModel):
    """Provide reflection and then follow up with search queries to improve the answer."""

    reflection: Reflection = Field(description="Your reflection on the initial answer.")
    search_queries: list[str] = Field(
        description="1-3 search queries for researching improvements to address the critique of your current answer."
    )
    
def reflect(draft):
    logger.info(f"###### reflect ######")

    reflection = []
    search_queries = []
    for attempt in range(5):
        llm = chat.get_chat(extended_thinking="Disable")
        structured_llm = llm.with_structured_output(Research, include_raw=True)
        
        info = structured_llm.invoke(draft)
        logger.info(f'attempt: {attempt}, info: {info}')
            
        if not info['parsed'] == None:
            parsed_info = info['parsed']
            reflection = [parsed_info.reflection.missing, parsed_info.reflection.advisable]
            logger.info(f"reflection: {reflection}")
            search_queries = parsed_info.search_queries
            logger.info(f"search_queries: {search_queries}")            
            break
    
    return {
        "reflection": reflection,
        "search_queries": search_queries
    }

def revise_draft(draft, context):   
    logger.info(f"###### revise_draft ######")
        
    system = (
        "당신은 보고서를 잘 작성하는 논리적이고 똑똑한 AI입니다."
        "당신이 작성하여야 할 보고서 <draft>의 소제목과 기본 포맷을 유지한 상태에서, 다음의 <context>의 내용을 추가합니다."
        "초등학생도 쉽게 이해하도록 풀어서 씁니다."
    )
    human = (
        "<draft>{draft}</draft>"
        "<context>{context}</context>"
    )
                
    reflection_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("human", human)
        ]
    )        
    reflect = reflection_prompt | chat.get_chat(extended_thinking="Disable")
        
    result = reflect.invoke({
        "draft": draft,
        "context": context
    })   
    logger.info(f"result: {result.content}")
                            
    return result.content
    
#########################################################
# Cost Agent
#########################################################
class CostState(TypedDict):
    service_costs: dict
    region_costs: dict
    daily_costs: dict
    additional_context: list[str]
    appendix: list[str]
    iteration: int
    reflection: list[str]
    final_response: str

# Define stand-alone functions
status_msg = []
def get_status_msg(status):
    global status_msg
    status_msg.append(status)

    if status != "end":
        status = " -> ".join(status_msg)
        return "[status]\n" + status + "..."
    else: 
        status = " -> ".join(status_msg)
        return "[status]\n" + status

response_msg = []

def service_cost(state: CostState, config) -> dict:
    logger.info(f"###### service_cost ######")

    logger.info(f"Getting cost analysis...")
    days = 30

    request_id = config.get("configurable", {}).get("request_id", "")
    status_container = config.get("configurable", {}).get("status_container", None)
    response_container = config.get("configurable", {}).get("response_container", None)

    try:
        if status_container:
            status_container.info(get_status_msg("service_cost"))

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # cost explorer
        if aws_access_key and aws_secret_key:
            ce = boto3.client(
                service_name='ce',
                aws_access_key_id=aws_access_key, 
                aws_secret_access_key=aws_secret_key, 
                aws_session_token=aws_session_token
            )
        else:
            ce = boto3.client(
                service_name='ce'
            )

        # service cost
        service_response = ce.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
        )
        logger.info(f"service_response: {service_response}")

    except Exception as e:
        logger.info(f"Error in cost analysis: {str(e)}")
        return None
    
    service_costs = pd.DataFrame([
        {
            'SERVICE': group['Keys'][0],
            'cost': float(group['Metrics']['UnblendedCost']['Amount'])
        }
        for group in service_response['ResultsByTime'][0]['Groups']
    ])
    logger.info(f"Service Costs: {service_costs}")

    if response_container:
        value = service_costs.to_string()
        response_container.info('[response]\n' + value[:800])
        response_msg.append(value[:800])
    
    # service cost (pie chart)
    fig_pie = px.pie(
        service_costs,
        values='cost',
        names='SERVICE',
        color='SERVICE',
        title='Service Cost',
        template='plotly_white',  # Clean background
        color_discrete_sequence=px.colors.qualitative.Set3  # Color palette
    )    

    url = get_url(fig_pie, "service_cost")

    task = "AWS 서비스 사용량"
    output_images = f"![{task} 그래프]({url})\n\n"

    key = f"artifacts/{request_id}_steps.md"
    time = f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

    instruction = f"이 이미지는 {task}에 대한 그래프입니다. 하나의 문장으로 이 그림에 대해 500자로 설명하세요."
    summary = get_summary(fig_pie, instruction)

    body = f"## {task}\n\n{output_images}\n\n{summary}\n\n"
    chat.updata_object(key, time + body, 'append')

    if response_container:
        value = summary
        response_container.info('[response]\n' + value[:200])
        response_msg.append(value[:200])

    appendix = state["appendix"] if "appendix" in state else []
    appendix.append(body)

    return {
        "appendix": appendix,
        "service_costs": service_response,
    }

def region_cost(state: CostState, config) -> dict:
    logger.info(f"###### region_cost ######")

    logger.info(f"Getting cost analysis...")
    days = 30

    request_id = config.get("configurable", {}).get("request_id", "")
    status_container = config.get("configurable", {}).get("status_container", None)
    response_container = config.get("configurable", {}).get("response_container", None)
    
    try:
        if status_container:
            status_container.info(get_status_msg("region_cost"))

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # cost explorer
        if aws_access_key and aws_secret_key:
            ce = boto3.client(
                service_name='ce',
                aws_access_key_id=aws_access_key, 
                aws_secret_access_key=aws_secret_key, 
                aws_session_token=aws_session_token
            )
        else:
            ce = boto3.client(
                service_name='ce'
            )

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
        logger.info(f"region_response: {region_response}")
    
    except Exception as e:
        logger.info(f"Error in cost analysis: {str(e)}")
        return None
    
    region_costs = pd.DataFrame([
        {
            'REGION': group['Keys'][0],
            'cost': float(group['Metrics']['UnblendedCost']['Amount'])
        }
        for group in region_response['ResultsByTime'][0]['Groups']
    ])
    logger.info(f"Region Costs: {region_costs}")

    if response_container:
        value = region_costs.to_string()
        response_container.info('[response]\n' + value[:800])
        response_msg.append(value[:800])

    # region cost (bar chart)
    fig_bar = px.bar(
        region_costs,
        x='REGION',
        y='cost',
        color='REGION',
        title='Region Cost',
        template='plotly_white',  # Clean background
        color_discrete_sequence=px.colors.qualitative.Set3  # Color palette
    )
    url = get_url(fig_bar, "region_costs")
    task = "AWS 리전별 사용량"
    output_images = f"![{task} 그래프]({url})\n\n"

    key = f"artifacts/{request_id}_steps.md"
    time = f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

    instruction = f"이 이미지는 {task}에 대한 그래프입니다. 하나의 문장으로 이 그림에 대해 500자로 설명하세요. 여기서 비용 단위는 dollar 입니다."
    summary = get_summary(fig_bar, instruction)

    body = f"## {task}\n\n{output_images}\n\n{summary}\n\n"
    chat.updata_object(key, time + body, 'append')

    if response_container:
        value = body
        response_container.info('[response]\n' + time + body[:200])
        response_msg.append(time + value[:200])

    appendix = state["appendix"] if "appendix" in state else []
    appendix.append(body)

    return {
        "appendix": appendix,
        "region_costs": region_response
    }

def daily_cost(state: CostState, config) -> dict:
    logger.info(f"###### daily_cost ######")
    logger.info(f"Getting cost analysis...")
    days = 30

    request_id = config.get("configurable", {}).get("request_id", "")
    status_container = config.get("configurable", {}).get("status_container", None)
    response_container = config.get("configurable", {}).get("response_container", None)
    
    try:
        if status_container:
            status_container.info(get_status_msg("daily_cost"))

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # cost explorer
        if aws_access_key and aws_secret_key:
            ce = boto3.client(
                service_name='ce',
                aws_access_key_id=aws_access_key, 
                aws_secret_access_key=aws_secret_key, 
                aws_session_token=aws_session_token
            )
        else:
            ce = boto3.client(
                service_name='ce'
            )

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
        logger.info(f"Daily Cost: {daily_response}")
    
    except Exception as e:
        logger.info(f"Error in cost analysis: {str(e)}")
        return None
    
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
    logger.info(f"Daily Costs: {daily_costs_df}")

    if response_container:
        value = daily_costs_df.to_string()
        response_container.info('[response]\n' + value[:800])
        response_msg.append(value[:800])

    # daily trend cost (line chart)
    fig_line = px.line(
        daily_costs_df,
        x='date',
        y='cost',
        color='SERVICE',
        title='Daily Cost Trend',
        template='plotly_white',  # Clean background
        markers=True,  # Add markers to data points
        line_shape='spline'  # Smooth curve display
    )
    url = get_url(fig_line, "daily_costs")
    
    task = "AWS 일자별 사용량"
    output_images = f"![{task} 그래프]({url})\n\n"

    key = f"artifacts/{request_id}_steps.md"
    time = f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

    instruction = f"이 이미지는 {task}에 대한 그래프입니다. 하나의 문장으로 이 그림에 대해 500자로 설명하세요. 여기서 비용 단위는 dollar 입니다."
    summary = get_summary(fig_line, instruction)

    body = f"## {task}\n\n{output_images}\n\n{summary}\n\n"
    chat.updata_object(key, time + body, 'append')

    if response_container:
        value = body
        response_container.info('[response]\n' + value[:200])
        response_msg.append(value[:200])

    appendix = state["appendix"] if "appendix" in state else []
    appendix.append(body)

    return {
        "appendix": appendix,
        "daily_costs": daily_response
    }

def generate_insight(state: CostState, config) -> dict:
    logger.info(f"###### generate_insight ######")

    prompt_name = "cost_insight"
    request_id = config.get("configurable", {}).get("request_id", "")    
    additional_context = state["additional_context"] if "additional_context" in state else []
    status_container = config.get("configurable", {}).get("status_container", None)
    response_container = config.get("configurable", {}).get("response_container", None)
    
    system_prompt=get_prompt_template(prompt_name)
    logger.info(f"system_prompt: {system_prompt}")

    human = (
        "다음 AWS 비용 데이터를 분석하여 상세한 인사이트를 제공해주세요:"
        "Cost Data:"
        "<service_costs>{service_costs}</service_costs>"
        "<region_costs>{region_costs}</region_costs>"
        "<daily_costs>{daily_costs}</daily_costs>"

        "다음의 additional_context는 관련된 다른 보고서입니다. 이 보고서를 현재 작성하는 보고서에 추가해주세요. 단, 전체적인 문맥에 영향을 주면 안됩니다."
        "<additional_context>{additional_context}</additional_context>"
    )

    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", human)])
    # logger.info(f'prompt: {prompt}')    

    llm = chat.get_chat(extended_thinking="Disable")
    chain = prompt | llm

    service_costs = json.dumps(state["service_costs"])
    region_costs = json.dumps(state["region_costs"])
    daily_costs = json.dumps(state["daily_costs"])

    try:
        if status_container:
            status_container.info(get_status_msg('generate_insight'))
            
        response = chain.invoke(
            {
                "service_costs": service_costs,
                "region_costs": region_costs,
                "daily_costs": daily_costs,
                "additional_context": additional_context
            }
        )
        logger.info(f"response: {response.content}")
        
    except Exception:
        err_msg = traceback.format_exc()
        logger.debug(f"error message: {err_msg}")                    
        raise Exception ("Not able to request to LLM")
    
    # logging in step.md
    key = f"artifacts/{request_id}_steps.md"
    time = f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    chat.updata_object(key, time + response.content, 'append')
    
    # report.md
    key = f"artifacts/{request_id}_report.md"
    body = "# AWS 사용량 분석\n\n" + response.content + "\n\n"  

    appendix = state["appendix"] if "appendix" in state else []
    values = '\n\n'.join(appendix)

    logger.info(f"body: {body}")
    chat.updata_object(key, time+body+values, 'prepend')

    if response_container:
        value = response.content
        response_container.info('[response]\n' + value[:500])
        response_msg.append(value[:500])

    iteration = state["iteration"] if "iteration" in state else 0

    return {
        "final_response": body+values,
        "iteration": iteration+1
    }

def reflect_context(state: CostState, config) -> dict:
    logger.info(f"###### reflect_context ######")

    status_container = config.get("configurable", {}).get("status_container", None)
    response_container = config.get("configurable", {}).get("response_container", None)
    
    if status_container:
        status_container.info(get_status_msg("reflect_context"))

    # earn reflection from the previous final response    
    result = reflect(state["final_response"])
    logger.info(f"reflection result: {result}")

    # logging in step.md
    request_id = config.get("configurable", {}).get("request_id", "")
    key = f"artifacts/{request_id}_steps.md"
    time = f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"    
    body = f"Reflection: {result['reflection']}\n\nSearch Queries: {result['search_queries']}\n\n"
    chat.updata_object(key, time + body, 'append')

    if response_container:
        value = body
        response_container.info('[response]\n' + value[:500])
        response_msg.append(value[:500])

    return {
        "reflection": result
    }

def mcp_tools(state: CostState, config) -> dict:
    logger.info(f"###### mcp_tools ######")
    draft = state['final_response']

    status_container = config.get("configurable", {}).get("status_container", None)
    response_container = config.get("configurable", {}).get("response_container", None)
    key_container = config.get("configurable", {}).get("key_container", None)
    mcp_servers = config.get("configurable", {}).get("mcp_servers", None)

    appendix = state["appendix"] if "appendix" in state else []

    if status_container:
        status_container.info(get_status_msg("mcp_tools"))

    global status_msg, response_msg 
    reflection_result, image_url, status_msg, response_msg = asyncio.run(reflection_agent.run(draft, state["reflection"], mcp_servers, status_container, response_container, key_container, status_msg, response_msg))
    logger.info(f"reflection result: {reflection_result}")

    value = ""
    if image_url:
        for url in image_url:
            value += f"![image]({url})\n\n"
    if value:
        logger.info(f"value: {value}")
        appendix.append(value)
    
    # logging in step.md
    request_id = config.get("configurable", {}).get("request_id", "")
    key = f"artifacts/{request_id}_steps.md"
    time = f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"    
    body = f"{reflection_result}\n\n"
    value = '\n\n'.join(appendix)
    chat.updata_object(key, time + body + value, 'append')

    if response_container:
        value = body
        response_container.info('[response]\n' + value[:500])
        response_msg.append(value[:500])

    additional_context = state["additional_context"] if "additional_context" in state else []
    additional_context.append(reflection_result)

    return {
        "additional_context": additional_context
    }

def should_end(state: CostState, config) -> str:
    logger.info(f"###### should_end ######")
    iteration = state["iteration"] if "iteration" in state else 0
    status_container = config.get("configurable", {}).get("status_container", None)
    
    if iteration > config.get("configurable", {}).get("max_iteration", 1):
        logger.info(f"max iteration reached!")

        if chat.debug_mode == "Enable":
            status_container.info(get_status_msg("end"))
        next = END
    else:
        logger.info(f"additional information is required!")
        next = "reflect_context"

    return next

agent = CostAgent(
    state_schema=CostState,
    impl=[
        ("service_cost", service_cost),
        ("region_cost", region_cost),
        ("daily_cost", daily_cost),
        ("generate_insight", generate_insight),
        ("reflect_context", reflect_context),
        ("mcp_tools", mcp_tools),
        ("should_end", should_end),
    ],
)

cost_agent = agent.compile()

def run(request_id: str, mcp_servers: dict, status_container=None, response_container=None, key_container=None):
    logger.info(f"request_id: {request_id}")

    global status_msg
    status_msg = []

    # add plan to report
    key = f"artifacts/{request_id}_plan.md"
    
    status_container.info(get_status_msg("start"))
    
    # draw a graph
    graph_diagram = cost_agent.get_graph().draw_mermaid_png(
        draw_method=MermaidDrawMethod.API,
        curve_style=CurveStyle.LINEAR
    )    
    random_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
    image_filename = f'workflow_{random_id}.png'
    url = chat.upload_to_s3(graph_diagram, image_filename)
    
    # update plan.md
    task = "실행 계획"
    output_images = f"![{task}]({url})\n\n"
    body = f"## {task}\n\n{output_images}"
    chat.updata_object(key, body, 'prepend')

    # make a report
    question = "AWS 사용량을 분석하세요."        
    inputs = {
        "messages": [HumanMessage(content=question)],
        "final_response": ""
    }
    config = {
        "request_id": request_id,
        "recursion_limit": 50,
        "max_iteration": 1,
        "mcp_servers": mcp_servers,
        "status_container": status_container,
        "response_container": response_container,
        "key_container": key_container
    }

    value = None
    for output in cost_agent.stream(inputs, config):
        for key, value in output.items():
            logger.info(f"--> key: {key}, value: {value}")
            # if status_container:
            #     status_container.info(f"Currently running: {key}")
            # if response_container and value and "final_response" in value:
            #     response_container.write(value["final_response"])
    
    logger.info(f"value: {value}")

    return value["final_response"]