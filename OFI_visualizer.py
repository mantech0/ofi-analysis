"""
OFI_visualizer.py  (v3 — 夜間除去・タイトル修正・market対応)
  Row 1: 株価推移 + ステルス買いマーカー
  Row 2: 累積OFI + ステルス買いマーカー
  Row 3: クラスタ散布図
→ index.html
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

CLUSTER_COLORS = {
    "確認上昇 (Bullish)":           "#4CAF50",
    "ステルス買い (Stealth Buy) ⚡": "#FFD700",
    "分配売り (Distribution)":       "#FF5722",
    "確認下落 (Bearish)":            "#78909C",
}

# 市場別の取引時間外レンジ除去設定
RANGEBREAKS = {
    "US": [dict(bounds=["sat", "mon"]),
           dict(bounds=[16, 9.5], pattern="hour")],   # ET: 16:00-09:30
    "JP": [dict(bounds=["sat", "mon"]),
           dict(bounds=[15.5, 9.0], pattern="hour")], # JST: 15:30-09:00
    "none": [],
}


def build_chart(df: pd.DataFrame, market: str = "US") -> go.Figure:
    has_slope = "price_slope_30min" in df.columns
    rb = RANGEBREAKS.get(market, [])

    fig = make_subplots(
        rows=3 if has_slope else 2,
        cols=1,
        shared_xaxes=False,
        row_heights=[0.36, 0.36, 0.28] if has_slope else [0.5, 0.5],
        vertical_spacing=0.10,
        subplot_titles=(
            "株価推移  ▲ = ステルス買い検出 (30分窓)",
            "累積OFI  ▲ = ステルス買い検出 (30分窓)",
            "クラスタ散布図: 価格の傾き vs OFIの傾き (30分窓)",
        ) if has_slope else ("株価推移", "累積OFI"),
    )

    # ── Row 1: Price ──────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["price"],
        mode="lines", name="Price",
        line=dict(color="#4FC3F7", width=1.5),
        connectgaps=False,
        hovertemplate="<b>%{x|%m/%d %H:%M}</b><br>価格: $%{y:.2f}<extra></extra>",
    ), row=1, col=1)

    if has_slope:
        s30 = df[df["stealth_30min"] == True]
        fig.add_trace(go.Scatter(
            x=s30["timestamp"], y=s30["price"],
            mode="markers", name="ステルス買い(30分)",
            marker=dict(symbol="triangle-up", size=11,
                        color="#FFD700", line=dict(width=1, color="#B8860B")),
            hovertemplate="<b>%{x|%m/%d %H:%M}</b><br>ステルス買い(30分)<extra></extra>",
        ), row=1, col=1)

        s60 = df[df["stealth_60min"] == True]
        fig.add_trace(go.Scatter(
            x=s60["timestamp"], y=s60["price"],
            mode="markers", name="ステルス買い(60分)",
            marker=dict(symbol="triangle-up", size=7,
                        color="#FF6B35", line=dict(width=1, color="#C0392B")),
            hovertemplate="<b>%{x|%m/%d %H:%M}</b><br>ステルス買い(60分)<extra></extra>",
        ), row=1, col=1)

    # ── Row 2: Cumulative OFI ─────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["cumulative_ofi"],
        mode="lines", name="累積OFI",
        fill="tozeroy",
        line=dict(color="#66BB6A", width=1.5),
        fillcolor="rgba(102,187,106,0.12)",
        connectgaps=False,
        hovertemplate="<b>%{x|%m/%d %H:%M}</b><br>累積OFI: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    fig.add_hline(y=0, row=2, col=1, line_dash="dot", line_color="gray", line_width=1)

    if has_slope:
        fig.add_trace(go.Scatter(
            x=s30["timestamp"], y=s30["cumulative_ofi"],
            mode="markers", showlegend=False,
            marker=dict(symbol="triangle-up", size=11,
                        color="#FFD700", line=dict(width=1, color="#B8860B")),
            hovertemplate="<b>%{x|%m/%d %H:%M}</b><br>ステルス買い(30分)<extra></extra>",
        ), row=2, col=1)

    # ── Row 3: Cluster scatter ────────────────────────────────
    if has_slope and "cluster_name" in df.columns:
        for name, color in CLUSTER_COLORS.items():
            sub = df[df["cluster_name"] == name]
            if len(sub) == 0:
                continue
            fig.add_trace(go.Scatter(
                x=sub["price_slope_30min"], y=sub["ofi_slope_30min"],
                mode="markers", name=name,
                marker=dict(color=color, size=6, opacity=0.8),
                text=sub["timestamp"].dt.strftime("%m/%d %H:%M"),
                hovertemplate=(
                    "<b>%{text}</b><br>価格傾き: %{x:.3f}<br>"
                    f"OFI傾き: %{{y:.1f}}<br>{name}<extra></extra>"
                ),
            ), row=3, col=1)

        ps = df["price_slope_30min"].dropna()
        os_ = df["ofi_slope_30min"].dropna()
        for xv, yv in [([ps.min(), ps.max()], [0, 0]), ([0, 0], [os_.min(), os_.max()])]:
            fig.add_trace(go.Scatter(
                x=xv, y=yv, mode="lines",
                line=dict(dash="dash", color="#546E7A", width=1),
                showlegend=False, hoverinfo="none",
            ), row=3, col=1)

    # ── Layout ────────────────────────────────────────────────
    fig.update_layout(
        xaxis2=dict(matches="x"),   # Row 2 の時間軸を Row 1 と同期
        title=dict(
            text="OFI 傾き分析チャート — 1分足（30分・60分ウィンドウ）",
            font=dict(size=16, color="white"), x=0.5, y=0.98,
        ),
        paper_bgcolor="#1A1A2E",
        plot_bgcolor="#16213E",
        font=dict(color="#E0E0E0"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            bgcolor="rgba(0,0,0,0.5)", font=dict(size=10),
        ),
        hovermode="closest",
        height=880,
        margin=dict(l=70, r=40, t=200, b=60),
    )

    # 軸スタイル（rangebreaks より先に設定）
    for ax in ["xaxis", "xaxis2", "xaxis3", "yaxis", "yaxis2", "yaxis3"]:
        fig.update_layout(**{ax: dict(
            gridcolor="#243454", zerolinecolor="#4A5568",
            tickfont=dict(color="#B0BEC5"),
        )})

    # 夜間・週末除去（row 1 と row 2 の時間軸に個別適用）
    if rb:
        fig.update_xaxes(rangebreaks=rb, row=1, col=1)
        fig.update_xaxes(rangebreaks=rb, row=2, col=1)

    fig.update_yaxes(title_text="価格 ($)", row=1, col=1)
    fig.update_yaxes(title_text="累積OFI", row=2, col=1)
    if has_slope:
        fig.update_xaxes(title_text="価格の傾き", row=3, col=1)
        fig.update_yaxes(title_text="OFIの傾き", row=3, col=1)

    return fig


if __name__ == "__main__":
    try:
        df = pd.read_csv("ofi_slope_result.csv", parse_dates=["timestamp"])
    except FileNotFoundError:
        df = pd.read_csv("ofi_result.csv", parse_dates=["timestamp"])

    fig = build_chart(df, market="US")
    fig.write_html("index.html", include_plotlyjs="cdn")
    print("[OK] index.html を出力しました")
