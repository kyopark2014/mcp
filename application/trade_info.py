from __future__ import annotations

import logging
import sys
import os
import io
import boto3
import uuid
import json
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

from urllib import parse
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Tuple
from matplotlib.patches import Rectangle
from typing import cast

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("loader")

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")
    
def load_config():
    config = None
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

region = config.get("region", "ap-northeast-2")
projectName = config.get("projectName", "es")

s3_prefix = "docs"
s3_image_prefix = "images"
model_name = "Claude 4.0 Sonnet"
s3_bucket = config.get("s3_bucket")
path = config.get('sharing_url', '')

# Simple mapping: subject (company name) -> KRX ticker (yfinance format)
# Add more companies here if needed.
SUBJECT_TO_TICKER: Dict[str, str] = {
    "SK텔레콤": "017670.KS",  # SK텔레콤 Corp
    "CJ CGV": "079160.KS",  # CJ CGV Corp
    "CGV": "079160.KS",  # CGV Corp
    "네이버": "035420.KS",  # NAVER Corp
    "NAVER": "035420.KS",  # NAVER Corp    
    "카카오": "035720.KS",  # Kakao Corp
    "KT": "030200.KS",  # KT Corp   
    "대한항공": "003490.KS",  # 대한항공 Corp
    "아시아나항공": "020560.KS",  # 아시아나항공 Corp
    "호텔신라": "008770.KS",  # 호텔신라 Corp
    "현대차": "005380.KS",  # 현대차 Corp
    "현대모비스": "012330.KS",  # 현대모비스 Corp
    "현대오토에버": "307950.KS",  # 현대오토에버 Corp
    "SK이노베이션": "096770.KS",  # SK이노베이션 Corp
    "SK하이닉스": "000660.KS",  # SK하이닉스 Corp
    "SK Hynix": "000660.KS",  # SK Hynix Corp
    "LG전자": "066570.KS",  # LG 전자 Corp
    "LG Electronics": "066570.KS",  # LG Electronics Corp    
    "LG이노텍": "011070.KS",  # LG 이노텍 Corp
    "LG Innotek": "011070.KS",  # LG Innotek Corp
    "LG에너지솔루션": "373220.KS",  # LG 에너지솔루션 Corp
    "LG디스플레이": "034220.KS",  # LG 디스플레이 Corp
    "HD현대일렉트릭": "267260.KS",  # HD 현대일렉트릭 Corp
    "두산": "000150.KS",  # 두산 Corp
    "GS": "078930.KS",  # GS Corp
    "S-Oil": "010950.KS",  # S-Oil Corp
    "한국전력": "015760.KS",  # 한국전력 Corp
    "삼성전자": "005930.KS",  # 삼성전자 Corp
    "삼성SDI": "006400.KS",  # 삼성SDI Corp,
    "효성중공업": "298040.KS",  # 효성중공업 Corp
    "한화오션": "042660.KS",  # 한화오션 Corp
    "한화시스템": "272210.KS",  # 한화시스템 Corp
    "농심": "004370.KS",  # 농심 Corp
    "동원": "009150.KS",  # 동원 Corp
    "SK": "034730.KS",  # SK Corp
}

stocks = {}

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

def upload_to_s3(file_bytes, file_name):
    """
    Upload a file to S3 and return the URL
    """
    try:
        s3_client = boto3.client(
            service_name='s3',
            region_name=region,
        )

        content_type = get_contents_type(file_name)       
        logger.info(f"content_type: {content_type}") 

        if content_type == "image/jpeg" or content_type == "image/png":
            s3_key = f"{s3_image_prefix}/{file_name}"
        else:
            s3_key = f"{s3_prefix}/{file_name}"
        
        user_meta = {  # user-defined metadata
            "content_type": content_type,
            "model_name": model_name
        }
        
        response = s3_client.put_object(
            Bucket=s3_bucket, 
            Key=s3_key, 
            ContentType=content_type,
            Metadata = user_meta,
            Body=file_bytes            
        )
        logger.info(f"upload response: {response}")

        #url = f"https://{s3_bucket}.s3.amazonaws.com/{s3_key}"
        url = path+'/'+s3_image_prefix+'/'+parse.quote(file_name)
        return url
    
    except Exception as e:
        err_msg = f"Error uploading to S3: {str(e)}"
        logger.info(f"{err_msg}")
        return None

