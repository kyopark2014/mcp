import json
import boto3
import logging
import sys
import base64
import chat
import pandas as pd
import plotly.express as px
import plotly.io as pio
import random
import traceback
import os
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-cost")

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

cost_data = {}
def normalize_service_name(service_name: str) -> str:
    """
    Normalize AWS service names to their official names
    Parameters:
        service_name: Input service name (e.g., 'S3', 'EC2')
    Returns:
        Normalized service name (e.g., 'Amazon S3', 'Amazon EC2')
    """
    service_mapping = {
        'S3': 'Amazon S3',
        'EC2': 'Amazon EC2',
        'RDS': 'Amazon RDS',
        'LAMBDA': 'AWS Lambda',
        'CLOUDWATCH': 'Amazon CloudWatch',
        'CLOUDFRONT': 'Amazon CloudFront',
        'DYNAMODB': 'Amazon DynamoDB',
        'SQS': 'Amazon SQS',
        'SNS': 'Amazon SNS',
        'EBS': 'Amazon EBS',
        'ELB': 'Elastic Load Balancing',
        'ECS': 'Amazon ECS',
        'EKS': 'Amazon EKS',
        'API GATEWAY': 'Amazon API Gateway',
        'ROUTE53': 'Amazon Route 53',
        'ELASTICACHE': 'Amazon ElastiCache',
        'REDSHIFT': 'Amazon Redshift',
        'SES': 'Amazon SES',
        'SNS': 'Amazon SNS',
        'SQS': 'Amazon SQS',
        'BEDROCK': 'Amazon Bedrock',
        'AMAZON BEDROCK': 'Amazon Bedrock',
        'SIMPLE STORAGE SERVICE': 'Amazon S3',
        'ELASTIC COMPUTE CLOUD': 'Amazon EC2',
        'RELATIONAL DATABASE SERVICE': 'Amazon RDS',
        'DYNAMO DB': 'Amazon DynamoDB',
        'SIMPLE QUEUE SERVICE': 'Amazon SQS',
        'SIMPLE NOTIFICATION SERVICE': 'Amazon SNS',
        'ELASTIC BLOCK STORE': 'Amazon EBS',
        'ELASTIC CONTAINER SERVICE': 'Amazon ECS',
        'ELASTIC KUBERNETES SERVICE': 'Amazon EKS',
        'SIMPLE EMAIL SERVICE': 'Amazon SES'
    }
    
    if not service_name:
        return None
        
    # Convert to uppercase for case-insensitive matching
    service_name = service_name.upper()
    
    # Check if the service name is in our mapping
    if service_name in service_mapping:
        return service_mapping[service_name]
    
    # If not found in mapping, return the original name
    return service_name

