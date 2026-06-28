"""
OFI_dummy_gen.py
1分足の歩み値・板情報ダミーCSVを生成するスクリプト。
「価格は下落または横ばいなのに、内部の買いエネルギー（OFI）だけが
右肩上がりに溜まっている状態（プロのステルス買いの罠）」を意図的に再現。
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

N = 390  # 9:30〜16:00 (1取引日 = 390分)
start_time = datetime(2024, 1, 15, 9, 30, 0)
timestamps = [start_time + timedelta(minutes=i) for i in range(N)]

# ---------------------------------------------------------------
# ステルス買いの罠: 価格は下落・横ばいなのに OFI は右肩上がり
# ---------------------------------------------------------------
# 価格: 緩やかな下落（表面上は弱い）
price_base = 8500.0
price_drift = np.linspace(0, -120, N)
price_noise = np.random.normal(0, 6, N)
prices = price_base + price_drift + price_noise

# Bid価格: 【意図的に上昇トレンドを設定】
#   → Bid_t > Bid_{t-1} が多発 => delta_bid = Vol_Bid,t (大きな正の値)
#   大口プレイヤーが意図的にビッドを引き上げて玉を集めている
bid_price_base = prices[0] - 1.0
bid_price_trend = np.linspace(0, 200, N)    # 価格は落ちるのにBidは上がる（1日分なので幅拡大）
bid_price_noise = np.random.normal(0, 1.5, N)
bid_prices = bid_price_base + bid_price_trend + bid_price_noise

# Bid出来高: 増加（大口が積極的に買い注文を積み上げる）
bid_volume_trend = np.linspace(800, 6000, N)
bid_volume_noise = np.random.normal(0, 200, N)
bid_volumes = np.maximum(100, bid_volume_trend + bid_volume_noise).astype(int)

# Ask価格: 【意図的に上昇トレンドを設定】
#   → Ask_t > Ask_{t-1} が多発 => delta_ask = 0 (売り圧力ゼロ扱い)
#   売り手が手を引いている（薄い売り板）
ask_price_base = prices[0] + 1.0
ask_price_trend = np.linspace(0, 60, N)
ask_price_noise = np.random.normal(0, 1.5, N)
ask_prices = ask_price_base + ask_price_trend + ask_price_noise

# Ask出来高: 減少（売り圧力は弱まっている）
ask_volume_trend = np.linspace(3000, 600, N)
ask_volume_noise = np.random.normal(0, 150, N)
ask_volumes = np.maximum(100, ask_volume_trend + ask_volume_noise).astype(int)

df = pd.DataFrame({
    "timestamp": timestamps,
    "price": np.round(prices, 1),
    "bid_price": np.round(bid_prices, 1),
    "bid_volume": bid_volumes,
    "ask_price": np.round(ask_prices, 1),
    "ask_volume": ask_volumes,
})

output_path = "ofi_dummy_data.csv"
df.to_csv(output_path, index=False)
print(f"[OK] ダミーデータを生成しました: {output_path}  ({len(df)} 行)")
print(df.head(5).to_string())