def resolve_ticker(subject: str) -> str:
    """Resolve input into a yfinance-style ticker.

    Order of resolution:
    1) Exact company name match in SUBJECT_TO_TICKER (with/without spaces)
    2) Already a yfinance-style ticker (e.g., 035420.KS / 000660.KQ)
    3) Fallback: search via search_ticker_candidates and use the first match
    """
    # 1) Company name -> ticker mapping (exact match)
    if subject in SUBJECT_TO_TICKER:
        return SUBJECT_TO_TICKER[subject]
    
    # 1-2) Try matching without spaces (e.g., "LG 에너지솔루션" -> "LG에너지솔루션")
    subject_no_space = subject.replace(" ", "")
    if subject_no_space in SUBJECT_TO_TICKER:
        return SUBJECT_TO_TICKER[subject_no_space]
    
    # 1-3) Try matching with normalized keys (remove spaces from both)
    for key, ticker in SUBJECT_TO_TICKER.items():
        if key.replace(" ", "") == subject_no_space:
            return ticker

    # 2) If it's already a yfinance-style ticker, accept as-is
    s = (subject or "").strip().upper()
    if len(s) >= 9 and s[:6].isdigit() and s[6] == '.' and s[7:] in {"KS", "KQ"}:
        return s

    # 3) Fallback: try searching candidates
    try:
        candidates = search_ticker_candidates(subject, limit=1)
    except Exception as exc:
        raise ValueError(f"Failed to resolve ticker for input {subject!r}: {exc}") from exc

    if candidates:
        return candidates[0].get("ticker", "") or (
            f"{candidates[0].get('itemcode', '')}"  # very defensive fallback
        )

    raise ValueError(
        f"Unknown subject: {subject!r}. Provide a known company name or a valid ticker."
    )

def _ticker_to_itemcode(ticker: str) -> str:
    # Example: 035420.KS -> 035420
    return ticker.split(".")[0]

def generate_short_uuid(length: int = 8) -> str:
    """Generate a short UUID string."""
    full_uuid = uuid.uuid4().hex
    return full_uuid[:length]


def search_ticker_candidates(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """Search ticker candidates by partial company name or 6-digit item code.

    Return format: [{ company_name, itemcode, market, ticker }]
    ticker follows yfinance format (e.g., 035420.KS or 000660.KQ).
    """
    try:
        import FinanceDataReader as fdr  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "FinanceDataReader is not installed. Install with: pip install finance-datareader"
        ) from exc

    try:
        df = fdr.StockListing("KRX")
    except Exception as exc:
        raise RuntimeError(f"FDR StockListing(KRX) call failed: err={exc}") from exc

    if df is None or getattr(df, "empty", True):
        return []

    # Defensive access to columns
    name_col = "Name"
    symbol_col = "Symbol"
    market_col = "Market"

    q = (query or "").strip()
    if not q:
        return []

    try:
        name_mask = df[name_col].astype(str).str.contains(q, case=False, na=False)
    except Exception:
        name_mask = False
    try:
        symbol_mask = df[symbol_col].astype(str).str.contains(q, na=False)
    except Exception:
        symbol_mask = False

    try:
        sub = df[name_mask | symbol_mask].copy()
    except Exception:
        return []

    def market_to_suffix(market: str) -> str:
        m = (market or "").upper()
        if "KOSDAQ" in m:
            return ".KQ"
        # Default: treat as KOSPI
        return ".KS"

    results: List[Dict[str, str]] = []
    for _, row in sub.iterrows():
        try:
            name_v = cast(str, row.get(name_col, ""))
            code_v = str(row.get(symbol_col, "")).zfill(6)
            market_v = cast(str, row.get(market_col, ""))
            ticker_v = f"{code_v}{market_to_suffix(market_v)}"
        except Exception:
            continue
        results.append(
            {
                "company_name": name_v,
                "itemcode": code_v,
                "market": market_v,
                "ticker": ticker_v,
            }
        )

    return results[: max(0, limit)]

