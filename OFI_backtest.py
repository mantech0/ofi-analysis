"""
OFI_backtest.py
バックテスト・エントリー条件定量化・示唆データ生成
"""

import numpy as np
import pandas as pd


def _trailing_consecutive(series: pd.Series) -> int:
    """末尾から遡る連続 True の個数"""
    vals = series.fillna(False).astype(bool).values
    count = 0
    for v in reversed(vals):
        if v:
            count += 1
        else:
            break
    return count


def _optimal_n(base_rate: float, bars_per_period: int,
               max_false_per_period: float) -> int:
    """
    1期間あたりの偽アラート期待値が max_false_per_period 以下になる最小 N。
    P(偽ランの開始) ≈ (1-r)*r^N と仮定（独立性・保守的推定）。
    """
    if base_rate <= 0 or base_rate >= 1:
        return 3
    for n in range(2, 21):
        expected = (1 - base_rate) * (base_rate ** n) * bars_per_period
        if expected <= max_false_per_period:
            return n
    return 20


def run_backtest(df: pd.DataFrame, timeframe: str, forward_bars: int) -> dict:
    """
    ステルス買いシグナル後 forward_bars バーの価格リターンを集計。
    """
    price_col   = "price" if "price" in df.columns else "close"
    stealth_col = "stealth_30min" if timeframe == "intraday" else "stealth_5day"

    if stealth_col not in df.columns or price_col not in df.columns:
        return {"n": 0}

    df2 = df.dropna(subset=[stealth_col, price_col]).reset_index(drop=True)
    rets = []
    for idx in df2.index[df2[stealth_col].fillna(False).astype(bool)]:
        if idx + forward_bars < len(df2):
            ep = float(df2.loc[idx, price_col])
            xp = float(df2.loc[idx + forward_bars, price_col])
            if ep > 0:
                rets.append((xp - ep) / ep * 100)

    if not rets:
        return {"n": 0}

    arr = np.array(rets)
    return {
        "n":        len(arr),
        "win_rate": round(float((arr > 0).mean() * 100), 1),
        "avg_ret":  round(float(arr.mean()), 3),
        "med_ret":  round(float(np.median(arr)), 3),
    }


def compute_entry_conditions(df: pd.DataFrame, timeframe: str) -> dict:
    """
    ステルス買い発生時の直前 window バーの OFI 変化量・価格変化量を集計し
    エントリー条件の閾値を算出。
      X = OFI 変化の中央値  → 「これ以上の OFI 上昇が必要」
      Y = 価格変化の 25 パーセンタイルの絶対値 → 「これ以内の下落なら許容」
    """
    stealth_col = "stealth_30min" if timeframe == "intraday" else "stealth_5day"
    price_col   = "price" if "price" in df.columns else "close"
    window      = 30 if timeframe == "intraday" else 5

    if stealth_col not in df.columns or "cumulative_ofi" not in df.columns:
        return {}

    df2 = df.reset_index(drop=True)
    signal_idx = df2.index[df2[stealth_col].fillna(False).astype(bool)]

    ofi_chgs, px_chgs = [], []
    for i in signal_idx:
        if i >= window:
            try:
                oi = float(df2.loc[i, "cumulative_ofi"])
                o0 = float(df2.loc[i - window, "cumulative_ofi"])
                pi = float(df2.loc[i, price_col])
                p0 = float(df2.loc[i - window, price_col])
                if p0 > 0:
                    ofi_chgs.append(oi - o0)
                    px_chgs.append((pi - p0) / p0 * 100)
            except Exception:
                pass

    if not ofi_chgs:
        return {}

    oc, pc = np.array(ofi_chgs), np.array(px_chgs)
    return {
        "ofi_x":   round(float(np.percentile(oc, 50)), 0),
        "price_y": round(float(abs(np.percentile(pc, 25))), 2),
        "n":       len(oc),
    }


