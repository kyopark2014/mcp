"""
MCP server for weather information retrieval using OpenWeatherMap API.
"""
import logging
import sys
import re
import json
import requests
import traceback
import boto3
import info
import utils

from botocore.config import Config
from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-server-weather")


def is_korean(text: str) -> bool:
    """Check if text contains Korean characters."""
    pattern_hangul = re.compile(r'[\u3131-\u3163\uac00-\ud7a3]+')
    return pattern_hangul.search(str(text)) is not None


def get_chat(extended_thinking: str):
    """Get Bedrock chat client for translation."""
    model_name = "Claude 4 Sonnet"
    models = info.get_model_info(model_name)
    model_id = models[0]["model_id"]
    profile = models[0]

    bedrock_region = profile['bedrock_region']
    modelId = profile['model_id']
    model_type = profile['model_type']
    maxOutputTokens = 4096 if model_type == 'claude' else 5120
    STOP_SEQUENCE = "\n\nHuman:"

    boto3_bedrock = boto3.client(
        service_name='bedrock-runtime',
        region_name=bedrock_region,
        config=Config(retries={'max_attempts': 30})
    )

    parameters = {
        "max_tokens": maxOutputTokens,
        "temperature": 0.1,
        "top_k": 250,
        "stop_sequences": [STOP_SEQUENCE]
    }

    return ChatBedrock(
        model_id=modelId,
        client=boto3_bedrock,
        model_kwargs=parameters,
        region_name=bedrock_region
    )


def translation(chat, text: str, input_language: str, output_language: str) -> str:
    """Translate text between languages using LLM."""
    system = (
        "You are a helpful assistant that translates {input_language} to {output_language} in <article> tags. "
        "Put it in <result> tags."
    )
    human = "<article>{text}</article>"
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    chain = prompt | chat

    try:
        result = chain.invoke({
            "input_language": input_language,
            "output_language": output_language,
            "text": text,
        })
        msg = result.content
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")
        raise Exception("Not able to request to LLM")

    return msg[msg.find('<result>') + 8:len(msg) - 9]


def get_weather_info(city: str) -> str:
    """
    Retrieve weather information by city name and return weather statement.
    city: the name of city to retrieve (supports Korean and English)
    return: weather statement
    """
    city = city.replace('\n', '').replace('\'', '').replace('"', '')

    llm = get_chat(extended_thinking="Disable")
    if is_korean(city):
        place = translation(llm, city, "Korean", "English")
        logger.info(f"city (translated): {place}")
    else:
        place = city
        city = translation(llm, city, "English", "Korean")
        logger.info(f"city (translated): {city}")

    logger.info(f"place: {place}")

    weather_str = f"{city}에 대한 날씨 정보가 없습니다."

    weather_api_key = utils.weather_api_key
    if weather_api_key:
        api = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={place}&APPID={weather_api_key}&lang=en&units=metric"
        )

        try:
            result = requests.get(api)
            result = json.loads(result.text)
            logger.info(f"result: {result}")

            if 'weather' in result:
                overall = result['weather'][0]['main']
                current_temp = result['main']['temp']
                humidity = result['main']['humidity']
                wind_speed = result['wind']['speed']
                cloud = result['clouds']['all']

                weather_str = (
                    f"{city}의 현재 날씨의 특징은 {overall}이며, 현재 온도는 {current_temp} 입니다. "
                    f"현재 습도는 {humidity}% 이고, 바람은 초당 {wind_speed} 미터 입니다. "
                    f"구름은 {cloud}% 입니다."
                )
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")

    logger.info(f"weather_str: {weather_str}")
    return weather_str


try:
    mcp = FastMCP(
        name="weather",
        instructions=(
            "You are a helpful assistant that provides weather information. "
            "You can use tools to get weather for any city (supports Korean and English city names)."
        ),
    )
    logger.info("Weather MCP server initialized successfully")
except Exception as e:
    logger.info(f"Error: {str(e)}")


@mcp.tool()
def get_weather(city: str) -> str:
    """
    Retrieve weather information by city name and return weather statement.
    city: the name of city to retrieve (supports Korean and English)
    return: weather statement
    """
    logger.info(f"get_weather --> city: {city}")
    return get_weather_info(city)


if __name__ == "__main__":
    mcp.run(transport="stdio")