def _fetch_fdr(itemcode: str, period: int = 30) -> List[Dict[str, object]]:
    """Fetch daily candles for the last ~period days using FinanceDataReader."""
    try:
        import FinanceDataReader as fdr  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "FinanceDataReader is not installed. Install with: pip install finance-datareader"
        ) from exc

    end_dt = datetime.now(timezone.utc).date()
    # Query period days (add buffer to account for non-trading days)
    start_dt = end_dt - timedelta(days=period + 5)

    try:
        df = fdr.DataReader(itemcode, start_dt.isoformat(), end_dt.isoformat())
    except Exception as exc:
        raise RuntimeError(
            f"FDR DataReader call failed: code={itemcode}, err={exc}"
        ) from exc

    if df is None or df.empty:
        logger.info(
            f"FDR DataFrame empty: code={itemcode}, start={start_dt}, end={end_dt}"
        )
        return []

    logger.info(
        f"FDR DataFrame shape={getattr(df, 'shape', None)}, columns={list(getattr(df, 'columns', []))}"
    )

    series: List[Dict[str, object]] = []
    for idx, row in df.iterrows():
        try:
            ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
        except Exception:
            continue
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        time_iso = ts.astimezone(timezone.utc).isoformat()

        def _get_float(name: str):
            v = row.get(name)
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        def _get_int(name: str):
            v = row.get(name)
            try:
                return int(v) if v is not None else None
            except Exception:
                return None

        series.append(
            {
                "time": time_iso,
                "open": _get_float("Open"),
                "high": _get_float("High"),
                "low": _get_float("Low"),
                "close": _get_float("Close"),
                "volume": _get_int("Volume"),
            }
        )

    # Keep only the last period calendar days
    cutoff = datetime.now(timezone.utc) - timedelta(days=period)
    before_len = len(series)
    series = [p for p in series if p["time"] and datetime.fromisoformat(p["time"]) >= cutoff]
    logger.info(f"FDR filtered last {period} days: {before_len} -> {len(series)} rows")
    return series

def get_stock_trend(company_name: str = "NAVER", period: int = 30) -> Dict[str, object]:
    """
    Return last ~period days price trend as a dict. Uses FinanceDataReader only.
    company_name: the company name to get stock trend
    period: the period to get stock trend
    return: the price trend of the given company as a dict
    """
    ticker = resolve_ticker(company_name)
    itemcode = _ticker_to_itemcode(ticker)

    logger.info(f"Fetching trend for {period} days via FDR: subject={company_name}, itemcode={itemcode}")
    series_fdr = _fetch_fdr(itemcode, period)

    points: List[Dict[str, Optional[object]]] = []
    if series_fdr:
        prev_close: Optional[float] = None
        for r in series_fdr:
            close_v = r.get("close")
            change_v: Optional[float] = None
            change_pct_v: Optional[float] = None
            if isinstance(close_v, (int, float)) and prev_close is not None:
                change_v = float(close_v) - float(prev_close)
                if prev_close != 0:
                    change_pct_v = (change_v / float(prev_close)) * 100.0
            points.append({**r, "change": change_v, "change_percent": change_pct_v})
            if isinstance(close_v, (int, float)):
                prev_close = float(close_v)

    if not points:
        logger.info("FDR returned no rows for last month trend.")

    result: Dict[str, object] = {
        "company_name": company_name,
        "ticker": ticker,
        "currency": "KRW",
        "range": "1mo",
        "interval": "1d",
        "points": points,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    stocks[f"{company_name}_{period}"] = result

    return result

def get_expected_high_low(company_name: str = "NAVER", period: int = 30) -> Tuple[str, str]:
    """
    Return last ~period days price trend with expected high and low as a dict. Uses FinanceDataReader only.
    company_name: the company name to get stock trend
    period: the period to get stock trend
    return: the price trend of the given company as a dict
    """

    trend_dict = stocks.get(f"{company_name}_{period}")
    if trend_dict is None:
        trend_dict = get_stock_trend(company_name, period)
        stocks[f"{company_name}_{period}"] = trend_dict
    
    points = trend_dict.get("points", [])
    if not points:
        raise ValueError("trend does not contain points data.")

    # Prepare data similar to draw_stock_trend
    df = pd.DataFrame(points)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)  # Sort by time
    
    # Filter out None values for close price
    df_clean = df[df['close'].notna()].copy()
    
    if len(df_clean) == 0:
        raise ValueError("No valid close price data in points.")
    
    # Get closing prices as array
    close_prices = df_clean['close'].values
    
    # Find and highlight maximum and minimum closing prices (highest and lowest)
    max_idx = pd.Series(close_prices).idxmax()
    min_idx = pd.Series(close_prices).idxmin()
    
    max_close = close_prices[max_idx]
    min_close = close_prices[min_idx]
    
    # Get current (last) closing price for percentage calculation
    current_close = close_prices[-1]
    
    # Calculate percentage from current closing price
    max_percent = ((max_close - current_close) / current_close) * 100 if current_close != 0 else 0
    min_percent = ((min_close - current_close) / current_close) * 100 if current_close != 0 else 0

    expected_high = f"{max_percent:+.2f}%"
    expected_low = f"{min_percent:+.2f}%"

    return expected_high, expected_low

