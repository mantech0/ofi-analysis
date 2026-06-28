"""
OFI_daily_dummy_gen.py
日足ダミーデータを生成 (60営業日 = 約3ヶ月)。
OHLCV形式。

ステルス買いパターン:
  - 終値は緩やかに下落（表面上は弱い）
  - 上昇日: 出来高大 → 買いエネルギーが溜まる
  - 下落日: 出来高小 → 売りの勢いは弱い
  → 日足累積OFIは右肩上がり
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta


def business_days(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


np.random.seed(42)

N = 60
dates = business_days(date(2024, 1, 15), N)

# 終値: 緩やかな下落 + ランダムウォーク成分
price_base = 8500.0
drift = np.linspace(0, -300, N)
rw = np.cumsum(np.random.normal(0, 20, N))
closes = price_base + drift + rw

# 始値: 前日終値 ± ギャップ
opens = np.roll(closes, 1) + np.random.normal(0, 15, N)
opens[0] = closes[0] + np.random.normal(0, 10)

# 高値・安値
highs = np.maximum(opens, closes) + np.random.uniform(15, 60, N)
lows  = np.minimum(opens, closes) - np.random.uniform(15, 60, N)

# 出来高: 上昇日は大きく、下落日は小さい（機関投資家の買い蓄積パターン）
up_days = closes > opens
base_vol = 1_000_000
volumes = np.where(
    up_days,
    (base_vol * np.random.uniform(1.8, 3.5, N)).astype(int),   # 上昇日: 1.8〜3.5倍
    (base_vol * np.random.uniform(0.2, 0.6, N)).astype(int),   # 下落日: 0.2〜0.6倍
)

df = pd.DataFrame({
    "date":   dates,
    "open":   np.round(opens,  1),
    "high":   np.round(highs,  1),
    "low":    np.round(lows,   1),
    "close":  np.round(closes, 1),
    "volume": volumes,
})

output = "ofi_daily_dummy_data.csv"
df.to_csv(output, index=False)
print(f"[OK] 日足ダミーデータを生成しました: {output}  ({len(df)} 日)")
print(df.head(5).to_string())
