"""
MCP server for Korean weather information from 기상청 날씨누리 (weather.go.kr) and 에어코리아.
날씨누리 단기예보, AWS 실시간 관측(기온/풍속/습도), 에어코리아 미세먼지·오존을 제공합니다.
인증키 없이 사용 가능합니다.
"""
import logging
import sys
import re
import requests
import traceback
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-server-korea-weather")

# URL
WEATHER_GO_KR_URL = "https://www.weather.go.kr/w/weather/forecast/short-term.do"
AWS_OBS_URL = "https://www.weather.go.kr/w/weather/land/aws-obs.do"
AIRKOREA_URL = "https://www.airkorea.or.kr/web/dustForecast"
AIRKOREA_FULL_URL = "https://www.airkorea.or.kr/web/dustForecast?pMENU_NO=113"

# 기상청/에어코리아 페이지 링크
WEATHER_PAGE_LINKS = {
    "날씨누리 메인(지도)": "https://www.weather.go.kr/w/index.do",
    "날씨지도": "https://www.weather.go.kr/wgis-nuri/html/map.html",
    "단기예보": "https://www.weather.go.kr/w/weather/forecast/short-term.do",
    "분석일기도": "https://www.weather.go.kr/w/image/chart/analysis.do",
    "대기질예보": "https://www.airkorea.or.kr/web/dustForecast?pMENU_NO=113",
    "황사일기도": "https://www.weather.go.kr/w/dust/image/sfc-chart.do",
    "지역별 관측": "https://www.weather.go.kr/w/weather/land/aws-obs.do",
}

# 지역명 -> stnId (날씨누리 발표관서)
LOCATION_TO_STNID = {
    "전국": 108, "서울": 109, "인천": 109, "경기": 109, "수원": 109, "성남": 109,
    "고양": 109, "용인": 109, "안양": 109, "부천": 109, "광명": 109, "김포": 109,
    "파주": 109, "양주": 109, "포천": 109, "가평": 109, "연천": 109, "화성": 109,
    "오산": 109, "평택": 109, "시흥": 109, "안산": 109, "군포": 109, "의왕": 109,
    "과천": 109, "하남": 109, "남양주": 109, "강원": 105, "춘천": 105, "강릉": 105,
    "원주": 105, "홍천": 105, "속초": 105, "충북": 131, "청주": 131, "충주": 131,
    "제천": 131, "단양": 131, "괴산": 131, "음성": 131, "진천": 131, "보은": 131,
    "영동": 131, "옥천": 131, "대전": 133, "세종": 133, "충남": 133, "천안": 133,
    "아산": 133, "당진": 133, "서산": 133, "태안": 133, "홍성": 133, "예산": 133,
    "공주": 133, "보령": 133, "서천": 133, "부여": 133, "논산": 133, "금산": 133,
    "계룡": 133, "전북": 146, "전주": 146, "군산": 146, "광주": 156, "전남": 156,
    "여수": 156, "목포": 156, "나주": 156, "순천": 156, "대구": 143, "경북": 143,
    "포항": 143, "경주": 143, "김천": 143, "구미": 143, "안동": 143, "영주": 143,
    "영천": 143, "상주": 143, "문경": 143, "예천": 143, "영양": 143, "봉화": 143,
    "울진": 143, "부산": 159, "울산": 159, "경남": 159, "창원": 159, "김해": 159,
    "진주": 159, "거제": 159, "통영": 159, "양산": 159, "밀양": 159, "거창": 159,
    "함양": 159, "산청": 159, "의령": 159, "창녕": 159, "고성": 159, "남해": 159,
    "제주": 184, "제주시": 184,
}

# 지역 -> AWS 관측 지점명 (aws-obs 테이블의 지점명)
LOCATION_TO_AWS_STATION = {
    "서울": "서울", "인천": "인천", "수원": "수원", "파주": "파주", "춘천": "춘천",
    "강릉": "강릉", "원주": "원주", "속초": "속초", "청주": "청주", "충주": "충주",
    "대전": "대전", "세종": "세종", "천안": "천안", "서산": "서산", "전주": "전주",
    "군산": "군산", "광주": "광주", "목포": "목포", "여수": "여수", "대구": "대구",
    "포항": "포항", "안동": "안동", "부산": "부산", "울산": "울산", "창원": "창원",
    "진주": "진주", "통영": "통영", "제주": "제주", "서귀포": "서귀포",
}