def is_lower_than_ma20(company_name: str = "NAVER", period: int = 30) -> bool:
    """
    Return True if the current closing price is lower than the 20-day moving average, False otherwise. Uses FinanceDataReader only.
    company_name: the company name to get stock trend
    period: the period to get stock trend
    return: True if the current closing price is lower than the 20-day moving average, False otherwise
    """

    trend_dict = stocks.get(f"{company_name}_{period}")
    if trend_dict is None:
        trend_dict = get_stock_trend(company_name, period)
        stocks[f"{company_name}_{period}"] = trend_dict
    
    points = trend_dict.get("points", [])
    if not points:
        raise ValueError("trend does not contain points data.")

    # Prepare data similar to draw_stock_trend
    df = pd.DataFrame(points)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)  # Sort by time

    df['ma20'] = df['close'].rolling(window=20, min_periods=1).mean()  # 20-day moving average
    
    # Filter out None values for close price
    df_clean = df[df['close'].notna()].copy()
    
    if len(df_clean) == 0:
        raise ValueError("No valid close price data in points.")
    
    # Get closing prices as array
    close_prices = df_clean['close'].values
    
    # Get current (last) closing price for percentage calculation
    current_close = close_prices[-1]

    return True if current_close < df['ma20'].values[-1] else False
    