def summarize(ins: dict) -> str:
    """
    示唆データを1〜3文の平文に翻訳する。
    「数字を見てどういう状況か」を直接説明する。
    """
    dom       = ins.get("dominant", "")
    dom_pct   = ins.get("dominant_pct", 0)
    ofi_dir   = ins.get("ofi_dir", "")
    base_rate = ins.get("base_rate", 0.0)
    alert_trig = ins.get("alert_trig", False)
    bt        = ins.get("backtest", {})
    tf_label  = "1分足" if ins.get("timeframe") == "intraday" else "日足"

    parts = []

    # ── フェーズの翻訳 ────────────────────────────────────────
    if "ステルス買い" in dom:
        if dom_pct >= 50:
            parts.append(f"{tf_label}が「ステルス買い {dom_pct}%」= 機関の仕込みシグナルが優勢。エントリー検討の好機")
        elif dom_pct >= 30:
            parts.append(f"{tf_label}で「ステルス買い {dom_pct}%」= 仕込みの兆候あり。強い確認が出るまで待機")
        else:
            parts.append(f"{tf_label}で「ステルス買い」が {dom_pct}% 程度で混在している")
    elif "分配売り" in dom:
        if dom_pct >= 50:
            parts.append(f"{tf_label}が「分配売り {dom_pct}%」= 機関の売り逃げフェーズ。今は仕込みの時期ではない")
        else:
            parts.append(f"{tf_label}で「分配売り {dom_pct}%」= 売り圧力が散見される。慎重に")
    elif "確認上昇" in dom:
        if dom_pct >= 50:
            parts.append(f"{tf_label}が「確認上昇 {dom_pct}%」= 素直な上昇トレンド。乗れるが出遅れ気味になりやすい")
        else:
            parts.append(f"{tf_label}で「確認上昇 {dom_pct}%」= 上昇傾向だがまだ方向感が弱い")
    elif "確認下落" in dom:
        if dom_pct >= 50:
            parts.append(f"{tf_label}が「確認下落 {dom_pct}%」= 売り圧力が続いている。様子見が無難")
        else:
            parts.append(f"{tf_label}で「確認下落 {dom_pct}%」= 弱め。まだ底打ちサインはない")

    # ── OFI が価格と逆向きのとき → 乖離シグナルを強調 ─────────
    if "↑" in ofi_dir and "確認下落" in dom:
        parts.append("ただし累積OFIは上昇中 → 価格下落中に買いが蓄積されている可能性（ステルス買い予兆）")
    elif "↓" in ofi_dir and "確認上昇" in dom:
        parts.append("ただし累積OFIは下落中 → 価格上昇に売りが付いてきており、上昇の持続力に注意")
    elif "↑" in ofi_dir and "ステルス買い" in dom:
        parts.append("累積OFIも上昇しており買い圧力を確認")
    elif "↓" in ofi_dir and "分配売り" in dom:
        parts.append("累積OFIも下落しており売り圧力を確認")

    # ── ステルス買いがほぼ出ていない ─────────────────────────
    if base_rate < 1.0 and "ステルス買い" not in dom:
        parts.append(f"ステルス買いシグナルの発生率は {base_rate}% とほぼゼロ → 機関の仕込みは確認できていない")

    # ── アラート ─────────────────────────────────────────────
    if alert_trig:
        n = ins.get("consecutive", 0)
        parts.append(f"⚡ 連続{n}回のステルス買いアラート発動中 → 今すぐエントリー条件を確認して")

    # ── バックテスト結果 ─────────────────────────────────────
    if bt.get("n", 0) >= 10:
        win = bt["win_rate"]
        avg = bt["avg_ret"]
        fwd = ins.get("forward_bars", 30)
        unit = "分後" if ins.get("timeframe") == "intraday" else "日後"
        if win >= 60:
            parts.append(f"過去データでは同シグナル後{fwd}{unit}の勝率が{win}% / 平均{avg:+.2f}% → 精度は良好")
        elif win < 40:
            parts.append(f"ただし過去シグナル後{fwd}{unit}の勝率は{win}% と低め → 追加確認を推奨")

    return " ／ ".join(parts) if parts else "分析データを収集中..."