def get_service_cost(start_date: str, end_date: str, granularity: str = "MONTHLY", region: str="us-west-2"):
    """
    Get AWS service cost data
    Parameters:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        granularity: Granularity of the cost data (DAILY, MONTHLY, HOURLY)
        region: The region of aws infrastructure, e.g., us-west-2
    Returns:
        JSON containing service costs
    """
    try:
        # cost explorer
        if aws_access_key and aws_secret_key:
            ce = boto3.client(
                service_name='ce',
                region_name=region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                aws_session_token=aws_session_token,
            )
        else:
            ce = boto3.client(
                service_name='ce',
                region_name=region
            )

        service_response = ce.get_cost_and_usage(
            TimePeriod={
                'Start': start_date,
                'End': end_date
            },
            Granularity=granularity,
            Metrics=['UnblendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
        )
        
        # Convert response to JSON format
        service_costs = []
        for time_period in service_response['ResultsByTime']:
            period_data = {
                'time_period': time_period['TimePeriod'],
                'services': []
            }
            
            for group in time_period['Groups']:
                service_data = {
                    'service': group['Keys'][0],
                    'cost': float(group['Metrics']['UnblendedCost']['Amount']),
                    'unit': group['Metrics']['UnblendedCost']['Unit']
                }
                period_data['services'].append(service_data)
            
            service_costs.append(period_data)
            
        return {
            'service_costs': service_costs,
            'granularity': granularity,
            'time_period': {
                'start': start_date,
                'end': end_date
            }
        }

    except Exception as e:
        logger.info(f"Error in service cost analysis: {str(e)}")
        return None

def get_region_cost(days: int=30, region: str="us-west-2"):
    """
    Get AWS region cost data
    Parameters:
        days: the period of the data, e.g., 30
        region: The region of aws infrastructure, e.g., us-west-2
    Returns:
        DataFrame containing region costs
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # cost explorer
        ce = boto3.client(
            service_name='ce',
            region_name=region
        )

        region_response = ce.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'REGION'}]
        )
        logger.info(f"Region Cost: {region_response}")
        
        region_costs = pd.DataFrame([
            {
                'REGION': group['Keys'][0],
                'cost': float(group['Metrics']['UnblendedCost']['Amount'])
            }
            for group in region_response['ResultsByTime'][0]['Groups']
        ])

        region_costs_df = pd.DataFrame(region_costs)
        logger.info(f"Region Cost (df): {region_costs_df}")

        global region_cost_data
        region_cost_data = {
            'region_costs': region_costs_df
        }

    except Exception as e:
        logger.info(f"Error in region cost analysis: {str(e)}")
        return None

def get_daily_cost(days: int=30, region: str="us-west-2"):
    """
    Get AWS daily cost data
    Parameters:
        days: the period of the data, e.g., 30
        region: The region of aws infrastructure, e.g., us-west-2
    Returns:
        DataFrame containing daily costs
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # cost explorer
        ce = boto3.client(
            service_name='ce',
            region_name=region
        )

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
        logger.info(f"Daily Cost (df): {daily_costs_df}")

        global daily_cost_data
        daily_cost_data = {
            'daily_costs': daily_costs_df
        }

        return daily_cost_data

    except Exception as e:
        logger.info(f"Error in cost analysis: {str(e)}")
        return None

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

def create_service_cost_visualizations():
    """Cost Visualization of aws services"""
    logger.info("Creating cost visualizations...")
        
    paths = []
    
    # service cost (pie chart)
    fig_pie = px.pie(
        cost_data['service_costs'],
        values='cost',
        names='SERVICE',
        title='Service Cost'
    )    
    paths.append(get_url(fig_pie, "service_costs"))
            
    return {
        "path": paths
    }

def create_daily_cost_visualizations():
    """Visualize daily AWS costs showing total costs and service-wise breakdown"""
    logger.info("Creating daily cost visualizations...")

    if not daily_cost_data or 'daily_costs' not in daily_cost_data:
        logger.info("No cost data available")
        return None        
    
    paths = []
    
    # Get daily costs DataFrame
    daily_costs_df = daily_cost_data['daily_costs']
    
    # Calculate daily total costs
    daily_totals = daily_costs_df.groupby('date')['cost'].sum().reset_index()
    
    # Total cost trend graph
    fig_total = px.line(
        daily_totals,
        x='date',
        y='cost',
        title='Daily Total Cost Trend'
    )
    paths.append(get_url(fig_total, "daily_total_costs"))

    # Service-wise cost trend graph
    fig_service = px.line(
        daily_costs_df,
        x='date',
        y='cost',
        color='SERVICE',
        title='Daily Cost Trend by Service'
    )
    paths.append(get_url(fig_service, "daily_service_costs"))

    # Daily service cost heatmap
    pivot_df = daily_costs_df.pivot_table(
        index='date',
        columns='SERVICE',
        values='cost',
        fill_value=0
    )
    
    fig_heatmap = px.imshow(
        pivot_df,
        title='Daily Cost Heatmap by Service',
        labels=dict(x="Service", y="Date", color="Cost"),
        aspect="auto"
    )
    paths.append(get_url(fig_heatmap, "daily_cost_heatmap"))
        
    logger.info(f"paths: {paths}")

    return {
        "path": paths
    }

def create_region_cost_visualizations():
    """Cost Visualization of region AWS cost"""
    logger.info("Creating region cost visualizations...")

    if not region_cost_data:
        logger.info("No cost data available")
        return None
        
    paths = []
    
    # region cost (bar chart)
    fig_bar = px.bar(
        cost_data['region_costs'],
        x='REGION',
        y='cost',
        title='Region Cost'
    )
    paths.append(get_url(fig_bar, "region_costs"))
    
    logger.info(f"paths: {paths}")

    return {
        "path": paths
    }

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
        "You are an AWS solutions architect."
        "Using the following Cost Data, answer user's questions."
        "If you don't know the answer, you can honestly say you don't know."
        "You will explain the answer in detail and clearly."
    )
    human = (
        "Please analyze the following AWS cost data and provide detailed insights:"
        "Cost Data:"
        "{raw_cost}"
        
        "Please analyze the following items:"
        "1. Main cost drivers"
        "2. Unusual patterns or sudden cost increases"
        "3. Areas where cost optimization is possible"
        "4. Overall cost trend and future prediction"
        
        "Please provide the analysis results in the following format:"

        "### Main cost drivers"
        "- [Detailed analysis content]"

        "### Unusual pattern analysis"
        "- [Description of unusual cost pattern]"

        "### Cost optimization opportunities"
        "- [Detailed cost optimization plan]"

        "### Cost trend"
        "- [Trend analysis and prediction]"
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

def ask_cost_insights(question):
    if cost_data:
        cost_data_dict = {
            'service_costs': cost_data['service_costs'].to_dict(orient='records'),
            'region_costs': cost_data['region_costs'].to_dict(orient='records'),
            'daily_costs': cost_data['daily_costs'].to_dict(orient='records') if 'daily_costs' in cost_data else []
        }
    else:
        return "Failed to retrieve cost data."

    system = (
        "You are an AWS solutions architect."
        "Using the following Cost Data, answer user's questions."
        "If you don't know the answer, you can honestly say you don't know."
        "You will explain the answer in detail and clearly."
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