def draw_stock_trend(trend: Dict[str, object]) -> Dict[str, List[str]]:
    """
    Draw graphs of the given trend.
    trend: the trend dictionary of the given company (containing points, company_name, ticker, etc.)
    return: dictionary with 'path' key containing a list of image file paths for the graphs
    """
    logger.info(f"draw_stock_trend --> trend: {trend}")

    image_url = []

    ###########################################################################################
    # Graph showing stock trend (candlestick chart)
    ###########################################################################################
    try:
        # Try common Korean fonts on macOS
        korean_fonts = ['AppleGothic', 'NanumGothic', 'Malgun Gothic', 'Apple SD Gothic Neo']
        font_found = False
        for font_name in korean_fonts:
            try:
                plt.rcParams['font.family'] = font_name
                plt.rcParams['axes.unicode_minus'] = False  # Fix minus sign display
                font_found = True
                logger.info(f"Korean font set to: {font_name}")
                break
            except Exception:
                continue
        if not font_found:
            # Fallback: set to any available font
            plt.rcParams['axes.unicode_minus'] = False
            logger.warning("Could not set Korean font, using default font")
    except Exception as exc:
        logger.warning(f"Font setting failed: {exc}, continuing with default font")
        plt.rcParams['axes.unicode_minus'] = False

    points = trend.get("points", [])
    if not points:
        raise ValueError("trend does not contain points data.")

    company_name = trend.get("company_name", "Stock")
    ticker = trend.get("ticker", "")

    # Prepare data
    df = pd.DataFrame(points)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)  # Sort by time
    
    # Calculate moving averages for trend analysis
    df['ma5'] = df['close'].rolling(window=5, min_periods=1).mean()  # 5-day moving average
    df['ma20'] = df['close'].rolling(window=20, min_periods=1).mean()  # 20-day moving average

    # Draw candlestick graph
    fig, ax = plt.subplots(figsize=(14, 7))

    width = 0.6

    for idx, row in df.iterrows():
        date = mdates.date2num(row['time'])
        open_price = row['open']
        close_price = row['close']
        high_price = row['high']
        low_price = row['low']
        
        # Check for None values
        if any(v is None for v in [open_price, close_price, high_price, low_price]):
            continue
        
        # Determine color (red for up, blue for down)
        color = 'red' if close_price >= open_price else 'blue'
        
        # High-low line (wick)
        ax.plot([date, date], [low_price, high_price], color=color, linewidth=1)
        
        # Open-close box (body)
        body_height = abs(close_price - open_price)
        body_bottom = min(open_price, close_price)
        rect = Rectangle((date - width/2, body_bottom), width, body_height, 
                         facecolor=color, edgecolor=color, linewidth=1)
        ax.add_patch(rect)
    
    # Draw moving average lines
    if len(df) > 0:
        dates = [mdates.date2num(t) for t in df['time']]
        ax.plot(dates, df['ma5'], color='orange', linewidth=2, label='MA5', linestyle='-', alpha=0.8)
        ax.plot(dates, df['ma20'], color='green', linewidth=2, label='MA20', linestyle='-', alpha=0.8)

    # Configure graph
    if len(df) > 0:
        ax.set_xlim(mdates.date2num(df['time'].min()) - 1, mdates.date2num(df['time'].max()) + 1)
        ax.set_ylim(df['low'].min() - 200, df['high'].max() + 200)

    # Format X-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.xticks(rotation=45, ha='right')

    # Labels and title
    title = f'{company_name} Stock Trend - Candlestick Chart'
    if ticker:
        title += f' ({ticker})'
    ax.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax.set_ylabel('Price (KRW)', fontsize=12, fontweight='bold')
    ax.set_title(title, fontsize=14, fontweight='bold')

    # Add grid
    ax.grid(True, alpha=0.3)

    # Add legend
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    legend_elements = [
        Patch(facecolor='red', edgecolor='red', label='Up'),
        Patch(facecolor='blue', edgecolor='blue', label='Down'),
        Line2D([0], [0], color='orange', linewidth=2, label='MA5 (5-day)'),
        Line2D([0], [0], color='green', linewidth=2, label='MA20 (20-day)')
    ]
    ax.legend(handles=legend_elements, loc='upper left')

    plt.tight_layout()

    # Save to file
    image_name = generate_short_uuid() + '.png'

    if path:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)

        url = upload_to_s3(buf.getvalue(), image_name)
        if url:
            image_url.append(url)
            logger.info(f"image_url: {image_url}")

    else:
        os.makedirs('contents', exist_ok=True)
        file_path = os.path.join('contents', image_name)
        
        plt.savefig(file_path, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig)
            
        image_url.append(os.path.abspath(file_path))
        logger.info(f"image_url: {image_url}")

    ###########################################################################################
    # Graph showing daily price increase and decrease percentages
    ###########################################################################################
    df = pd.DataFrame(points)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)  # Sort by time
    
    # Create a new figure for the bar chart
    fig2, ax2 = plt.subplots(figsize=(14, 7))
    
    # Prepare data for bar chart
    if len(df) > 0 and 'change_percent' in df.columns:
        dates = df['time']
        change_percent = df['change_percent'].fillna(0).values
        
        # Convert dates to matplotlib date numbers (same as candlestick chart)
        date_nums = [mdates.date2num(d) for d in dates]
        width_days = 0.6  # Width in days (same as candlestick chart width=0.6)
        
        # Determine colors: red for positive (increase), blue for negative (decrease)
        colors = ['red' if x >= 0 else 'blue' for x in change_percent]
        
        # Draw bar chart using date numbers
        bars = ax2.bar(date_nums, change_percent, color=colors, alpha=0.7, width=width_days)
        
        # Add percentage labels on bars
        for i, (bar, val) in enumerate(zip(bars, change_percent)):
            if not pd.isna(val) and val != 0:
                label_text = f'{val:.2f}%'
                # Position text above bar for positive values, below for negative values
                if val >= 0:
                    ax2.text(bar.get_x() + bar.get_width()/2, val,
                            label_text, ha='center', va='bottom', fontsize=12, fontweight='bold')
                else:
                    ax2.text(bar.get_x() + bar.get_width()/2, val,
                            label_text, ha='center', va='top', fontsize=12, fontweight='bold')
        
        # Set X-axis limits to match candlestick chart
        ax2.set_xlim(mdates.date2num(df['time'].min()) - 1, mdates.date2num(df['time'].max()) + 1)
        
        # Format X-axis with dates (same format as candlestick chart)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        # Add zero line
        ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        
        # Labels and title
        title2 = f'{company_name} Daily Price Change Percentage'
        if ticker:
            title2 += f' ({ticker})'
        ax2.set_xlabel('Date', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Change Percentage (%)', fontsize=12, fontweight='bold')
        ax2.set_title(title2, fontsize=14, fontweight='bold')
        
        # Add grid
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Add legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='red', edgecolor='red', label='Increase'),
            Patch(facecolor='blue', edgecolor='blue', label='Decrease')
        ]
        ax2.legend(handles=legend_elements, loc='upper right')
    
    plt.tight_layout()

    # Save to file
    image_name = generate_short_uuid() + '.png'

    if path:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig2)
        buf.seek(0)

        url = upload_to_s3(buf.getvalue(), image_name)
        if url:
            image_url.append(url)
            logger.info(f"image_url: {image_url}")

    else:
        os.makedirs('contents', exist_ok=True)
        file_path = os.path.join('contents', image_name)
        plt.savefig(file_path, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig2)
        image_url.append(os.path.abspath(file_path))

    # Draw stock trend graph based on closing price
    df = pd.DataFrame(points)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)  # Sort by time
    
    # Draw line graph based on closing price with daily change
    fig3, ax3 = plt.subplots(figsize=(14, 7))

    # Filter out None values for close price
    df_clean = df[df['close'].notna()].copy()
    
    if len(df_clean) > 0:
        # Convert dates to matplotlib date numbers
        dates = [mdates.date2num(t) for t in df_clean['time']]
        close_prices = df_clean['close'].values
        
        # Fill NaN values: use close price for high/low if missing
        high_prices = df_clean['high'].fillna(df_clean['close']).values
        low_prices = df_clean['low'].fillna(df_clean['close']).values
        
        # Draw filled area between high and low prices
        ax3.fill_between(dates, low_prices, high_prices, 
                         color='lightgray', alpha=0.3, label='High-Low Range', zorder=1)
        
        # Draw line graph for closing price
        ax3.plot(dates, close_prices, color='blue', linewidth=2, label='Closing Price', marker='o', markersize=4, zorder=3)
        
        # Find and highlight maximum and minimum closing prices (highest and lowest)
        max_idx = pd.Series(close_prices).idxmax()
        min_idx = pd.Series(close_prices).idxmin()
        
        max_close = close_prices[max_idx]
        min_close = close_prices[min_idx]
        max_date = dates[max_idx]
        min_date = dates[min_idx]
        
        # Get current (last) closing price for percentage calculation
        current_close = close_prices[-1]
        
        # Calculate percentage from current closing price
        max_percent = ((max_close - current_close) / current_close) * 100 if current_close != 0 else 0
        min_percent = ((min_close - current_close) / current_close) * 100 if current_close != 0 else 0
        logger.info(f"max_percent: {max_percent}")
        logger.info(f"min_percent: {min_percent}")
        
        # Highlight maximum closing price (highest price)
        ax3.plot(max_date, max_close, marker='^', markersize=12, color='darkred', 
               markeredgecolor='white', markeredgewidth=2, zorder=5, label='Max Price')
        ax3.annotate(f'Max: {max_percent:+.2f}%',
                   xy=(max_date, max_close),
                   xytext=(10, 10), textcoords='offset points',
                   fontsize=15, fontweight='bold', color='darkred',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                   arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0', color='darkred'))
        
        # Highlight minimum closing price (lowest price)
        ax3.plot(min_date, min_close, marker='v', markersize=12, color='darkblue',
               markeredgecolor='white', markeredgewidth=2, zorder=5, label='Min Price')
        ax3.annotate(f'Min: {min_percent:+.2f}%',
                   xy=(min_date, min_close),
                   xytext=(10, -20), textcoords='offset points',
                   fontsize=15, fontweight='bold', color='darkblue',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lightblue', alpha=0.7),
                   arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0', color='darkblue'))
        
        # Configure Y-axis to show closing price, high, and low
        all_values = list(close_prices) + list(high_prices) + list(low_prices)
        if len(all_values) > 0:
            min_val_plot = min(all_values)
            max_val_plot = max(all_values)
            ax3.set_ylim(min_val_plot * 0.98, max_val_plot * 1.02)
        
        ax3.set_xlim(min(dates) - 1, max(dates) + 1)
        ax3.set_ylabel('Price (KRW)', fontsize=12, fontweight='bold', color='blue')
        ax3.tick_params(axis='y', labelcolor='blue')

    # Format X-axis
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax3.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.xticks(rotation=45, ha='right')

    # Labels and title
    title3 = f'{company_name} Stock Trend - Closing Price & Daily Change'
    if ticker:
        title3 += f' ({ticker})'
    ax3.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax3.set_title(title3, fontsize=14, fontweight='bold')

    # Add grid
    ax3.grid(True, alpha=0.3)
    
    # Add legend
    ax3.legend(loc='upper left')
    
    plt.tight_layout()

    # Save to file
    image_name = generate_short_uuid() + '.png'    

    if path:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig3)
        buf.seek(0)

        url = upload_to_s3(buf.getvalue(), image_name)
        if url:
            image_url.append(url)
            logger.info(f"image_url: {image_url}")
        else:
            logger.error(f"Failed to upload image to S3: {image_name}")

    else:
        os.makedirs('contents', exist_ok=True)
        file_path = os.path.join('contents', image_name)
        
        plt.savefig(file_path, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig3)

        image_url.append(os.path.abspath(file_path))
        logger.info(f"image_url: {image_url}")

    return {
        "path": image_url
    }