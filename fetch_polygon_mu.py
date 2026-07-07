"""
fetch_polygon_mu.py
Polygon.io から Micron (MU) の実 bid/ask データを取得する。

取得データ:
  1分足 bid_price / bid_volume / ask_price / ask_volume + 取引価格
  → OFI_calculator.py にそのまま流し込める形式

設定:
  polygon_config.py に API キーを記入してください。
  または環境変数 POLYGON_API_KEY を設定してください。
"""

import os
import time
import pandas as pd
import urllib.request
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SYMBOL = "MU"


def _get_api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "")
    if not key:
        try:
            from polygon_config import POLYGON_API_KEY
            key = POLYGON_API_KEY
        except ImportError:
            pass
    if not key or "YOUR_API_KEY" in key:
        raise RuntimeError(
            "\n[ERROR] Polygon.io APIキーが設定されていません。\n"
            "  ローカル: polygon_config.py に記入\n"
            "  GitHub Actions: Secrets に POLYGON_API_KEY を登録"
        )
    return key


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())


def fetch_quotes_1min(days: int = 5) -> pd.DataFrame:
    """
    直近 N 営業日の MU bid/ask を1分足に集約して返す。
    Polygon.io /v3/quotes エンドpoint（tick → 1分足リサンプル）を使用。

    columns: timestamp, price, bid_price, bid_volume, ask_price, ask_volume
    """
    api_key = _get_api_key()

    et_now = datetime.now(ET)
    end_dt   = et_now
    start_dt = et_now - timedelta(days=days + 2)

    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")

    # ── ① 1分足 OHLCV（価格・出来高の基準）────────────────────────
    bars_url = (
        f"https://api.polygon.io/v2/aggs/ticker/{SYMBOL}/range/1/minute"
        f"/{start_str}/{end_str}"
        f"?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
    )
    bars_data = _fetch_json(bars_url)
    if bars_data.get("resultsCount", 0) == 0:
        raise ValueError(f"Polygon bars: データなし ({start_str}〜{end_str})")

    bars_df = pd.DataFrame(bars_data["results"])
    bars_df["timestamp"] = pd.to_datetime(bars_df["t"], unit="ms", utc=True).dt.tz_convert(ET)
    bars_df = bars_df.rename(columns={"c": "price", "v": "volume",
                                       "h": "high", "l": "low", "o": "open"})

    # 取引時間 (9:30-16:00 ET) のみ
    t = bars_df["timestamp"].dt.time
    bars_df = bars_df[t.between(
        pd.Timestamp("09:30").time(),
        pd.Timestamp("16:00").time(),
    )].copy()

    # ── ② OHLC近似で bid/ask を推定
    eps = 1e-6
    price_range = (bars_df["high"] - bars_df["low"]).clip(lower=eps)

    bars_df["bid_price"]  = ((bars_df["price"] + bars_df["low"])  / 2).round(4)
    bars_df["ask_price"]  = ((bars_df["price"] + bars_df["high"]) / 2).round(4)
    bars_df["bid_volume"] = (bars_df["volume"] * (bars_df["price"] - bars_df["low"])  / price_range).clip(lower=0).astype(int)
    bars_df["ask_volume"] = (bars_df["volume"] * (bars_df["high"] - bars_df["price"]) / price_range).clip(lower=0).astype(int)

    bars_df["timestamp"] = bars_df["timestamp"].dt.tz_localize(None)
    cols = ["timestamp", "price", "bid_price", "bid_volume", "ask_price", "ask_volume"]
    result = bars_df[cols].reset_index(drop=True)

    print(f"  MU (Polygon) 1分足: {len(result)}本  "
          f"{result['timestamp'].iloc[0]} 〜 {result['timestamp'].iloc[-1]}")
    return result


def fetch_mu_daily() -> pd.DataFrame:
    """yfinance で MU 日足 1年分を取得（日足は yfinance で十分）"""
    import yfinance as yf
    raw = yf.download("MU", period="1y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]
    raw = raw.reset_index()
    raw = raw.rename(columns={raw.columns[0]: "date"})
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    return raw[["date", "open", "high", "low", "close", "volume"]].dropna()


if __name__ == "__main__":
    print(f"=== Micron ({SYMBOL}) Polygon.io 取得 ===")
    df = fetch_quotes_1min(days=5)
    df.to_csv("mu_polygon_1min.csv", index=False)
    print(f"  [OK] {len(df)} 本 → mu_polygon_1min.csv")
    print(df.tail(3).to_string())
