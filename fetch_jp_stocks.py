"""
fetch_jp_stocks.py
東証上場銘柄の日足・1分足 OHLCV を yfinance で取得する汎用モジュール。
fetch_kioxia.py と同じ変換ロジック（MultiIndex フラット化、JST 変換）。
"""

import pandas as pd
import yfinance as yf
import pytz

JST = pytz.timezone("Asia/Tokyo")


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    return df


def fetch_daily(ticker: str, period: str = "1y") -> pd.DataFrame:
    raw = yf.download(ticker, period=period, interval="1d",
                      auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError(f"{ticker}: 日足データなし")
    raw = _flatten(raw).reset_index()
    raw = raw.rename(columns={raw.columns[0]: "date"})
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    out = raw[["date", "open", "high", "low", "close", "volume"]].dropna()
    print(f"  {ticker} 日足: {len(out)}日  {out['date'].iloc[0]} 〜 {out['date'].iloc[-1]}")
    return out.reset_index(drop=True)


def fetch_intraday(ticker: str, period: str = "5d", interval: str = "1m") -> pd.DataFrame:
    raw = yf.download(ticker, period=period, interval=interval,
                      auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError(f"{ticker}: 1分足データなし")
    raw = _flatten(raw).reset_index()
    ts_col = raw.columns[0]
    raw = raw.rename(columns={ts_col: "timestamp"})
    raw["timestamp"] = pd.to_datetime(raw["timestamp"])

    if raw["timestamp"].dt.tz is not None:
        raw["timestamp"] = raw["timestamp"].dt.tz_convert(JST).dt.tz_localize(None)

    raw = raw[raw["volume"] > 0].copy()
    cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"]
            if c in raw.columns]
    out = raw[cols].reset_index(drop=True)
    print(f"  {ticker} 1分足: {len(out)}本  {out['timestamp'].iloc[0]} 〜 {out['timestamp'].iloc[-1]}")
    return out
