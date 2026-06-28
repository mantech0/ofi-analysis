"""
OFI_daily_visualizer.py
日足OFI分析チャート → index_daily.html

  Row 1: ローソク足 (OHLC) + ステルス買いマーカー
  Row 2: 累積OFI (面グラフ) + ステルス買いマーカー
  Row 3: クラスタ散布図 (価格傾き vs OFI傾き, 5日窓)
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

CLUSTER_COLORS = {
    "確認上昇 (Bullish)":           "#4CAF50",
    "ステルス買い (Stealth Buy) ⚡": "#FFD700",
    "分配売り (Distribution)":       "#FF5722",
    "確認下落 (Bearish)":            "#78909C",
}


def build_daily_chart(df: pd.DataFrame) -> go.Figure:
    has_slope = "price_slope_5d" in df.columns

    fig = make_subplots(
        rows=3 if has_slope else 2,
        cols=1,
        shared_xaxes=False,
        row_heights=[0.38, 0.34, 0.28] if has_slope else [0.55, 0.45],
        vertical_spacing=0.08,
        subplot_titles=(
            "日足チャート (ローソク足)  ▲ = ステルス買い検出 (5日窓)",
            "累積OFI (日足近似)  ▲ = ステルス買い検出 (5日窓)",
            "クラスタ散布図: 価格の傾き vs OFIの傾き (5日窓)",
        ) if has_slope else (
            "日足チャート (ローソク足)",
            "累積OFI (日足近似)",
        ),
    )

    date_strs = df["date"].dt.strftime("%Y-%m-%d")

    # ── Row 1: Candlestick ────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=date_strs,
        open=df["open"], high=df["high"],
        low=df["low"],  close=df["close"],
        name="OHLC",
        increasing=dict(line=dict(color="#4CAF50"), fillcolor="#4CAF50"),
        decreasing=dict(line=dict(color="#EF5350"), fillcolor="#EF5350"),
        hovertext=date_strs,
    ), row=1, col=1)

    if has_slope:
        s5 = df[df["stealth_5d"] == True]
        fig.add_trace(go.Scatter(
            x=s5["date"].dt.strftime("%Y-%m-%d"), y=s5["high"] + 30,
            mode="markers", name="ステルス買い(5日)",
            marker=dict(symbol="triangle-up", size=12,
                        color="#FFD700", line=dict(width=1, color="#B8860B")),
            hovertemplate="<b>%{x}</b><br>ステルス買い検出(5日窓)<extra></extra>",
        ), row=1, col=1)

        s20 = df[df["stealth_20d"] == True]
        fig.add_trace(go.Scatter(
            x=s20["date"].dt.strftime("%Y-%m-%d"), y=s20["high"] + 60,
            mode="markers", name="ステルス買い(20日)",
            marker=dict(symbol="triangle-up", size=8,
                        color="#FF6B35", line=dict(width=1, color="#C0392B")),
            hovertemplate="<b>%{x}</b><br>ステルス買い検出(20日窓)<extra></extra>",
        ), row=1, col=1)

    # ── Row 2: Cumulative OFI ─────────────────────────────────
    fig.add_trace(go.Scatter(
        x=date_strs, y=df["cumulative_ofi"],
        mode="lines", name="累積OFI",
        fill="tozeroy",
        line=dict(color="#66BB6A", width=2),
        fillcolor="rgba(102,187,106,0.12)",
        hovertemplate="<b>%{x}</b><br>累積OFI: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    fig.add_hline(y=0, row=2, col=1, line_dash="dot", line_color="gray", line_width=1)

    if has_slope:
        fig.add_trace(go.Scatter(
            x=s5["date"].dt.strftime("%Y-%m-%d"), y=s5["cumulative_ofi"],
            mode="markers", showlegend=False,
            marker=dict(symbol="triangle-up", size=12,
                        color="#FFD700", line=dict(width=1, color="#B8860B")),
            hovertemplate="<b>%{x}</b><br>ステルス買い(5日)<extra></extra>",
        ), row=2, col=1)

    # ── Row 3: Cluster scatter ────────────────────────────────
    if has_slope and "cluster_name" in df.columns:
        for name, color in CLUSTER_COLORS.items():
            sub = df[df["cluster_name"] == name]
            if len(sub) == 0:
                continue
            fig.add_trace(go.Scatter(
                x=sub["price_slope_5d"], y=sub["ofi_slope_5d"],
                mode="markers", name=name,
                marker=dict(color=color, size=8, opacity=0.85),
                text=sub["date"].dt.strftime("%Y-%m-%d"),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "価格傾き: %{x:.2f}<br>"
                    f"OFI傾き: %{{y:,.0f}}<br>{name}<extra></extra>"
                ),
            ), row=3, col=1)

        ps = df["price_slope_5d"].dropna()
        os = df["ofi_slope_5d"].dropna()
        for xv, yv in [([ps.min(), ps.max()], [0, 0]),
                        ([0, 0], [os.min(), os.max()])]:
            fig.add_trace(go.Scatter(
                x=xv, y=yv, mode="lines",
                line=dict(dash="dash", color="#546E7A", width=1),
                showlegend=False, hoverinfo="none",
            ), row=3, col=1)

    # ── Layout ────────────────────────────────────────────────
    fig.update_layout(
        xaxis2=dict(matches="x"),
        title=dict(
            text="OFI 傾き分析チャート — 日足（5日・20日ウィンドウ）",
            font=dict(size=16, color="white"), x=0.5,
        ),
        paper_bgcolor="#1A1A2E",
        plot_bgcolor="#16213E",
        font=dict(color="#E0E0E0"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
            bgcolor="rgba(0,0,0,0.5)", font=dict(size=10),
        ),
        hovermode="closest",
        height=880,
        margin=dict(l=70, r=40, t=130, b=60),
        xaxis=dict(rangeslider=dict(visible=False)),  # ローソク足のスライダー非表示
    )

    for ax in ["xaxis", "xaxis2", "xaxis3", "yaxis", "yaxis2", "yaxis3"]:
        fig.update_layout(**{ax: dict(
            gridcolor="#243454", zerolinecolor="#4A5568",
            tickfont=dict(color="#B0BEC5"),
        )})

    fig.update_yaxes(title_text="価格 (¥)",  row=1, col=1)
    fig.update_yaxes(title_text="累積OFI",   row=2, col=1)
    if has_slope:
        fig.update_xaxes(title_text="価格の傾き (price_slope_5d)",  row=3, col=1)
        fig.update_yaxes(title_text="OFIの傾き (ofi_slope_5d)",     row=3, col=1)

    return fig


if __name__ == "__main__":
    try:
        df = pd.read_csv("ofi_daily_slope_result.csv", parse_dates=["date"])
    except FileNotFoundError:
        df = pd.read_csv("ofi_daily_result.csv", parse_dates=["date"])

    fig = build_daily_chart(df)
    fig.write_html("index_daily.html", include_plotlyjs="cdn")
    print("[OK] index_daily.html を出力しました（日足版）")
