"""
OFI_slope_analyzer.py  — イントラデイ版（1分足）
ローリング傾き計算 + ルールベース異常検出 + K-meansクラスタリング
ウィンドウ: 30分・60分

4クラスタの意味:
  確認上昇   : 価格↑ & OFI↑  → 素直な上昇
  ステルス買い: 価格↓ & OFI↑  → プロの隠れ買い (TARGET)
  分配売り   : 価格↑ & OFI↓  → 高値圏での売り抜け
  確認下落   : 価格↓ & OFI↓  → 素直な下落
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

WINDOWS = [30, 60]   # minutes
PRIMARY = WINDOWS[0]

CLUSTER_NAMES = {
    ( 1,  1): "確認上昇 (Bullish)",
    (-1,  1): "ステルス買い (Stealth Buy) ⚡",
    ( 1, -1): "分配売り (Distribution)",
    (-1, -1): "確認下落 (Bearish)",
}


def rolling_slope(series: pd.Series, window: int) -> pd.Series:
    slopes = np.full(len(series), np.nan)
    x = np.arange(window, dtype=float)
    for i in range(window - 1, len(series)):
        y = series.iloc[i - window + 1: i + 1].values
        slopes[i] = np.polyfit(x, y, 1)[0]
    return pd.Series(slopes, index=series.index)


def label_cluster(centroid: np.ndarray) -> str:
    key = (1 if centroid[0] >= 0 else -1, 1 if centroid[1] >= 0 else -1)
    return CLUSTER_NAMES.get(key, "不明")


def analyze(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.copy()

    for w in WINDOWS:
        s = f"{w}min"
        df[f"price_slope_{s}"] = rolling_slope(df["price"], w)
        df[f"ofi_slope_{s}"]   = rolling_slope(df["cumulative_ofi"], w)
        df[f"stealth_{s}"]     = (df[f"price_slope_{s}"] < 0) & (df[f"ofi_slope_{s}"] > 0)

    p_col = f"price_slope_{PRIMARY}min"
    o_col = f"ofi_slope_{PRIMARY}min"
    valid_mask = df[[p_col, o_col]].notna().all(axis=1)
    valid = df.loc[valid_mask, [p_col, o_col]]

    scaler = StandardScaler()
    X = scaler.fit_transform(valid)
    km = KMeans(n_clusters=4, random_state=42, n_init=10)
    km.fit(X)

    centroids = scaler.inverse_transform(km.cluster_centers_)
    cluster_map = {i: label_cluster(c) for i, c in enumerate(centroids)}

    df["cluster"] = np.nan
    df.loc[valid_mask, "cluster"] = km.labels_.astype(float)
    df["cluster_name"] = df["cluster"].map(cluster_map)

    return df, cluster_map


if __name__ == "__main__":
    df = pd.read_csv("ofi_result.csv", parse_dates=["timestamp"])
    df_out, cluster_map = analyze(df)
    df_out.to_csv("ofi_slope_result.csv", index=False)

    print("[OK] イントラデイ傾き分析完了: ofi_slope_result.csv")
    for w in WINDOWS:
        n = int(df_out[f"stealth_{w}min"].sum())
        print(f"  ステルス買い検出 ({w}分窓): {n} / {len(df_out)} 本")
    print("\n  K-meansクラスタ:")
    for k, name in cluster_map.items():
        n = (df_out["cluster"] == k).sum()
        print(f"    Cluster {k}: {name} ({n}本)")
