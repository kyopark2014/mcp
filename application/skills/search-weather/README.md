# Search Weather Skill

도시 이름을 입력받아 실시간 날씨 정보를 검색하고 반환하는 skill입니다.

## 기능

- 전 세계 주요 도시의 실시간 날씨 정보 제공
- 한글 및 영문 도시명 지원
- 현재 날씨, 체감온도, 습도, 바람, 기압 등 상세 정보
- 오늘의 최고/최저 기온 및 일출/일몰 시간
- JSON 및 텍스트 형태 출력 지원

## 사용법

### 기본 사용법

```bash
python skills/search-weather/scripts/weather_search.py "서울"
```

### 영문 도시명으로 검색

```bash
python skills/search-weather/scripts/weather_search.py "Tokyo"
```

### 텍스트 형태로 출력

```bash
python skills/search-weather/scripts/weather_search.py "New York" --format text
```

## 명령어 옵션

- `city` (필수): 검색할 도시 이름
- `--format [json|text]`: 출력 형식 (기본값: json)
- `--lang`: 언어 설정 (기본값: ko)

## 지원 도시

전 세계 주요 도시를 지원합니다:

### 한국
- 서울, Seoul
- 부산, Busan
- 대구, Daegu
- 인천, Incheon
- 광주, Gwangju
- 대전, Daejeon
- 울산, Ulsan

### 해외 주요 도시
- Tokyo, 도쿄
- Beijing, 베이징
- Shanghai, 상하이
- New York, 뉴욕
- London, 런던
- Paris, 파리
- Berlin, 베를린
- Sydney, 시드니

## 출력 형식

### JSON 형식 (기본값)
```json
{
  "city": "서울",
  "current_temp": "15°C",
  "feels_like": "13°C",
  "description": "맑음",
  "humidity": "65%",
  "wind_speed": "10 km/h",
  "wind_direction": "NW",
  "pressure": "1013 hPa",
  "visibility": "10 km",
  "uv_index": "3",
  "max_temp": "18°C",
  "min_temp": "8°C",
  "sunrise": "06:45 AM",
  "sunset": "06:30 PM",
  "last_updated": "2024-01-15 14:30:00",
  "status": "success"
}
```

### 텍스트 형식
```
🌤️ 서울 날씨 정보

📊 현재 날씨:
• 기온: 15°C (체감온도: 13°C)
• 날씨: 맑음
• 습도: 65%
• 바람: 10 km/h (NW)
• 기압: 1013 hPa
• 가시거리: 10 km
• 자외선 지수: 3

📈 오늘 예보:
• 최고기온: 18°C
• 최저기온: 8°C
• 일출: 06:45 AM
• 일몰: 06:30 PM

⏰ 업데이트: 2024-01-15 14:30:00
```

## 오류 처리

도시를 찾을 수 없거나 네트워크 오류가 발생한 경우:

```json
{
  "city": "잘못된도시명",
  "error": "날씨 정보를 가져올 수 없습니다.",
  "status": "error"
}
```

## 기술적 세부사항

- **API**: wttr.in 무료 날씨 서비스 사용
- **언어**: Python 3.6+
- **의존성**: requests 라이브러리
- **응답 시간**: 일반적으로 1-3초
- **API 키**: 불필요 (무료 서비스)

## 설치 요구사항

```bash
pip install requests
```

## 예제 사용법

### Python 코드에서 사용
```python
import subprocess
import json

result = subprocess.run(
    ["python", "skills/search-weather/scripts/weather_search.py", "서울"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    weather_data = json.loads(result.stdout)
    print(f"{weather_data['city']} 현재 기온: {weather_data['current_temp']}")
```

### 여러 도시 검색
```bash
for city in "서울" "도쿄" "뉴욕"; do
    python skills/search-weather/scripts/weather_search.py "$city" --format text
    echo "---"
done
```

## 주의사항

- 인터넷 연결이 필요합니다
- 일부 소규모 도시는 검색되지 않을 수 있습니다
- 날씨 정보는 실시간으로 업데이트되지만 약간의 지연이 있을 수 있습니다