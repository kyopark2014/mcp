import logging
import sys
import datetime
import requests
import yfinance as yf
import chat
import traceback
import json
import re
import utils
import os
from pytz import timezone
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-basic")

aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.environ.get('AWS_SESSION_TOKEN')
aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')

def get_current_time(format: str=f"%Y-%m-%d %H:%M:%S")->str:
    """Returns the current date and time in the specified format"""
    # f"%Y-%m-%d %H:%M:%S"
    
    format = format.replace('\'','')
    timestr = datetime.datetime.now(timezone('Asia/Seoul')).strftime(format)
    logger.info(f"timestr: {timestr}")
    
    return timestr

def get_book_list(keyword: str) -> str:
    """
    Search book list by keyword and then return book list
    keyword: search keyword
    return: book list
    """
    
    keyword = keyword.replace('\'','')

    answer = ""
    url = f"https://search.kyobobook.co.kr/search?keyword={keyword}&gbCode=TOT&target=total"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        prod_info = soup.find_all("a", attrs={"class": "prod_info"})
        
        if len(prod_info):
            answer = "추천 도서는 아래와 같습니다.\n"
            
        for prod in prod_info[:5]:
            title = prod.text.strip().replace("\n", "")       
            link = prod.get("href")
            answer = answer + f"{title}, URL: {link}\n\n"
    
    return answer

def get_weather_info(city: str) -> str:
    """
    retrieve weather information by city name and then return weather statement.
    city: the English name of city to retrieve
    return: weather statement
    """    
    
    city = city.replace('\n','')
    city = city.replace('\'','')
    city = city.replace('\"','')
                
    llm = chat.get_chat(extended_thinking="Disable")
    if chat.isKorean(city):
        place = chat.traslation(llm, city, "Korean", "English")
        logger.info(f"city (translated): {place}")
    else:
        place = city
        city = chat.traslation(llm, city, "English", "Korean")
        logger.info(f"city (translated): {city}")
        
    logger.info(f"place: {place}")
    
    weather_str: str = f"{city}에 대한 날씨 정보가 없습니다."

    weather_api_key = utils.weather_api_key
    if weather_api_key: 
        apiKey = weather_api_key
        lang = 'en' 
        units = 'metric' 
        api = f"https://api.openweathermap.org/data/2.5/weather?q={place}&APPID={apiKey}&lang={lang}&units={units}"
        # print('api: ', api)
                
        try:
            result = requests.get(api)
            result = json.loads(result.text)
            logger.info(f"result: {result}")
        
            if 'weather' in result:
                overall = result['weather'][0]['main']
                current_temp = result['main']['temp']
                min_temp = result['main']['temp_min']
                max_temp = result['main']['temp_max']
                humidity = result['main']['humidity']
                wind_speed = result['wind']['speed']
                cloud = result['clouds']['all']
                
                #weather_str = f"{city}의 현재 날씨의 특징은 {overall}이며, 현재 온도는 {current_temp}도 이고, 최저온도는 {min_temp}도, 최고 온도는 {max_temp}도 입니다. 현재 습도는 {humidity}% 이고, 바람은 초당 {wind_speed} 미터 입니다. 구름은 {cloud}% 입니다."
                weather_str = f"{city}의 현재 날씨의 특징은 {overall}이며, 현재 온도는 {current_temp} 입니다. 현재 습도는 {humidity}% 이고, 바람은 초당 {wind_speed} 미터 입니다. 구름은 {cloud}% 입니다."
                #weather_str = f"Today, the overall of {city} is {overall}, current temperature is {current_temp} degree, min temperature is {min_temp} degree, highest temperature is {max_temp} degree. huminity is {humidity}%, wind status is {wind_speed} meter per second. the amount of cloud is {cloud}%."            
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")   
            # raise Exception ("Not able to request to LLM")    
        
    logger.info(f"weather_str: {weather_str}")                        
    return weather_str

def stock_data_lookup(ticker, country, period="1mo"):
    """
    Retrieve accurate stock data for a given ticker.
    country: the english country name of the stock
    ticker: the ticker to retrieve stock price history for. In South Korea, a ticker is a 6-digit number.
    period: the period to retrieve stock price history for. for example, "1mo", "1y", "5y", "max"
    return: the information of ticker
    """ 
    com = re.compile('[a-zA-Z]') 
    alphabet = com.findall(ticker)
    logger.info(f"alphabet: {alphabet}")

    logger.info(f"country: {country}")

    if len(alphabet)==0:
        if country == "South Korea":
            ticker += ".KS"
        elif country == "Japan":
            ticker += ".T"
    logger.info(f"ticker: {ticker}")
    
    stock = yf.Ticker(ticker)
    
    # get the price history for past 1 month
    history = stock.history(period=period)
    logger.info(f"history: {history}")
    
    result = f"## Trading History\n{history}"
    #history.reset_index().to_json(orient="split", index=False, date_format="iso")    
    
    result += f"\n\n## Financials\n{stock.financials}"    
    logger.info(f"financials: {stock.financials}")

    result += f"\n\n## Major Holders\n{stock.major_holders}"
    logger.info(f"major_holders: {stock.major_holders}")

    logger.info(f"result: {result}")

    return result
