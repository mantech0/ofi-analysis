"""
fetch_alpaca_mu.py
Micron (MU) の 1分足データを Alpaca から取得する。

戦略:
  - 当日分: 実 tick NBBO を1分足にリサンプルして使用（精度優先）
  - 過去日分: 1分足 Bars + OHLC近似（速度優先）
  → 合計 5営業日分を OFI_calculator.py に流せる形式で返す
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SYMBOL = "MU"
ET = ZoneInfo("America/New_York")


def _get_client() -> StockHistoricalDataClient:
    key    = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_API_SECRET", "")
    if not key or not secret:
        try:
            from alpaca_config import ALPACA_API_KEY, ALPACA_API_SECRET
            key, secret = ALPACA_API_KEY, ALPACA_API_SECRET
        except ImportError:
            pass
    if not key or "YOUR_API_KEY" in key:
        raise RuntimeError(
            "\n[ERROR] Alpaca APIキーが設定されていません。\n"
            "  ローカル: alpaca_config.py に記入\n"
            "  GitHub Actions: Secrets に ALPACA_API_KEY / ALPACA_API_SECRET を登録"
        )
    return StockHistoricalDataClient(key, secret)


def _market_time(dt: datetime) -> bool:
    t = dt.time()
    return pd.Timestamp("09:30").time() <= t <= pd.Timestamp("16:00").time()


def _bars_to_ofi_format(b_raw: pd.DataFrame) -> pd.DataFrame:
    """1分足Bars DataFrame → OHLC近似でbid/askを推定して返す"""
    df = b_raw.copy()
    eps = 1e-6
    rng = (df["high"] - df["low"]).clip(lower=eps)
    df["price"]      = df["close"]
    df["bid_price"]  = ((df["close"] + df["low"])  / 2).round(4)
    df["ask_price"]  = ((df["close"] + df["high"]) / 2).round(4)
    df["bid_volume"] = (df["volume"] * (df["close"] - df["low"])  / rng).clip(lower=0).astype(int)
    df["ask_volume"] = (df["volume"] * (df["high"] - df["close"]) / rng).clip(lower=0).astype(int)
    return df[["price", "bid_price", "bid_volume", "ask_price", "ask_volume"]]


def fetch_nbbo_1min(days: int = 5) -> pd.DataFrame:
    """
    直近 N 営業日の MU データを1分足で返す。
    当日: 実tick NBBO、過去日: 1分足Bars + OHLC近似。

    columns: timestamp, price, bid_price, bid_volume, ask_price, ask_volume
    """
    client = _get_client()
    et_now = datetime.now(ET)
    today_open  = et_now.replace(hour=9,  minute=30, second=0, microsecond=0)
    today_close = et_now.replace(hour=16, minute=0,  second=0, microsecond=0)
    hist_start  = (et_now - timedelta(days=days + 2)).replace(
        hour=9, minute=30, second=0, microsecond=0
    )

    # ── ① 過去日分: 1分足Bars（速い）────────────────────────────
    print(f"  過去Bars取得中: {hist_start.strftime('%Y-%m-%d')} 〜 前日...")
    b_req = StockBarsRequest(
        symbol_or_symbols=SYMBOL,
        timeframe=TimeFrame.Minute,
        start=hist_start,
        end=today_open,
        feed="iex",
    )
    b_raw = client.get_stock_bars(b_req).df
    if isinstance(b_raw.index, pd.MultiIndex):
        b_raw = b_raw.xs(SYMBOL, level="symbol")
    b_raw.index = b_raw.index.tz_convert(ET)
    b_raw = b_raw[b_raw.index.map(_market_time)]

    hist_df = _bars_to_ofi_format(b_raw)
    hist_df.index.name = "timestamp"
    hist_df = hist_df.reset_index()
    hist_df["timestamp"] = hist_df["timestamp"].dt.tz_localize(None)
    print(f"  → {len(hist_df)}本取得")

    # ── ② 当日分: 実tick NBBO（精度優先）────────────────────────
    today_end = min(et_now, today_close)
    is_market_open = today_open <= et_now <= today_close
    today_df = pd.DataFrame()

    if is_market_open or et_now > today_open:
        print(f"  当日Quotes取得中: {today_open.strftime('%H:%M')} 〜 {today_end.strftime('%H:%M')} ET...")
        try:
            q_req = StockQuotesRequest(
                symbol_or_symbols=SYMBOL,
                start=today_open,
                end=today_end,
                feed="iex",
            )
            q_raw = client.get_stock_quotes(q_req).df
            if isinstance(q_raw.index, pd.MultiIndex):
                q_raw = q_raw.xs(SYMBOL, level="symbol")
            q_raw.index = q_raw.index.tz_convert(ET)

            ba_1min = (
                q_raw[["bid_price", "bid_size", "ask_price", "ask_size"]]
                .resample("1min").last().dropna()
                .rename(columns={"bid_size": "bid_volume", "ask_size": "ask_volume"})
            )

            # 当日Barsで価格を補完
            b_today_req = StockBarsRequest(
                symbol_or_symbols=SYMBOL,
                timeframe=TimeFrame.Minute,
                start=today_open, end=today_end, feed="iex",
            )
            b_today = client.get_stock_bars(b_today_req).df
            if isinstance(b_today.index, pd.MultiIndex):
                b_today = b_today.xs(SYMBOL, level="symbol")
            b_today.index = b_today.index.tz_convert(ET)

            today_merged = ba_1min.join(b_today[["close"]], how="inner").rename(columns={"close": "price"})
            today_merged = today_merged[today_merged.index.map(_market_time)]
            today_merged.index.name = "timestamp"
            today_merged = today_merged.reset_index()
            today_merged["timestamp"] = today_merged["timestamp"].dt.tz_localize(None)
            today_df = today_merged[["timestamp", "price", "bid_price", "bid_volume", "ask_price", "ask_volume"]]
            print(f"  → 当日実板 {len(today_df)}本取得")
        except Exception as e:
            print(f"  当日Quotes取得失敗（OHLC近似にフォールバック）: {e}")

    # ── ③ 結合 ────────────────────────────────────────────────────
    if today_df.empty:
        result = hist_df
    else:
        result = pd.concat([hist_df, today_df], ignore_index=True)

    result = result.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    print(f"  MU (Alpaca) 合計: {len(result)}本  "
          f"{result['timestamp'].iloc[0]} 〜 {result['timestamp'].iloc[-1]}")
    return result[["timestamp", "price", "bid_price", "bid_volume", "ask_price", "ask_volume"]]


def fetch_mu_daily() -> pd.DataFrame:
    """yfinance で MU 日足 1年分を取得"""
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
    print(f"=== Micron ({SYMBOL}) Alpaca 取得 ===")
    df = fetch_nbbo_1min(days=5)
    df.to_csv("mu_alpaca_1min.csv", index=False)
    print(f"  [OK] {len(df)} 本 → mu_alpaca_1min.csv")
    print(df.tail(3).to_string())
