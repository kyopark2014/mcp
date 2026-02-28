---
name: search-weather
description: Search real-time weather information by city name using OpenWeatherMap API. Use when the user asks about weather, current temperature, forecasts, or climate conditions for a specific city (e.g., "서울 날씨", "Tokyo weather", "뉴욕 기온"). Always pass city names in English to the script.
---

# Search Weather

OpenWeatherMap API를 활용하여 도시별 실시간 날씨 정보를 검색하는 skill.

## Quick Start

```bash
python skills/search-weather/scripts/weather_search.py "Seoul"
python skills/search-weather/scripts/weather_search.py "Tokyo" --format text
```

**중요**: 항상 전체 경로 `skills/search-weather/scripts/weather_search.py`를 사용한다.

## 도시명은 반드시 영문으로

사용자가 한글로 도시를 요청하더라도, 스크립트에는 영문 도시명을 전달한다.
- "서울 날씨" -> `"Seoul"`
- "도쿄 날씨" -> `"Tokyo"`
- "뉴욕 날씨" -> `"New York"`

## 명령어 옵션

- `city` (필수): 영문 도시명 (e.g., Seoul, Tokyo, New York)
- `--format [json|text]`: 출력 형식 (기본값: json)

## JSON 응답 필드

| 필드 | 설명 |
|------|------|
| `city` | 도시 이름 |
| `overall` | 날씨 요약 (e.g., Clear, Clouds, Rain) |
| `description` | 상세 날씨 설명 |
| `current_temp` | 현재 기온 |
| `feels_like` | 체감 온도 |
| `min_temp` / `max_temp` | 최저/최고 기온 |
| `humidity` | 습도 |
| `pressure` | 기압 |
| `wind_speed` | 풍속 (m/s) |
| `wind_direction` | 풍향 (도) |
| `clouds` | 구름량 |
| `visibility` | 가시거리 |
| `last_updated` | 마지막 업데이트 시각 (UTC) |
| `status` | `success` 또는 `error` |
| `error` | 에러 메시지 (`status`가 `error`일 때만 포함) |

## Agent 통합

```python
import subprocess
import json

WEATHER_SCRIPT = "skills/search-weather/scripts/weather_search.py"

result = subprocess.run(
    ["python", WEATHER_SCRIPT, city_name, "--format", "json"],
    capture_output=True,
    text=True
)
response = json.loads(result.stdout)
```

## API Key

OpenWeatherMap API key는 다음 순서로 조회된다:
1. `utils.weather_api_key` (AWS Secrets Manager에서 로드)
2. 환경변수 `OPENWEATHERMAP_API_KEY`

## 요구사항

- Python 3.6+
- `requests` 라이브러리
- OpenWeatherMap API key
- 인터넷 연결
