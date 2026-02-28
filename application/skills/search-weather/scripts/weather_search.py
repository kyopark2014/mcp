#!/usr/bin/env python3
"""
Weather Search Script for search-weather skill
OpenWeatherMap API를 활용하여 도시별 날씨 정보를 검색합니다.
"""

import argparse
import json
import sys
import os

import requests
import traceback
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("weather-search")


def get_weather_info(city: str) -> dict:
    """
    OpenWeatherMap API를 사용하여 날씨 정보를 가져온다.
    city: 영문 도시명 (e.g., Seoul, Tokyo, New York)
    """
    city = city.replace('\n', '').replace('\'', '').replace('\"', '')

    api_key = os.environ.get("OPENWEATHERMAP_API_KEY", "")
    if not api_key:
        return {
            "city": city,
            "error": "OpenWeatherMap API key not configured. Set OPENWEATHERMAP_API_KEY or configure via AWS Secrets Manager.",
            "status": "error"
        }

    lang = 'en'
    units = 'metric'
    api = f"https://api.openweathermap.org/data/2.5/weather?q={city}&APPID={api_key}&lang={lang}&units={units}"

    try:
        result = requests.get(api, timeout=10)
        data = json.loads(result.text)
        logger.info(f"API response: {data}")

        if 'weather' not in data:
            return {
                "city": city,
                "error": data.get("message", "Unknown error from API"),
                "status": "error"
            }

        weather_info = {
            "city": city,
            "overall": data['weather'][0]['main'],
            "description": data['weather'][0].get('description', ''),
            "current_temp": f"{data['main']['temp']}°C",
            "feels_like": f"{data['main'].get('feels_like', 'N/A')}°C",
            "min_temp": f"{data['main']['temp_min']}°C",
            "max_temp": f"{data['main']['temp_max']}°C",
            "humidity": f"{data['main']['humidity']}%",
            "pressure": f"{data['main'].get('pressure', 'N/A')} hPa",
            "wind_speed": f"{data['wind']['speed']} m/s",
            "wind_direction": f"{data['wind'].get('deg', 'N/A')}°",
            "clouds": f"{data['clouds']['all']}%",
            "visibility": f"{data.get('visibility', 'N/A')} m",
            "last_updated": datetime.utcfromtimestamp(data['dt']).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "status": "success"
        }

        return weather_info

    except Exception:
        err_msg = traceback.format_exc()
        logger.error(f"Weather API error: {err_msg}")
        return {
            "city": city,
            "error": "Failed to retrieve weather information.",
            "status": "error"
        }


def format_weather_text(weather_data: dict) -> str:
    """날씨 정보를 사람이 읽기 쉬운 텍스트로 포맷팅한다."""
    if weather_data['status'] == 'error':
        return f"❌ {weather_data['city']}: {weather_data['error']}"

    return f"""{weather_data['city']} 날씨 정보

현재 날씨:
  날씨: {weather_data['overall']} ({weather_data['description']})
  기온: {weather_data['current_temp']} (체감: {weather_data['feels_like']})
  최저/최고: {weather_data['min_temp']} / {weather_data['max_temp']}
  습도: {weather_data['humidity']}
  기압: {weather_data['pressure']}
  바람: {weather_data['wind_speed']} ({weather_data['wind_direction']})
  구름: {weather_data['clouds']}
  가시거리: {weather_data['visibility']}

업데이트: {weather_data['last_updated']}"""


def main():
    parser = argparse.ArgumentParser(description='Weather search via OpenWeatherMap API')
    parser.add_argument('city', help='City name in English (e.g., Seoul, Tokyo, New York)')
    parser.add_argument('--format', choices=['json', 'text'], default='json',
                        help='Output format (default: json)')

    args = parser.parse_args()

    weather_data = get_weather_info(args.city)

    if args.format == 'json':
        print(json.dumps(weather_data, ensure_ascii=False, indent=2))
    else:
        print(format_weather_text(weather_data))


if __name__ == "__main__":
    main()