def build_insight(df: pd.DataFrame, timeframe: str, symbol: str) -> dict:
    """1タブ分の示唆データを辞書で返す"""
    price_col   = "price" if "price" in df.columns else "close"
    stealth_col = "stealth_30min" if timeframe == "intraday" else "stealth_5day"
    cluster_col = "cluster_name"

    # タイムフレーム別パラメータ
    forward_bars     = 30  if timeframe == "intraday" else 5
    bars_per_period  = 390 if timeframe == "intraday" else 252
    max_false        = 0.3 if timeframe == "intraday" else 3.0
    lookback         = 60  if timeframe == "intraday" else 20

    # ── 直近クラスタ分布 ─────────────────────────────────────
    if cluster_col in df.columns:
        recent = df.dropna(subset=[cluster_col]).tail(lookback)
        if len(recent) > 0:
            vc = recent[cluster_col].value_counts()
            dominant     = vc.index[0]
            dominant_pct = round(float(vc.iloc[0] / len(recent) * 100))
        else:
            dominant, dominant_pct = "データ不足", 0
    else:
        dominant, dominant_pct = "−", 0

    # ── OFI 方向（直近 30 本） ────────────────────────────────
    ofi_dir = "−"
    if "cumulative_ofi" in df.columns:
        ofi_vals = df["cumulative_ofi"].dropna().tail(30)
        if len(ofi_vals) >= 2:
            chg = float(ofi_vals.iloc[-1]) - float(ofi_vals.iloc[0])
            ofi_dir = "↑ 上昇" if chg > 0 else "↓ 下落"

    # ── 連続シグナル数・統計 ──────────────────────────────────
    consecutive = stealth_count = 0
    base_rate = 0.0
    if stealth_col in df.columns:
        s = df[stealth_col].fillna(False).astype(bool)
        consecutive   = _trailing_consecutive(s)
        stealth_count = int(s.sum())
        base_rate     = float(s.mean())

    # N の最適値（統計的根拠付き）
    alert_n = _optimal_n(base_rate, bars_per_period, max_false)
    # 偽陽性の期待値（per period）
    if base_rate > 0:
        false_exp = round((1 - base_rate) * (base_rate ** alert_n) * bars_per_period, 2)
    else:
        false_exp = 0.0

    alert_trig = consecutive >= alert_n

    # N 算出根拠テキスト
    period_label = "1日" if timeframe == "intraday" else "1年"
    n_reason = (
        f"発生率 {round(base_rate*100,1)}% → "
        f"連続{alert_n}回の偽陽性期待値 {false_exp:.2f}回/{period_label}"
    )

    # ── バックテスト ─────────────────────────────────────────
    bt = run_backtest(df, timeframe=timeframe, forward_bars=forward_bars)

    # ── エントリー条件 ───────────────────────────────────────
    ec = compute_entry_conditions(df, timeframe=timeframe)

    # ── 返り値を仮組みしてから summary を生成 ─────────────────
    result = {
        "symbol":        symbol,
        "timeframe":     timeframe,
        "dominant":      dominant,
        "dominant_pct":  dominant_pct,
        "ofi_dir":       ofi_dir,
        "consecutive":   consecutive,
        "alert_n":       alert_n,
        "alert_trig":    alert_trig,
        "stealth_count": stealth_count,
        "base_rate":     round(base_rate * 100, 1),
        "false_exp":     false_exp,
        "n_reason":      n_reason,
        "backtest":      bt,
        "forward_bars":  forward_bars,
        "entry":         ec,
        "lookback":      lookback,
    }
    result["summary"] = summarize(result)
    return result
