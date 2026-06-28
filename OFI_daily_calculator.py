"""
OFI_daily_calculator.py
日足OFI近似計算。

板情報なしで使える近似式 (Lee-Ready ルール簡略版):
  close > open → 出来高を "買い主導" とみなす → OFI = +volume
  close < open → 出来高を "売り主導" とみなす → OFI = -volume
  close == open → OFI = 0

実データ接続時も yfinance の日足OHLCV をそのまま流し込める。
"""

import numpy as np
import pandas as pd


def calculate_daily_ofi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["daily_ofi"] = (df["volume"] * np.sign(df["close"] - df["open"])).astype(int)
    df["cumulative_ofi"] = df["daily_ofi"].cumsum()
    return df


if __name__ == "__main__":
    df_raw = pd.read_csv("ofi_daily_dummy_data.csv")
    df_result = calculate_daily_ofi(df_raw)
    df_result.to_csv("ofi_daily_result.csv", index=False)

    print("[OK] 日足OFI計算完了: ofi_daily_result.csv")
    print(df_result[["date", "close", "daily_ofi", "cumulative_ofi"]].tail(10).to_string())
