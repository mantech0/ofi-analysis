"""
fetch_kioxia.py
Kioxia (285A.T) の実データを yfinance で取得する。
  - 日足 : 過去1年分 → kioxia_daily.csv
  - 1分足: 直近5営業日 → kioxia_intraday.csv
"""

import pandas as pd
import yfinance as yf

TICKER = "285A.T"


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance の MultiIndex カラムをフラット化 + 小文字化"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.columns = [c.lower() for c in df.columns]
    return df


def fetch_daily(period: str = "1y") -> pd.DataFrame:
    raw = yf.download(TICKER, period=period, interval="1d",
                      auto_adjust=True, progress=False)
    if raw.empty:
        raise RuntimeError(f"日足データ取得失敗: {TICKER}")

    df = _flatten(raw).reset_index()
    # yfinance は "Date" または "index" でインデックスを返す
    date_col = next(c for c in df.columns if "date" in c.lower())
    df = df.rename(columns={date_col: "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[["date", "open", "high", "low", "close", "volume"]].dropna()

    df.to_csv("kioxia_daily.csv", index=False)
    print(f"  日足: {len(df)}日  {df['date'].iloc[0]} 〜 {df['date'].iloc[-1]}")
    return df


def fetch_intraday(period: str = "5d", interval: str = "1m") -> pd.DataFrame:
    raw = yf.download(TICKER, period=period, interval=interval,
                      auto_adjust=True, progress=False)
    if raw.empty:
        raise RuntimeError(f"1分足データ取得失敗: {TICKER}")

    df = _flatten(raw).reset_index()
    ts_col = next(c for c in df.columns if "datetime" in c.lower() or "timestamp" in c.lower())
    df = df.rename(columns={ts_col: "timestamp"})

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    # UTC の場合は JST (UTC+9) に変換
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = (df["timestamp"]
                           .dt.tz_convert("Asia/Tokyo")
                           .dt.tz_localize(None))

    df = df[["timestamp", "open", "high", "low", "close", "volume"]].dropna()
    df = df[df["volume"] > 0]  # 出来高ゼロ（昼休み等）を除去

    df.to_csv("kioxia_intraday.csv", index=False)
    print(f"  1分足: {len(df)}本  {df['timestamp'].iloc[0]} 〜 {df['timestamp'].iloc[-1]}")
    return df


if __name__ == "__main__":
    print(f"=== Kioxia ({TICKER}) データ取得 ===")
    fetch_daily()
    fetch_intraday()
