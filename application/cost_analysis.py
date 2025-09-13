import boto3
import utils
import json
import pandas as pd
import plotly.express as px
import traceback
import chat
import os
from datetime import datetime, timedelta
from langchain_core.prompts import ChatPromptTemplate

import logging
import sys
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

def get_cost_analysis(days: str=30):
    """Cost analysis data collection"""
    logger.info(f"Getting cost analysis...")
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # cost explorer
        if aws_access_key and aws_secret_key:
            ce = boto3.client('ce',
                region_name=aws_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                aws_session_token=aws_session_token,
            )
        else:
            ce = boto3.client('ce')

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
        # logger.info(f"Service Cost: {service_response}")
        
        service_costs = pd.DataFrame([
            {
                'SERVICE': group['Keys'][0],
                'cost': float(group['Metrics']['UnblendedCost']['Amount'])
            }
            for group in service_response['ResultsByTime'][0]['Groups']
        ])
        logger.info(f"Service Costs: {service_costs}")
        
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
        # logger.info(f"Region Cost: {region_response}")
        
        region_costs = pd.DataFrame([
            {
                'REGION': group['Keys'][0],
                'cost': float(group['Metrics']['UnblendedCost']['Amount'])
            }
            for group in region_response['ResultsByTime'][0]['Groups']
        ])
        logger.info(f"Region Costs: {region_costs}")
        
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
        # logger.info(f"Daily Cost: {daily_response}")
        
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
        
        return {
            'service_costs': service_costs,
            'region_costs': region_costs,
            'daily_costs': daily_costs_df
        }
        
    except Exception as e:
        logger.info(f"Error in cost analysis: {str(e)}")
        return None

def create_cost_visualizations(cost_data):
    """Cost Visualization"""
    logger.info("Creating cost visualizations...")

    if not cost_data:
        logger.info("No cost data available")
        return None
        
    visualizations = {}
    
    # service cost (pie chart)
    fig_pie = px.pie(
        cost_data['service_costs'],
        values='cost',
        names='SERVICE',
        title='Service Cost'
    )
    visualizations['service_pie'] = fig_pie
            
    # daily trend cost (line chart)
    fig_line = px.line(
        cost_data['daily_costs'],
        x='date',
        y='cost',
        color='SERVICE',
        title='Daily Cost Trend'
    )
    visualizations['daily_trend'] = fig_line
    
    # region cost (bar chart)
    fig_bar = px.bar(
        cost_data['region_costs'],
        x='REGION',
        y='cost',
        title='Region Cost'
    )
    visualizations['region_bar'] = fig_bar
    
    logger.info(f"Visualizations created: {list(visualizations.keys())}")
    return visualizations

def generate_cost_insights():
    if cost_data:
        cost_data_dict = {
            'service_costs': cost_data['service_costs'].to_dict(orient='records'),
            'region_costs': cost_data['region_costs'].to_dict(orient='records'),
            'daily_costs': cost_data['daily_costs'].to_dict(orient='records') if 'daily_costs' in cost_data else []
        }
    else:
        return "Not available"

    system = (
        "당신의 AWS solutions architect입니다."
        "다음의 Cost Data을 이용하여 user의 질문에 답변합니다."
        "모르는 질문을 받으면 솔직히 모른다고 말합니다."
        "답변의 이유를 풀어서 명확하게 설명합니다."
    )
    human = (
        "다음 AWS 비용 데이터를 분석하여 상세한 인사이트를 제공해주세요:"
        "Cost Data:"
        "{raw_cost}"
        
        "다음 항목들에 대해 분석해주세요:"
        "1. 주요 비용 발생 요인"
        "2. 비정상적인 패턴이나 급격한 비용 증가"
        "3. 비용 최적화가 가능한 영역"
        "4. 전반적인 비용 추세와 향후 예측"
        
        "분석 결과를 다음과 같은 형식으로 제공해주세요:"

        "### 주요 비용 발생 요인"
        "- [구체적인 분석 내용]"

        "### 이상 패턴 분석"
        "- [비정상적인 비용 패턴 설명]"

        "### 최적화 기회"
        "- [구체적인 최적화 방안]"

        "### 비용 추세"
        "- [추세 분석 및 예측]"
    ) 

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # logger.info('prompt: ', prompt)    

    llm = chat.get_chat(extended_thinking="Disable")
    chain = prompt | llm

    raw_cost = json.dumps(cost_data_dict)

    try:
        response = chain.invoke(
            {
                "raw_cost": raw_cost
            }
        )
        logger.info(f"response: {response.content}")

    except Exception:
        err_msg = traceback.format_exc()
        logger.debug(f"error message: {err_msg}")                    
        raise Exception ("Not able to request to LLM")
    
    return response.content

cost_data = {}
visualizations = {}
insights = ""

def get_visualiation():
    global cost_data, visualizations

    try:
        cost_data = get_cost_analysis()
        if cost_data:
            logger.info(f"No cost data available")

            # draw visualizations        
            visualizations = create_cost_visualizations(cost_data)

    except Exception as e:
        logger.info(f"Error to earn cost data: {str(e)}")   

def ask_cost_insights(question):
    if cost_data:
        cost_data_dict = {
            'service_costs': cost_data['service_costs'].to_dict(orient='records'),
            'region_costs': cost_data['region_costs'].to_dict(orient='records'),
            'daily_costs': cost_data['daily_costs'].to_dict(orient='records') if 'daily_costs' in cost_data else []
        }
    else:
        return "Cost 데이터를 가져오는데 실패하였습니다."

    system = (
        "당신의 AWS solutions architect입니다."
        "다음의 Cost Data을 이용하여 user의 질문에 답변합니다."
        "모르는 질문을 받으면 솔직히 모른다고 말합니다."
        "답변의 이유를 풀어서 명확하게 설명합니다."
    )
    human = (
        "Question: {question}"

        "Cost Data:"
        "{raw_cost}"        
    ) 

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # logger.info('prompt: ', prompt)    

    llm = chat.get_chat()
    chain = prompt | llm

    raw_cost = json.dumps(cost_data_dict)

    try:
        response = chain.invoke(
            {
                "question": question,
                "raw_cost": raw_cost
            }
        )
        logger.info(f"response: {response.content}")

    except Exception:
        err_msg = traceback.format_exc()
        logger.debug(f"error message: {err_msg}")                    
        raise Exception ("Not able to request to LLM")
    
    return response.content
