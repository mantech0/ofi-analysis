"""
fetch_alpaca_mu.py
Micron (MU) の実板データ (NBBO) を Alpaca IEX フィードで取得する。

取得データ:
  1分足 bid_price / bid_volume / ask_price / ask_volume + 取引価格 (close)
  → OFI_calculator.py にそのまま流し込める形式で出力

設定:
  alpaca_config.py に API Key / Secret を記入してください。
  アカウント無料登録: https://app.alpaca.markets
"""

import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from alpaca_config import ALPACA_API_KEY, ALPACA_API_SECRET

SYMBOL = "MU"
ET = ZoneInfo("America/New_York")


def _check_credentials():
    if "YOUR_API_KEY" in ALPACA_API_KEY:
        raise RuntimeError(
            "\n[ERROR] alpaca_config.py にAPIキーが設定されていません。\n"
            "  1. https://app.alpaca.markets で無料アカウントを作成\n"
            "  2. API Keys → Paper Trading でキーを発行\n"
            "  3. alpaca_config.py の YOUR_API_KEY_HERE と YOUR_API_SECRET_HERE を書き換える"
        )


def fetch_nbbo_1min(days: int = 5) -> pd.DataFrame:
    """
    直近 N 営業日の MU NBBO を 1分足に集約して返す。

    columns: timestamp, price, bid_price, bid_volume, ask_price, ask_volume
    """
    _check_credentials()
    client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)

    et_now = datetime.now(ET)
    end   = et_now.replace(hour=16, minute=0, second=0, microsecond=0)
    start = (et_now - timedelta(days=days + 2)).replace(  # 週末を考慮して余裕を持つ
        hour=9, minute=30, second=0, microsecond=0
    )

    print(f"  期間: {start.strftime('%Y-%m-%d %H:%M')} 〜 {end.strftime('%Y-%m-%d %H:%M')} ET")

    # ── ① Quotes: tick-level NBBO ─────────────────────────────
    print("  Quotes 取得中 (tick データのため少し時間がかかります)...")
    q_req = StockQuotesRequest(
        symbol_or_symbols=SYMBOL, start=start, end=end, feed="iex"
    )
    q_raw = client.get_stock_quotes(q_req).df
    if isinstance(q_raw.index, pd.MultiIndex):
        q_raw = q_raw.xs(SYMBOL, level="symbol")
    q_raw.index = q_raw.index.tz_convert(ET)

    # 1分足に集約: 各分末のスナップショット (=その瞬間の最良気配)
    ba_1min = (
        q_raw[["bid_price", "bid_size", "ask_price", "ask_size"]]
        .resample("1min")
        .last()
        .dropna()
        .rename(columns={"bid_size": "bid_volume", "ask_size": "ask_volume"})
    )

    # ── ② Bars: 1分足取引価格 ─────────────────────────────────
    b_req = StockBarsRequest(
        symbol_or_symbols=SYMBOL,
        timeframe=TimeFrame.Minute,
        start=start, end=end, feed="iex",
    )
    b_raw = client.get_stock_bars(b_req).df
    if isinstance(b_raw.index, pd.MultiIndex):
        b_raw = b_raw.xs(SYMBOL, level="symbol")
    b_raw.index = b_raw.index.tz_convert(ET)

    # ── ③ 結合 ────────────────────────────────────────────────
    df = ba_1min.join(b_raw[["close"]], how="inner").rename(columns={"close": "price"})
    df.index.name = "timestamp"
    df = df.reset_index()

    # 取引時間のみ (9:30-16:00 ET)
    t = df["timestamp"].dt.time
    df = df[t.between(
        pd.Timestamp("09:30").time(),
        pd.Timestamp("16:00").time(),
    )].reset_index(drop=True)

    return df[["timestamp", "price", "bid_price", "bid_volume", "ask_price", "ask_volume"]]


def fetch_mu_daily() -> pd.DataFrame:
    """yfinance で MU 日足 1年分を取得 (日足はyfinanceで十分)"""
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
    print(f"=== Micron ({SYMBOL}) 板データ取得 ===")
    df = fetch_nbbo_1min(days=5)
    df.to_csv("mu_nbbo_1min.csv", index=False)
    print(f"  [OK] {len(df)} 本 → mu_nbbo_1min.csv")
    print(df.head(3).to_string())
