"""
fetch_mu_ohlc.py
Micron (MU) 1分足 OHLCV を yfinance で取得し、
OHLC から bid/ask を推定する。

推定式 (Corwin-Schultz 近似の簡略版):
  bid_price  ≈ (close + low)  / 2   ← 最良買い気配の代理
  ask_price  ≈ (close + high) / 2   ← 最良売り気配の代理
  bid_volume ≈ volume × (close - low)  / (high - low)
  ask_volume ≈ volume × (high - close) / (high - low)

出力: OFI_calculator.py (bid/ask 版) にそのまま流せる形式
  columns: timestamp, price, bid_price, bid_volume, ask_price, ask_volume
"""

import numpy as np
import pandas as pd
import yfinance as yf

SYMBOL = "MU"


def fetch_and_derive(period: str = "5d") -> pd.DataFrame:
    raw = yf.download(SYMBOL, period=period, interval="1m",
                      auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]

    raw = raw.reset_index()
    ts_col = raw.columns[0]
    raw = raw.rename(columns={ts_col: "timestamp"})
    raw["timestamp"] = pd.to_datetime(raw["timestamp"])

    # UTC → ET 変換
    if raw["timestamp"].dt.tz is not None:
        raw["timestamp"] = (raw["timestamp"]
                            .dt.tz_convert("America/New_York")
                            .dt.tz_localize(None))

    raw = raw[raw["volume"] > 0].copy()

    # OHLC → bid/ask 推定
    eps = 1e-6
    price_range = (raw["high"] - raw["low"]).clip(lower=eps)

    raw["price"]      = raw["close"]
    raw["bid_price"]  = ((raw["close"] + raw["low"])  / 2).round(4)
    raw["ask_price"]  = ((raw["close"] + raw["high"]) / 2).round(4)
    raw["bid_volume"] = (raw["volume"] * (raw["close"] - raw["low"])  / price_range).clip(lower=0).astype(int)
    raw["ask_volume"] = (raw["volume"] * (raw["high"] - raw["close"]) / price_range).clip(lower=0).astype(int)

    cols = ["timestamp", "price", "bid_price", "bid_volume", "ask_price", "ask_volume"]
    return raw[cols].reset_index(drop=True)


def fetch_mu_daily() -> pd.DataFrame:
    raw = yf.download(SYMBOL, period="1y", interval="1d",
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]
    raw = raw.reset_index()
    raw = raw.rename(columns={raw.columns[0]: "date"})
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    return raw[["date", "open", "high", "low", "close", "volume"]].dropna()


if __name__ == "__main__":
    print(f"=== Micron ({SYMBOL}) OHLC 取得 ===")
    df = fetch_and_derive(period="5d")
    df.to_csv("mu_ohlc_1min.csv", index=False)
    print(f"[OK] {len(df)} 本 → mu_ohlc_1min.csv")
    print(df.head(3).to_string())