# 지역 -> 에어코리아 권역 (표 컬럼명)
LOCATION_TO_AIR_REGION = {
    "서울": "서울", "인천": "인천", "수원": "경기", "성남": "경기", "고양": "경기",
    "용인": "경기", "안양": "경기", "부천": "경기", "화성": "경기", "평택": "경기",
    "춘천": "강원", "강릉": "강원", "원주": "강원", "속초": "강원", "홍천": "강원",
    "대전": "대전", "세종": "세종", "청주": "충북", "충주": "충북", "천안": "충남",
    "아산": "충남", "서산": "충남", "전주": "전북", "군산": "전북", "광주": "광주",
    "여수": "전남", "목포": "전남", "순천": "전남", "대구": "대구", "포항": "경북",
    "경주": "경북", "안동": "경북", "부산": "부산", "울산": "울산", "창원": "경남",
    "김해": "경남", "진주": "경남", "통영": "경남", "제주": "제주",
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def get_stnid(location: str) -> tuple[int, str] | None:
    """지역명으로 stnId와 표시명 반환."""
    location = location.strip()
    if location in LOCATION_TO_STNID:
        return LOCATION_TO_STNID[location], location
    for name, stnid in LOCATION_TO_STNID.items():
        if name in location or location in name:
            return stnid, name
    return None


def get_aws_station(location: str) -> str | None:
    """지역명으로 AWS 관측 지점명 반환."""
    location = location.strip()
    if location in LOCATION_TO_AWS_STATION:
        return LOCATION_TO_AWS_STATION[location]
    for name, station in LOCATION_TO_AWS_STATION.items():
        if name in location or location in name:
            return station
    return None


def get_air_region(location: str) -> str | None:
    """지역명으로 에어코리아 권역명 반환."""
    location = location.strip()
    if location in LOCATION_TO_AIR_REGION:
        return LOCATION_TO_AIR_REGION[location]
    for name, region in LOCATION_TO_AIR_REGION.items():
        if name in location or location in name:
            return region
    return None


def fetch_page(url: str, params: dict | None = None) -> str | None:
    """페이지 HTML 가져오기."""
    try:
        resp = requests.get(url, params=params or {}, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        logger.error(f"페이지 요청 실패 {url}: {e}")
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def parse_aws_obs(html: str, station_name: str) -> dict | None:
    """AWS 관측 테이블에서 해당 지점의 기온, 풍향, 풍속, 습도 추출."""
    if not html or not station_name:
        return None
    # 테이블: 번호|지점|고도|강수유무|일강수|기온|체감온도|10분풍향|10분풍속|습도|위치
    # 지점이 station_name인 행 찾기 (위치 컬럼으로 행 식별)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        if station_name not in row:
            continue
        tds = re.findall(r"<td[^>]*>([^<]*(?:<[^>]+>[^<]*)*?)</td>", row)
        if len(tds) >= 10:
            # 셀1=지점, 셀5=기온, 6=체감, 7=풍향, 8=풍속, 9=습도
            if re.sub(r"<[^>]+>", "", tds[1]).strip() == station_name:
                return {
                    "기온": re.sub(r"<[^>]+>", "", tds[5]).strip(),
                    "체감온도": re.sub(r"<[^>]+>", "", tds[6]).strip(),
                    "풍향": re.sub(r"<[^>]+>", "", tds[7]).strip(),
                    "풍속": re.sub(r"<[^>]+>", "", tds[8]).strip(),
                    "습도": re.sub(r"<[^>]+>", "", tds[9]).strip(),
                }
    return None


def parse_airkorea(html: str, region: str) -> dict | None:
    """에어코리아 페이지에서 해당 권역의 미세먼지, 오존 예보 추출."""
    if not html or not region:
        return None
    result = {}
    region_cols = ["구분", "서울", "인천", "경기", "강원", "대전", "세종", "충북", "충남", "광주", "전북", "전남", "부산", "대구", "울산", "경북", "경남", "제주"]
    if region not in region_cols[1:]:
        return result
    col_idx = region_cols.index(region)

    # 예보 요약
    summary = re.search(r"예보등급\s*○\s*([^<]+?)(?=<)", html, re.DOTALL)
    if summary:
        s = _strip_html(summary.group(1)).strip().replace("&#039;", "'")
        result["예보요약"] = s[:150] if s else None

    # 오늘의 전국 미세먼지 예보 테이블
    table_match = re.search(r"오늘의 전국 미세먼지 예보</caption>.*?<tbody>(.*?)</tbody>", html, re.DOTALL)
    if table_match:
        tbody = table_match.group(1)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL)
        row_map = {"미세먼지": "미세먼지", "PM-10": "PM10", "PM-2.5": "PM25", "오존": "오존"}
        for row in rows:
            cells = re.findall(r"<t[hd][^>]*>([^<]*)</t[hd]>", row)
            if cells and cells[0]:
                first = cells[0].strip()
                if first in row_map:
                    if len(cells) > col_idx:
                        val = _strip_html(cells[col_idx]).strip() or "-"
                        result[row_map[first]] = val
    return result if result else None


def parse_weather_html(html: str) -> dict:
    """날씨누리 단기예보 HTML 파싱. 일별 테이블 데이터 구조화."""
    data = {}
    if not html:
        return data

    m = re.search(r"(\d{4}년 \d{1,2}월 \d{1,2}일 \([^\\)]+\)요일 \d{1,2}:\d{2}) 발표", html)
    if m:
        data["발표시각"] = m.group(1)

    summary_match = re.search(r"□\s*\(종합\)\s*([^○]+?)(?=○|$)", html, re.DOTALL)
    if summary_match:
        s = _strip_html(summary_match.group(1)).strip()
        data["종합"] = re.sub(r"\s+", " ", s)[:200] if s else None

    day_matches = re.findall(r"○\s*\(([^)]+)\)\s*([^○□]+?)(?=○|□|$)", html)
    skip = ("표입니다", "예보요소", "평년(오늘)", "현재위치의")
    day_forecasts = []
    for label, f in day_matches:
        f = _strip_html(f).strip()
        f = re.sub(r"\s+", " ", f)
        if not any(w in f for w in skip) and len(f) > 10 and "날씨" not in label:
            day_forecasts.append(f"{label}: {f[:70]}")
    if day_forecasts:
        data["일별예보"] = " | ".join(day_forecasts[:4])

    # 일별 테이블 파싱 (헤더 + 최저/최고기온 행)
    table_match = re.search(
        r'<table class="table-col whitespaced">(.*?)</table>', html, re.DOTALL
    )
    if table_match:
        tbl = table_match.group(1)
        # 헤더: 예보요소 | 평년 | 어제 | 오늘 | 내일 | 모레 | 글피 (각 th 개별 매칭)
        hdr = re.search(r"<thead>(.*?)</thead>", tbl, re.DOTALL)
        headers = []
        if hdr:
            raw_ths = re.findall(r"<th[^>]*>\s*(?:<[^>]+>)*([^<]+)\s*</th>", hdr.group(1))
            headers = [re.sub(r"\s+", " ", t).strip() for t in raw_ths]
        # 날짜 컬럼 (평년, 어제, 오늘, 내일, 모레, 글피)
        if len(headers) >= 4:
            data["_table_headers"] = headers[:6]

        # 최저기온, 최고기온 행
        for key, label in [("최저기온", "최저기온"), ("최고기온", "최고기온")]:
            row = re.search(
                rf"{re.escape(label)}\s*\(℃\)[^<]*(?:</span>)?</th>\s*(.*?)</tr>",
                tbl, re.DOTALL
            )
            if row:
                vals = re.findall(r"<td[^>]*>([^<]+)</td>", row.group(1))
                vals = [v.strip() for v in vals if v.strip()]
                data[f"_table_{key}"] = vals

    # 파고 (해상 예보) - 첫 번째 파고 행만
    search_html = table_match.group(1) if table_match else html
    wave_row = re.search(r"파고\s*\(m\)[^<]*</th>\s*(.*?)</tr>", search_html, re.DOTALL)
    if wave_row:
        vals = re.findall(r"<td[^>]*>([^<]+)</td>", wave_row.group(1))
        if vals:
            data["파고"] = " / ".join(v.strip() for v in vals[:6] if v.strip())
        if not data.get("파고"):
            data["파고"] = "해상 예보 해당 지역 없음"

    # 기존 호환용 단일 문자열
    if data.get("_table_최저기온"):
        v = data["_table_최저기온"]
        if len(v) >= 6:
            data["최저기온"] = f"오늘 {v[2]}, 내일 {v[3]}, 모레 {v[4]}, 글피 {v[5]}"
        elif len(v) >= 4:
            data["최저기온"] = f"오늘 {v[0]}, 내일 {v[1]}, 모레 {v[2]}, 글피 {v[3]}"
    if data.get("_table_최고기온"):
        v = data["_table_최고기온"]
        if len(v) >= 6:
            data["최고기온"] = f"오늘 {v[2]}, 내일 {v[3]}, 모레 {v[4]}, 글피 {v[5]}"
        elif len(v) >= 4:
            data["최고기온"] = f"오늘 {v[0]}, 내일 {v[1]}, 모레 {v[2]}, 글피 {v[3]}"

    return data


def _range_to_single(value: str, use_low: bool) -> str:
    """'X ~ Y' 형식에서 최저기온은 낮은 값, 최고기온은 높은 값 추출."""
    value = (value or "").strip()
    m = re.match(r"([-\d.]+)\s*~\s*([-\d.]+)", value)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        v = low if use_low else high
        return str(int(v)) if v == int(v) else f"{v:.1f}"
    return value


def _markdown_table(headers: list[str], rows: list[tuple[str, list[str]]]) -> str:
    """마크다운 표 생성. headers=날짜 컬럼, rows=(행이름, 값리스트)."""
    if not headers or not rows:
        return ""
    col_count = min(len(headers), min((len(v) for _, v in rows if v), default=0))
    if col_count == 0:
        return ""
    hdr = ["구분"] + headers[:col_count]
    sep = "| " + " | ".join("---" for _ in hdr) + " |"
    lines = ["| " + " | ".join(hdr) + " |", sep]
    for label, vals in rows:
        cells = (vals + [""] * col_count)[:col_count]
        lines.append("| " + " | ".join([label] + cells) + " |")
    return "\n".join(lines)


def format_weather_response(
    forecast: dict,
    aws: dict | None,
    air: dict | None,
    display_name: str,
) -> str:
    """날씨 정보를 읽기 쉬운 문자열로 포맷. 일별 예보는 표로 제공."""
    lines = [f"## {display_name} 지역 날씨 정보", ""]

    if forecast.get("발표시각"):
        lines.append(f"**발표 시각**: {forecast['발표시각']}")
    if forecast.get("종합"):
        lines.append(f"**종합 예보**: {forecast['종합']}")
    if forecast.get("일별예보"):
        lines.append(f"**일별 예보**: {forecast['일별예보']}")

    # 일별 기온 표 (범위 "X ~ Y" → 최저는 낮은 값, 최고는 높은 값으로 표시)
    hdrs = forecast.get("_table_headers")
    min_vals = forecast.get("_table_최저기온")
    max_vals = forecast.get("_table_최고기온")
    if hdrs and (min_vals or max_vals):
        rows = []
        if min_vals:
            rows.append(("최저기온(℃)", [_range_to_single(v, use_low=True) for v in min_vals]))
        if max_vals:
            rows.append(("최고기온(℃)", [_range_to_single(v, use_low=False) for v in max_vals]))
        tbl = _markdown_table(hdrs, rows)
        if tbl:
            lines.append("")
            lines.append("### 일별 기온 예보")
            lines.append("")
            lines.append(tbl)
            lines.append("")

    if forecast.get("파고"):
        lines.append(f"**파고(m)**: {forecast['파고']}")

    if aws:
        lines.append("")
        lines.append("### 실시간 관측 (AWS)")
        lines.append(f"- **현재 기온**: {aws.get('기온', '-')}℃ (체감 {aws.get('체감온도', '-')}℃)")
        lines.append(f"- **풍향/풍속**: {aws.get('풍향', '-')} 방향, {aws.get('풍속', '-')} m/s")
        lines.append(f"- **습도**: {aws.get('습도', '-')}%")

    if air:
        lines.append("")
        lines.append("### 대기질 예보 (에어코리아)")
        if air.get("예보요약"):
            lines.append(f"- **요약**: {air['예보요약']}")
        if air.get("미세먼지"):
            lines.append(f"- **미세먼지**: {air['미세먼지']}")
        if air.get("PM10"):
            lines.append(f"- **PM-10**: {air['PM10']}")
        if air.get("PM25"):
            lines.append(f"- **PM-2.5(초미세먼지)**: {air['PM25']}")
        if air.get("오존"):
            lines.append(f"- **오존**: {air['오존']}")

    lines.append("")
    lines.append("### 페이지 링크 (클릭하여 열기)")
    for name, url in WEATHER_PAGE_LINKS.items():
        lines.append(f"- {name}: {url}")
    lines.append("")
    lines.append("*시간별 예보*는 날씨누리 메인(https://www.weather.go.kr/w/index.do)에서 지역 검색 후 확인할 수 있습니다.")

    lines.append("")
    lines.append("*(출처: 기상청 날씨누리 https://www.weather.go.kr, 에어코리아 https://www.airkorea.or.kr)*")
    return "\n".join(lines)


def get_korea_weather_info(location: str) -> str:
    """지역명으로 한국 날씨 정보 조회 (단기예보 + AWS 관측 + 대기질 + 이미지 링크)."""
    location = (location or "").strip()
    if not location:
        location = "서울"  # 지역 미지정 시 서울 기준

    result = get_stnid(location)
    if not result:
        supported = ", ".join(sorted(set(LOCATION_TO_STNID.keys()))[:25])
        return f"'{location}'에 대한 지역을 찾을 수 없습니다. 지원 지역 예: {supported} 등"

    stnid, display_name = result
    logger.info(f"get_korea_weather_info: location={location}, stnId={stnid}")

    forecast = {}
    aws_data = None
    air_data = None

    # 1. 단기예보
    html = fetch_page(WEATHER_GO_KR_URL, {"stnId": stnid})
    if html:
        forecast = parse_weather_html(html)

    # 2. AWS 실시간 관측 (풍속, 습도 등)
    aws_station = get_aws_station(location)
    if aws_station:
        aws_html = fetch_page(AWS_OBS_URL)
        if aws_html:
            aws_data = parse_aws_obs(aws_html, aws_station)

    # 3. 에어코리아 대기질 (미세먼지, 오존)
    air_region = get_air_region(location)
    if air_region:
        air_html = fetch_page(AIRKOREA_FULL_URL)
        if air_html:
            air_data = parse_airkorea(air_html, air_region)

    if not forecast and not aws_data and not air_data:
        return "날씨 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."

    return format_weather_response(forecast, aws_data, air_data, display_name)


try:
    mcp = FastMCP(
        name="korea-weather",
        instructions=(
            "한국 지역의 날씨 정보를 기상청 날씨누리와 에어코리아에서 조회합니다. "
            "단기예보, 실시간 관측(기온/풍속/습도), 미세먼지·오존 예보, 페이지 링크를 제공합니다. "
            "지역이 지정되지 않으면 서울 기준으로 조회합니다. "
            "응답에 포함된 '페이지 링크' 섹션을 사용자에게 반드시 그대로 전달하세요."
        ),
    )
    logger.info("Korea Weather MCP server initialized successfully")
except Exception as e:
    logger.error(f"Error: {e}")


@mcp.tool()
def get_korea_weather(location: str = "") -> str:
    """
    한국 지역의 날씨 정보를 상세히 조회합니다.
    location: 조회할 지역명 (예: 서울, 부산, 인천, 대구, 대전, 광주, 수원, 제주 등). 미지정 시 서울 기준.
    return: 단기예보, 실시간 관측(기온/풍향/풍속/습도), 미세먼지·오존 예보, 페이지 링크(URL 포함).
    응답에 포함된 페이지 링크를 사용자에게 반드시 전달하세요.
    """
    logger.info(f"get_korea_weather --> location: {location or '(미지정→서울)'}")
    return get_korea_weather_info(location)


@mcp.tool()
def get_korea_weather_by_stnid(stnid: int) -> str:
    """
    발표관서 코드(stnId)로 한국 날씨 정보를 조회합니다.
    stnid: 108=전국, 109=서울·인천·경기, 105=강원, 131=충북, 133=대전·세종·충남,
           146=전북, 156=광주·전남, 143=대구·경북, 159=부산·울산·경남, 184=제주
    return: 해당 지역의 단기예보 정보
    """
    logger.info(f"get_korea_weather_by_stnid --> stnid: {stnid}")
    html = fetch_page(WEATHER_GO_KR_URL, {"stnId": stnid})
    if not html:
        return "날씨누리(weather.go.kr)에서 데이터를 가져오지 못했습니다."
    forecast = parse_weather_html(html)
    return format_weather_response(forecast, None, None, f"stnId {stnid}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
