"""
OFI_calculator.py
CSVを読み込み、Order Flow Imbalance (OFI) を計算して cumulative OFI を付与する。

数式:
  ΔVol_Bid:
    Bid_t > Bid_{t-1}  => Vol_Bid,t
    Bid_t == Bid_{t-1} => Vol_Bid,t - Vol_Bid,{t-1}
    Bid_t < Bid_{t-1}  => 0

  ΔVol_Ask:
    Ask_t < Ask_{t-1}  => Vol_Ask,t
    Ask_t == Ask_{t-1} => Vol_Ask,t - Vol_Ask,{t-1}
    Ask_t > Ask_{t-1}  => 0

  OFI_t = ΔVol_Bid - ΔVol_Ask
"""

import numpy as np
import pandas as pd


def calculate_ofi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    bid_p = df["bid_price"].values
    bid_v = df["bid_volume"].values
    ask_p = df["ask_price"].values
    ask_v = df["ask_volume"].values

    n = len(df)
    delta_bid = np.zeros(n)
    delta_ask = np.zeros(n)

    for t in range(1, n):
        # Bid側
        if bid_p[t] > bid_p[t - 1]:
            delta_bid[t] = bid_v[t]
        elif bid_p[t] == bid_p[t - 1]:
            delta_bid[t] = bid_v[t] - bid_v[t - 1]
        else:
            delta_bid[t] = 0

        # Ask側
        if ask_p[t] < ask_p[t - 1]:
            delta_ask[t] = ask_v[t]
        elif ask_p[t] == ask_p[t - 1]:
            delta_ask[t] = ask_v[t] - ask_v[t - 1]
        else:
            delta_ask[t] = 0

    df["delta_bid"] = delta_bid
    df["delta_ask"] = delta_ask
    df["ofi"] = delta_bid - delta_ask
    df["cumulative_ofi"] = df["ofi"].cumsum()

    return df


if __name__ == "__main__":
    input_path = "ofi_dummy_data.csv"
    output_path = "ofi_result.csv"

    df_raw = pd.read_csv(input_path)
    df_result = calculate_ofi(df_raw)

    df_result.to_csv(output_path, index=False)
    print(f"[OK] OFI計算完了: {output_path}  ({len(df_result)} 行)")
    print(df_result[["timestamp", "price", "ofi", "cumulative_ofi"]].tail(10).to_string())
