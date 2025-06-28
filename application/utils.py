import logging
import sys
import json
import traceback
import boto3
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-basic")

def load_config():
    config = None
    
    with open("application/config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

bedrock_region = config['region']
projectName = config['projectName']

def get_contents_type(file_name):
    if file_name.lower().endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    elif file_name.lower().endswith((".pdf")):
        content_type = "application/pdf"
    elif file_name.lower().endswith((".txt")):
        content_type = "text/plain"
    elif file_name.lower().endswith((".csv")):
        content_type = "text/csv"
    elif file_name.lower().endswith((".ppt", ".pptx")):
        content_type = "application/vnd.ms-powerpoint"
    elif file_name.lower().endswith((".doc", ".docx")):
        content_type = "application/msword"
    elif file_name.lower().endswith((".xls")):
        content_type = "application/vnd.ms-excel"
    elif file_name.lower().endswith((".py")):
        content_type = "text/x-python"
    elif file_name.lower().endswith((".js")):
        content_type = "application/javascript"
    elif file_name.lower().endswith((".md")):
        content_type = "text/markdown"
    elif file_name.lower().endswith((".png")):
        content_type = "image/png"
    else:
        content_type = "no info"    
    return content_type

def load_mcp_env():
    with open("application/mcp.env", "r", encoding="utf-8") as f:
        mcp_env = json.load(f)
    return mcp_env

def save_mcp_env(mcp_env):
    with open("application/mcp.env", "w", encoding="utf-8") as f:
        json.dump(mcp_env, f)

# api key to get weather information in agent
secretsmanager = boto3.client(
    service_name='secretsmanager',
    region_name=bedrock_region
)

# api key for weather
weather_api_key = ""
try:
    get_weather_api_secret = secretsmanager.get_secret_value(
        SecretId=f"openweathermap-{projectName}"
    )
    #print('get_weather_api_secret: ', get_weather_api_secret)
    secret = json.loads(get_weather_api_secret['SecretString'])
    #print('secret: ', secret)
    weather_api_key = secret['weather_api_key']

except Exception as e:
    raise e

# api key to use Tavily Search
tavily_key = tavily_api_wrapper = ""
try:
    get_tavily_api_secret = secretsmanager.get_secret_value(
        SecretId=f"tavilyapikey-{projectName}"
    )
    #print('get_tavily_api_secret: ', get_tavily_api_secret)
    secret = json.loads(get_tavily_api_secret['SecretString'])
    #print('secret: ', secret)

    if "tavily_api_key" in secret:
        tavily_key = secret['tavily_api_key']
        #print('tavily_api_key: ', tavily_api_key)

        if tavily_key:
            tavily_api_wrapper = TavilySearchAPIWrapper(tavily_api_key=tavily_key)
            #     os.environ["TAVILY_API_KEY"] = tavily_key

        else:
            logger.info(f"tavily_key is required.")
except Exception as e: 
    logger.info(f"Tavily credential is required: {e}")
    raise e

# api key to use firecrawl Search
firecrawl_key = ""
try:
    get_firecrawl_secret = secretsmanager.get_secret_value(
        SecretId=f"firecrawlapikey-{projectName}"
    )
    secret = json.loads(get_firecrawl_secret['SecretString'])

    if "firecrawl_api_key" in secret:
        firecrawl_key = secret['firecrawl_api_key']
        # print('firecrawl_api_key: ', firecrawl_key)
except Exception as e: 
    logger.info(f"Firecrawl credential is required: {e}")
    raise e

# api key to use perplexity Search
perplexity_key = ""
try:
    get_perplexity_api_secret = secretsmanager.get_secret_value(
        SecretId=f"perplexityapikey-{projectName}"
    )
    #print('get_perplexity_api_secret: ', get_perplexity_api_secret)
    secret = json.loads(get_perplexity_api_secret['SecretString'])
    #print('secret: ', secret)

    if "perplexity_api_key" in secret:
        perplexity_key = secret['perplexity_api_key']
        #print('perplexity_api_key: ', perplexity_api_key)

except Exception as e: 
    logger.info(f"perplexity credential is required: {e}")
    raise e

async def generate_pdf_report(report_content: str, filename: str) -> str:
    """
    Generates a PDF report from the research findings.
    Args:
        report_content: The content to be converted into PDF format
        filename: Base name for the generated PDF file
    Returns:
        A message indicating the result of PDF generation
    """
    logger.info(f'###### generate_pdf_report ######')
    try:
        # Ensure directory exists
        os.makedirs("artifacts", exist_ok=True)
        # Set up the PDF file
        filepath = f"artifacts/{filename}.pdf"
        logger.info(f"filepath: {filepath}")
        doc = SimpleDocTemplate(filepath, pagesize=letter)
        # Register TTF font directly (specify path to NanumGothic font file)
        font_path = "assets/NanumGothic-Regular.ttf"  # Change to actual TTF file path
        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
        # Create styles
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='Normal_KO',
                                fontName='NanumGothic',
                                fontSize=10,
                                spaceAfter=12))  # 문단 간격 증가
        styles.add(ParagraphStyle(name='Heading1_KO',
                                fontName='NanumGothic',
                                fontSize=16,
                                spaceAfter=20,  # 제목 후 여백 증가
                                textColor=colors.HexColor('#0000FF')))  # 파란색
        styles.add(ParagraphStyle(name='Heading2_KO',
                                fontName='NanumGothic',
                                fontSize=14,
                                spaceAfter=16,  # 제목 후 여백 증가
                                textColor=colors.HexColor('#0000FF')))  # 파란색
        styles.add(ParagraphStyle(name='Heading3_KO',
                                fontName='NanumGothic',
                                fontSize=12,
                                spaceAfter=14,  # 제목 후 여백 증가
                                textColor=colors.HexColor('#0000FF')))  # 파란색
        # Process content
        elements = []
        lines = report_content.split('\n')
        for line in lines:
            if line.startswith('# '):
                elements.append(Paragraph(line[2:], styles['Heading1_KO']))
            elif line.startswith('## '):
                elements.append(Paragraph(line[3:], styles['Heading2_KO']))
            elif line.startswith('### '):
                elements.append(Paragraph(line[4:], styles['Heading3_KO']))
            elif line.strip():  # Skip empty lines
                elements.append(Paragraph(line, styles['Normal_KO']))
        # Build PDF
        doc.build(elements)
        return f"PDF report generated successfully: {filepath}"
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        # Fallback to text file
        try:
            text_filepath = f"artifacts/{filename}.txt"
            with open(text_filepath, 'w', encoding='utf-8') as f:
                f.write(report_content)
            return f"PDF generation failed. Saved as text file instead: {text_filepath}"
        except Exception as text_error:
            return f"Error generating report: {str(e)}. Text fallback also failed: {str(text_error)}"