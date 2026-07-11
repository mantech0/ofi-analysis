"""
create_dashboard.py
全銘柄 OFI ダッシュボード生成

出力先: ./dist/
  index.html        ← 銘柄一覧・全銘柄ブリーフィングコピー
  mu.html           ← Micron (MU)
  kioxia.html       ← Kioxia (285A.T)
  1969.html         ← 高砂熱化学
  6503.html         ← 三菱電機
  8002.html         ← 丸紅
  8053.html         ← 住友商事
"""

import csv
import io
import json
import os
import pathlib
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd

# .env をPythonで直接読み込む（bash source では & が誤解釈されるため）
_env_path = pathlib.Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from OFI_calculator import calculate_ofi
from OFI_daily_calculator import calculate_daily_ofi
from ofi_daily_score import update_score, get_7day_summary, format_score
from OFI_slope_analyzer import analyze as intra_analyze
from OFI_daily_slope_analyzer import analyze as daily_analyze
from OFI_visualizer import build_chart
from OFI_daily_visualizer import build_daily_chart
from OFI_backtest import build_insight

# ── 銘柄定義 ──────────────────────────────────────────────────────
STOCKS = [
    {"code": "MU",   "name": "マイクロン",  "ticker": "MU",     "market": "US"},
    {"code": "285A", "name": "キオクシア",  "ticker": "285A.T", "market": "JP"},
    {"code": "1969", "name": "高砂熱化学",  "ticker": "1969.T", "market": "JP"},
    {"code": "6503", "name": "三菱電機",    "ticker": "6503.T", "market": "JP"},
    {"code": "8002", "name": "丸紅",        "ticker": "8002.T", "market": "JP"},
    {"code": "8053", "name": "住友商事",    "ticker": "8053.T", "market": "JP"},
]

OUT_DIR  = pathlib.Path("dist")
LOGS_DIR = pathlib.Path(__file__).parent / "logs"
HISTORY_PATH = LOGS_DIR / "history.json"

# ── 履歴スナップショット ───────────────────────────────────────────
def save_snapshot(all_results: list, build_time: str) -> list:
    LOGS_DIR.mkdir(exist_ok=True)
    _jst = timezone(timedelta(hours=9))
    try:
        _dt = datetime.fromisoformat(build_time).astimezone(_jst)
        run_id     = _dt.strftime("%Y%m%d_%H%M")
        ts_display = _dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        run_id     = datetime.now().strftime("%Y%m%d_%H%M")
        ts_display = run_id

    snapshot = {
        "id": run_id,
        "timestamp": build_time,
        "ts_display": ts_display,
        "stocks": [
            {"code": r["code"], "name": r["name"], "market": r["market"],
             "ins_i": r["ins_i"], "ins_d": r["ins_d"]}
            for r in all_results
        ],
    }

    history = []
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            history = json.load(f)
    history = [h for h in history if h["id"] != run_id]  # 同IDは上書き
    history.append(snapshot)
    history = history[-100:]  # 最新100件のみ保持

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"[HISTORY] スナップショット保存: {run_id} (累計 {len(history)} 件)")
    return history


# ── ポートフォリオ取得 ─────────────────────────────────────────────
def _clean_num(s: str) -> str:
    """¥ $ , を除去して数値文字列に変換"""
    return s.replace("¥", "").replace("$", "").replace(",", "").strip()


def fetch_portfolio() -> list:
    """
    Google Sheets の公開CSVを取得して保有銘柄リストを返す。
    - ヘッダー行を自動検出（1行目が空/パーセント行でも対応）
    - 売却日付が入っている行は除外
    - 同一コードが複数行ある場合は加重平均で集計
    - 「株個数」のような重複列名は最初の出現（購入側）を使用
    """
    url = os.environ.get("PORTFOLIO_CSV_URL", "")
    if not url:
        return []
    try:
        # utf-8-sig で BOM を自動除去
        with urllib.request.urlopen(url, timeout=10) as r:
            content = r.read().decode("utf-8-sig")

        all_rows = list(csv.reader(io.StringIO(content)))

        # "コード" または "銘柄" を含む行をヘッダーとして自動検出
        header_idx = None
        for i, row in enumerate(all_rows):
            if any(c.strip() in ("コード", "銘柄", "code") for c in row):
                header_idx = i
                break

        if header_idx is None:
            print("  ポートフォリオ: ヘッダー行が見つかりません")
            return []

        headers = [c.strip() for c in all_rows[header_idx]]
        print(f"  ヘッダー検出: 行{header_idx + 1} → {headers[:6]}...")

        # 重複列名があっても「最初の出現」を使うため index() で列番号を取得
        def first_col(*names) -> int:
            for name in names:
                try:
                    return headers.index(name)
                except ValueError:
                    pass
            return -1

        ci_code  = first_col("コード", "code")
        ci_name  = first_col("銘柄", "銘柄名")
        ci_qty   = first_col("株個数", "株数")       # 購入側（最初の出現）
        ci_price = first_col("購入価格", "平均取得価格")
        ci_sell  = first_col("売却日付")
        ci_acct  = first_col("口座区分")
        ci_memo  = first_col("購入メモ", "メモ")

        if ci_code < 0 or ci_name < 0:
            print(f"  コード/銘柄列が見つかりません。列一覧: {headers}")
            return []

        def get(row, idx):
            return row[idx].strip() if 0 <= idx < len(row) else ""

        holdings = {}
        for row in all_rows[header_idx + 1:]:
            if not row or all(c.strip() == "" for c in row):
                continue

            code      = get(row, ci_code)
            name      = get(row, ci_name)
            qty_str   = _clean_num(get(row, ci_qty))
            price_str = _clean_num(get(row, ci_price))
            sell_date = get(row, ci_sell)
            account   = get(row, ci_acct)
            memo      = get(row, ci_memo)

            if not code or not name:
                continue
            if sell_date:           # 売却済みはスキップ
                continue

            try:
                qty   = float(qty_str)   if qty_str   else 0.0
                price = float(price_str) if price_str else 0.0
            except ValueError:
                continue

            if qty <= 0:
                continue

            is_jp = code.isdigit() or code in ("285A", "2869") or code.endswith(".T")
            currency = "JPY" if is_jp else "USD"

            if code in holdings:
                ex = holdings[code]
                total = ex["qty"] + qty
                ex["price"] = (ex["price"] * ex["qty"] + price * qty) / total
                ex["qty"]   = total
            else:
                holdings[code] = {
                    "code": code, "name": name,
                    "qty": qty, "price": price,
                    "currency": currency, "account": account,
                    "memo": memo[:30] + "…" if len(memo) > 30 else memo,
                }

        result = list(holdings.values())
        print(f"  ポートフォリオ: {len(result)} 銘柄取得（売却済み除く）")
        return result

    except Exception as e:
        print(f"  ポートフォリオ取得エラー（スキップ）: {e}")
        return []


def portfolio_to_text(holdings: list) -> str:
    """ブリーフィングに挿入するテキストを生成"""
    if not holdings:
        return ""
    lines = ["=== 保有銘柄（個別株）==="]
    for h in holdings:
        sym   = "$" if h["currency"] == "USD" else "¥"
        qty   = int(h["qty"]) if h["qty"] == int(h["qty"]) else h["qty"]
        price = h["price"]
        price_str = f"{price:,.0f}" if h["currency"] == "JPY" else f"{price:,.2f}"
        line  = f"{h['code']} {h['name']}: {qty}株 @{sym}{price_str}"
        if h.get("account"):
            line += f" [{h['account']}]"
        if h.get("memo"):
            line += f" ← {h['memo']}"
        lines.append(line)
    return "\n".join(lines)


# ── データ取得 ─────────────────────────────────────────────────────
def _ohlcv_to_ofi_input(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    eps = 1e-6
    rng = (df["high"] - df["low"]).clip(lower=eps)
    df["price"]      = df["close"]
    df["bid_price"]  = ((df["close"] + df["low"])  / 2).round(4)
    df["ask_price"]  = ((df["close"] + df["high"]) / 2).round(4)
    df["bid_volume"] = (df["volume"] * (df["close"] - df["low"])  / rng).clip(lower=0).astype(int)
    df["ask_volume"] = (df["volume"] * (df["high"] - df["close"]) / rng).clip(lower=0).astype(int)
    return df


def fetch_and_process(stock: dict) -> dict:
    """1銘柄分のフィギュア＋示唆データを生成して返す"""
    code   = stock["code"]
    ticker = stock["ticker"]
    market = stock["market"]
    name   = stock["name"]

    result = {"code": code, "name": name, "market": market}

    # ── イントラデイ ──────────────────────────────────────────────
    try:
        if market == "US":
            from fetch_alpaca_mu import fetch_nbbo_1min
            raw_i = fetch_nbbo_1min(days=5)
        else:
            from fetch_jp_stocks import fetch_intraday
            raw_ohlcv = fetch_intraday(ticker, period="5d", interval="1m")
            raw_i = _ohlcv_to_ofi_input(raw_ohlcv)

        ofi_i = calculate_ofi(raw_i)
        slope_i, _ = intra_analyze(ofi_i)
        fig_i = build_chart(slope_i, market=market)
        fig_i.update_layout(title_text=f"{code} {name} — 1分足 OFI 分析（30分・60分ウィンドウ）")
        ins_i = build_insight(slope_i, timeframe="intraday", symbol=code)
        result["fig_i"] = fig_i
        result["ins_i"] = ins_i
        print(f"    1分足: {len(slope_i)}本 | {ins_i['dominant']} | 連続{ins_i['consecutive']}回")
    except Exception as e:
        print(f"    1分足 エラー: {e}")
        result["fig_i"] = None
        result["ins_i"] = {"dominant": "取得エラー", "summary": str(e),
                            "dominant_pct": 0, "ofi_dir": "−",
                            "stealth_count": 0, "base_rate": 0,
                            "consecutive": 0, "alert_n": 3, "alert_trig": False,
                            "n_reason": "−", "backtest": {"n": 0},
                            "forward_bars": 30, "entry": {}, "lookback": 60}

    # ── 日足 ───────────────────────────────────────────────────────
    try:
        if market == "US":
            from fetch_alpaca_mu import fetch_mu_daily
            raw_d = fetch_mu_daily()
        else:
            from fetch_jp_stocks import fetch_daily
            raw_d = fetch_daily(ticker, period="1y")

        ofi_d = calculate_daily_ofi(raw_d)

        # ── 7日間スコア永続化（数バイトのJSON書き込みのみ）────────────────
        try:
            latest = ofi_d.iloc[-1]
            update_score(code, str(latest["date"]), int(latest["daily_ofi"]))
            result["score_7d"], result["score_entries"] = get_7day_summary(code)
        except Exception as _e:
            result["score_7d"] = 0
            result["score_entries"] = []

        slope_d, _ = daily_analyze(ofi_d)
        fig_d = build_daily_chart(slope_d)
        fig_d.update_layout(title_text=f"{code} {name} — 日足 OFI 分析（5日・20日ウィンドウ）")
        ins_d = build_insight(slope_d, timeframe="daily", symbol=code)
        result["fig_d"] = fig_d
        result["ins_d"] = ins_d
        bt = ins_d["backtest"]
        print(f"    日足  : {len(slope_d)}日 | {ins_d['dominant']} | BT勝率{bt.get('win_rate','−')}%")
    except Exception as e:
        print(f"    日足 エラー: {e}")
        result["fig_d"] = None
        result["ins_d"] = {"dominant": "取得エラー", "summary": str(e),
                            "dominant_pct": 0, "ofi_dir": "−",
                            "stealth_count": 0, "base_rate": 0,
                            "consecutive": 0, "alert_n": 3, "alert_trig": False,
                            "n_reason": "−", "backtest": {"n": 0},
                            "forward_bars": 5, "entry": {}, "lookback": 20}
        result.setdefault("score_7d", 0)
        result.setdefault("score_entries", [])

    return result


# ── HTML 生成 ──────────────────────────────────────────────────────
PHASE_COLOR = {
    "ステルス買い (Stealth Buy) ⚡": "#FFD700",
    "確認上昇 (Bullish)":           "#4CAF50",
    "分配売り (Distribution)":       "#FF5722",
    "確認下落 (Bearish)":            "#78909C",
}

COMMON_CSS = r"""
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #E0E0E0; }
a { text-decoration: none; color: inherit; }
.header {
  background: #1A1A2E; padding: 12px 16px;
  border-bottom: 1px solid #2A3A5C;
  display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 100;
}
.header-left { display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 16px; font-weight: 600; }
.back-btn {
  background: #1E2A3A; color: #90CAF9; border: 1px solid #2A3A5C;
  padding: 6px 12px; border-radius: 6px; font-size: 13px;
}
.header-right { display: flex; gap: 8px; align-items: center; }
.updated-at { font-size: 11px; color: #374151; }
.copy-btn {
  background: #1B4332; color: #95D5B2; border: 1px solid #52B788;
  padding: 6px 12px; border-radius: 6px; cursor: pointer;
  font-size: 13px; font-weight: 500;
}
.copy-btn.copied { background: #1565C0; color: #fff; border-color: #42A5F5; }
.help-btn {
  background: #243454; color: #90CAF9; border: 1px solid #3A5A8C;
  padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.tabs {
  display: flex; gap: 4px; padding: 8px 12px;
  background: #161B27; border-bottom: 1px solid #2A3A5C;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
}
.tab {
  padding: 7px 16px; border-radius: 6px; border: none; cursor: pointer;
  font-size: 13px; font-weight: 500; background: #1E2A3A; color: #90A4AE;
  white-space: nowrap; flex-shrink: 0;
}
.tab.active { background: #1565C0; color: #fff; }
.insight-box { background: #161B27; border-bottom: 1px solid #2A3A5C; padding: 10px 14px; display: none; }
.insight-box.active { display: block; }
.insight-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 8px; margin-bottom: 8px; }
@media (min-width: 640px) { .insight-grid { grid-template-columns: repeat(4,1fr); } }
.ins-card { background: #1A1A2E; border-radius: 6px; padding: 8px 10px; border-left: 3px solid #2A3A5C; }
.ins-label { font-size: 10px; color: #546E7A; text-transform: uppercase; margin-bottom: 3px; }
.ins-val { font-size: 13px; font-weight: 500; line-height: 1.3; }
.ins-sub { font-size: 11px; color: #78909C; margin-top: 2px; }
.insight-row2 { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.alert-on {
  background: linear-gradient(135deg,#1B4332,#2D6A4F); border: 1px solid #52B788;
  border-radius: 6px; padding: 6px 12px; color: #95D5B2; font-weight: 600; font-size: 13px;
}
.alert-off { background: #161B27; border: 1px solid #2A3A5C; border-radius: 6px; padding: 6px 12px; color: #4A5568; font-size: 12px; }
.n-reason { font-size: 10px; color: #546E7A; margin-top: 2px; }
.insight-summary {
  background: #1E2A3A; border-left: 3px solid #90CAF9;
  border-radius: 0 6px 6px 0; padding: 7px 12px;
  font-size: 13px; color: #B0BEC5; margin-top: 6px; line-height: 1.6;
}
.ofi-up { color: #4CAF50; } .ofi-down { color: #FF5722; }
.chart-wrap { display: none; }
.chart-wrap.active { display: block; }
.status-bar { background: #161B27; padding: 4px 16px; color: #374151; font-size: 11px; border-top: 1px solid #1E2A3A; }
.hist-box { background: #16213E; border-left: 3px solid #546E7A; margin: 6px 14px; padding: 8px 12px; border-radius: 0 6px 6px 0; }
.hist-label { font-size: 10px; color: #546E7A; text-transform: uppercase; margin-bottom: 4px; }
.hist-total { font-size: 14px; font-weight: 600; }
.card-hist { font-size: 11px; margin-top: 4px; }
.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.75); z-index: 1000; align-items: center; justify-content: center; }
.modal-overlay.open { display: flex; }
.modal { background: #1A1A2E; border: 1px solid #2A3A5C; border-radius: 10px; padding: 24px; max-width: 640px; width: 92%; max-height: 85vh; overflow-y: auto; position: relative; }
.modal h2 { font-size: 15px; margin-bottom: 14px; color: #90CAF9; }
.modal h3 { font-size: 12px; margin: 14px 0 6px; color: #78909C; text-transform: uppercase; }
.modal-close { position: absolute; top: 12px; right: 14px; background: none; border: none; color: #546E7A; font-size: 20px; cursor: pointer; }
.guide-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 14px; }
.guide-table th,.guide-table td { padding: 7px 10px; text-align: left; border-bottom: 1px solid #2A3A5C; }
.guide-table th { color: #546E7A; }
.guide-table td { color: #B0BEC5; }
.cluster-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 14px; }
.cluster-card { background: #16213E; border-radius: 6px; padding: 9px 12px; }
.cluster-name { font-size: 13px; font-weight: 600; margin-bottom: 3px; }
.cluster-desc { font-size: 12px; color: #78909C; }
"""

HELP_MODAL_HTML = r"""
<div class="modal-overlay" id="modal">
  <div class="modal">
    <button class="modal-close" onclick="closeHelp()">✕</button>
    <h2>OFI チャートの見方ガイド</h2>
    <h3>クラスタ 4 種の意味</h3>
    <div class="cluster-grid">
      <div class="cluster-card"><div class="cluster-name" style="color:#FFD700">⚡ ステルス買い</div><div class="cluster-desc">価格↓ OFI↑ — 機関が静かに仕込み中。最良エントリー候補</div></div>
      <div class="cluster-card"><div class="cluster-name" style="color:#4CAF50">▲ 確認上昇</div><div class="cluster-desc">価格↑ OFI↑ — 素直な上昇。乗れるが出遅れ気味</div></div>
      <div class="cluster-card"><div class="cluster-name" style="color:#FF5722">▼ 分配売り</div><div class="cluster-desc">価格↑ OFI↓ — 機関が高値で売り逃げ中。買わない／利確</div></div>
      <div class="cluster-card"><div class="cluster-name" style="color:#78909C">▼ 確認下落</div><div class="cluster-desc">価格↓ OFI↓ — 素直な下落。様子見</div></div>
    </div>
    <h3>日中の判断フロー</h3>
    <table class="guide-table">
      <thead><tr><th>状況</th><th>読み方</th><th>アクション</th></tr></thead>
      <tbody>
        <tr><td>価格↓ + OFI↑ + ⚡</td><td>機関が静かに拾っている</td><td style="color:#FFD700">エントリー検討</td></tr>
        <tr><td>価格↑ + OFI↓</td><td>機関が売り逃げ中</td><td>乗らない / 利確</td></tr>
        <tr><td>両方↑</td><td>素直な上昇</td><td>出遅れ気味</td></tr>
        <tr><td>両方↓</td><td>素直な下落</td><td>様子見</td></tr>
      </tbody>
    </table>
    <h3>示唆ボックスの読み方</h3>
    <table class="guide-table">
      <tbody>
        <tr><td><b>現在フェーズ</b></td><td>直近60本(1分足)/20本(日足) の最頻クラスタ</td></tr>
        <tr><td><b>累積OFI方向</b></td><td>直近30本のOFI変化方向。価格と逆なら注目</td></tr>
        <tr><td><b>バックテスト</b></td><td>過去シグナル後30分後(1分足)/5日後(日足) の勝率・平均リターン</td></tr>
        <tr><td><b>エントリー条件</b></td><td>シグナル時OFI変化中央値 / 価格変化25パーセンタイルから算出</td></tr>
        <tr><td><b>アラート閾値 N</b></td><td>統計的に偽陽性が1日0.3回以内になる最小連続回数</td></tr>
      </tbody>
    </table>
    <h3>注意事項</h3>
    <table class="guide-table">
      <tbody>
        <tr><td>データ</td><td>OHLC近似版 (bid/ask 実板なし)</td></tr>
        <tr><td>単体シグナル</td><td>OFI だけでは「いつ上がるか」は不明。他の根拠と組み合わせること</td></tr>
        <tr><td>バックテスト</td><td>過去の集計であり将来を保証しない</td></tr>
      </tbody>
    </table>
  </div>
</div>
"""

COMMON_JS = r"""
const PHASE_COLOR = {
  "ステルス買い (Stealth Buy) ⚡": "#FFD700",
  "確認上昇 (Bullish)": "#4CAF50",
  "分配売り (Distribution)": "#FF5722",
  "確認下落 (Bearish)": "#78909C",
};
function renderInsight(id, ins) {
  const el = document.getElementById('ins_' + id);
  if (!el || !ins) return;
  const pc = PHASE_COLOR[ins.dominant] || '#90A4AE';
  const bt = ins.backtest || {};
  const ec = ins.entry   || {};
  const fwd = ins.forward_bars || 30;
  const btText = bt.n > 0
    ? `勝率 <b>${bt.win_rate}%</b> / 平均 <b style="color:${bt.avg_ret>=0?'#4CAF50':'#FF5722'}">${bt.avg_ret>=0?'+':''}${bt.avg_ret}%</b> <span style="color:#546E7A">(N=${bt.n})</span>`
    : '<span style="color:#546E7A">データ不足</span>';
  const ecText = ec.n > 0
    ? `OFI変化 <b>+${Number(ec.ofi_x).toLocaleString()}</b>以上 かつ 価格 <b>-${ec.price_y}%</b>以内`
    : '<span style="color:#546E7A">データ不足</span>';
  const alertHTML = ins.alert_trig
    ? `<div class="alert-on">⚡ アラート発動! 連続<b>${ins.consecutive}</b>回 (閾値${ins.alert_n}回)</div>`
    : `<div class="alert-off">⊘ 未発動 — 連続${ins.consecutive}/${ins.alert_n}回<div class="n-reason">${ins.n_reason||''}</div></div>`;
  el.innerHTML = `
<div class="insight-grid">
  <div class="ins-card" style="border-left-color:${pc}">
    <div class="ins-label">現在フェーズ</div>
    <div class="ins-val" style="color:${pc}">${ins.dominant}</div>
    <div class="ins-sub">${ins.dominant_pct}% / ${ins.lookback||60}本</div>
  </div>
  <div class="ins-card">
    <div class="ins-label">累積OFI方向</div>
    <div class="ins-val ${ins.ofi_dir&&ins.ofi_dir.includes('↑')?'ofi-up':'ofi-down'}">${ins.ofi_dir||'−'}</div>
    <div class="ins-sub">ステルス買い ${ins.stealth_count}回 (${ins.base_rate}%)</div>
  </div>
  <div class="ins-card">
    <div class="ins-label">バックテスト(${fwd}本後)</div>
    <div class="ins-val" style="font-size:12px">${btText}</div>
    <div class="ins-sub">中央値: ${bt.n>0?(bt.med_ret>=0?'+':'')+bt.med_ret+'%':'−'}</div>
  </div>
  <div class="ins-card">
    <div class="ins-label">エントリー条件</div>
    <div class="ins-val" style="font-size:12px">${ecText}</div>
    <div class="ins-sub">シグナル${ec.n||0}件から算出</div>
  </div>
</div>
<div class="insight-row2">${alertHTML}</div>
<div class="insight-summary">💡 ${ins.summary||'分析中...'}</div>`;
}
function openHelp()  { document.getElementById('modal').classList.add('open'); }
function closeHelp() { document.getElementById('modal').classList.remove('open'); }
document.getElementById('modal').addEventListener('click', e => { if(e.target===e.currentTarget) closeHelp(); });
"""


def _make_copy_js(ins_i: dict, ins_d: dict, code: str, name: str,
                  score_7d: int = 0, score_entries: list = None) -> str:
    _s, _label, _ = format_score(score_7d)
    _days = len(score_entries) if score_entries else 0
    return f"""
function buildBriefing() {{
  const now = new Date().toLocaleString('ja-JP', {{timeZone:'Asia/Tokyo'}});
  const ins_i = {json.dumps(ins_i, ensure_ascii=False)};
  const ins_d = {json.dumps(ins_d, ensure_ascii=False)};
  let t = `=== OFI分析ブリーフィング [{code} {name}] ===\\n生成: ${{now}}\\n\\n`;
  for (const [label, ins] of [['1分足', ins_i], ['日足', ins_d]]) {{
    t += `【${{label}}】\\n`;
    t += `フェーズ: ${{ins.dominant}} (${{ins.dominant_pct}}%)\\n`;
    t += `累積OFI: ${{ins.ofi_dir}}\\n`;
    t += `ステルス買い: ${{ins.base_rate}}%発生率 / 連続${{ins.consecutive}}回 (閾値${{ins.alert_n}}回)\\n`;
    const bt = ins.backtest || {{}};
    if (bt.n > 0) t += `バックテスト(${{ins.forward_bars}}本後): 勝率${{bt.win_rate}}% / 平均${{bt.avg_ret>=0?'+':''}}${{bt.avg_ret}}%\\n`;
    const ec = ins.entry || {{}};
    if (ec.n > 0) t += `エントリー条件: OFI変化+${{ec.ofi_x}}以上 かつ 価格-${{ec.price_y}}%以内\\n`;
    if (ins.alert_trig) t += `⚡ アラート発動中!\\n`;
    t += `示唆: ${{ins.summary}}\\n\\n`;
  }}
  t += `【ヒストリカル需給（直近{_days}日間）】\\n`;
  t += `・7日間通算累積OFI: {_s} （{_label}）\\n\\n`;
  t += `---\\n以上を踏まえて今日の売買判断について壁打ちしたい。`;
  return t;
}}
function copyBriefing() {{
  const text = buildBriefing();
  navigator.clipboard.writeText(text).then(() => {{
    const btn = document.getElementById('copy-btn');
    btn.textContent = '✅ コピー完了!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = '📋 コピー'; btn.classList.remove('copied'); }}, 2500);
  }}).catch(() => {{
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
    alert('コピーしました！');
  }});
}}
"""


def make_history_page(history: list, build_time: str) -> str:
    history_json = json.dumps(list(reversed(history)), ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OFI 履歴</title>
<style>
{COMMON_CSS}
.history-list {{ padding: 12px; display: flex; flex-direction: column; gap: 8px; }}
.snap-card {{ background: #1A1A2E; border: 1px solid #2A3A5C; border-radius: 10px; overflow: hidden; }}
.snap-header {{ display: flex; align-items: center; gap: 10px; padding: 12px 14px; cursor: pointer; user-select: none; }}
.snap-ts {{ font-size: 14px; font-weight: 600; color: #90CAF9; }}
.snap-alerts {{ display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }}
.alert-chip {{ background: #1B4332; color: #95D5B2; border: 1px solid #52B788; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
.snap-chevron {{ margin-left: auto; color: #546E7A; font-size: 14px; transition: 0.15s; }}
.snap-body {{ display: none; border-top: 1px solid #2A3A5C; padding: 10px 14px; }}
.snap-body.open {{ display: block; }}
.mini-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 10px; }}
@media (min-width: 640px) {{ .mini-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
.mini-card {{ background: #16213E; border-radius: 6px; padding: 7px 9px; }}
.mini-code {{ font-size: 12px; font-weight: 700; }}
.mini-name {{ font-size: 11px; color: #78909C; }}
.mini-phase {{ font-size: 11px; margin-top: 3px; }}
.snap-copy-btn {{
  background: #1B4332; color: #95D5B2; border: 1px solid #52B788;
  padding: 8px 0; border-radius: 6px; cursor: pointer;
  font-size: 13px; font-weight: 500; width: 100%;
}}
.snap-copy-btn.copied {{ background: #1565C0; color: #fff; border-color: #42A5F5; }}
.empty-msg {{ padding: 48px 24px; color: #546E7A; text-align: center; font-size: 14px; }}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <a href="index.html" class="back-btn">← 一覧</a>
    <h1>OFI 履歴</h1>
  </div>
  <div class="header-right">
    <span class="updated-at" id="updated-at"></span>
    <button class="help-btn" onclick="openHelp()">?</button>
  </div>
</div>

<div class="history-list" id="history-list"></div>
<div class="status-bar">タップで展開 | 📋 でAIチャットにコピー</div>

{HELP_MODAL_HTML}

<script>
{COMMON_JS}

const HISTORY = {history_json};
const PC = {{
  "ステルス買い (Stealth Buy) ⚡": "#FFD700",
  "確認上昇 (Bullish)":           "#4CAF50",
  "分配売り (Distribution)":       "#FF5722",
  "確認下落 (Bearish)":            "#78909C",
}};

function buildSnapText(snap) {{
  let t = `=== OFI全銘柄ブリーフィング ===\\n更新完了: ${{snap.ts_display}}\\n\\n`;
  for (const s of snap.stocks) {{
    t += `▶ ${{s.code}} ${{s.name}}\\n`;
    for (const [label, ins] of [['1分足', s.ins_i], ['日足', s.ins_d]]) {{
      t += `  【${{label}}】${{ins.dominant}} (${{ins.dominant_pct}}%) / OFI:${{ins.ofi_dir}}\\n`;
      t += `  示唆: ${{ins.summary}}\\n`;
      if (ins.alert_trig) t += `  ⚡ アラート発動中!\\n`;
    }}
    t += `\\n`;
  }}
  t += `---\\nこの時点(${{snap.ts_display}})のOFI状況を踏まえて分析してほしい。`;
  return t;
}}

function copySnap(idx, btn) {{
  const text = buildSnapText(HISTORY[idx]);
  navigator.clipboard.writeText(text).then(() => {{
    btn.textContent = '✅ コピー完了!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = '📋 AIにコピー'; btn.classList.remove('copied'); }}, 2500);
  }}).catch(() => {{
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
    alert('コピーしました！');
  }});
}}

function toggleSnap(idx) {{
  const body = document.getElementById('sb' + idx);
  const chev = document.getElementById('sc' + idx);
  const open = body.classList.toggle('open');
  chev.textContent = open ? '▲' : '▼';
}}

function render() {{
  const container = document.getElementById('history-list');
  if (!HISTORY.length) {{
    container.innerHTML = '<div class="empty-msg">履歴がありません。<br>ダッシュボードを更新すると自動で記録されます。</div>';
    return;
  }}
  HISTORY.forEach((snap, idx) => {{
    const alertStocks = snap.stocks.filter(s => s.ins_i.alert_trig || s.ins_d.alert_trig);
    const chips = alertStocks.map(s => `<span class="alert-chip">⚡ ${{s.code}}</span>`).join('');
    const cards = snap.stocks.map(s => {{
      const ci = PC[s.ins_i.dominant] || '#90A4AE';
      const cd = PC[s.ins_d.dominant] || '#90A4AE';
      const flag = s.market === 'US' ? '🇺🇸' : '🇯🇵';
      const alert = (s.ins_i.alert_trig || s.ins_d.alert_trig) ? ' ⚡' : '';
      return `<div class="mini-card">
        <div class="mini-code">${{flag}} ${{s.code}}${{alert}}</div>
        <div class="mini-name">${{s.name}}</div>
        <div class="mini-phase" style="color:${{ci}}">${{s.ins_i.dominant}}</div>
        <div class="mini-phase" style="color:${{cd}}">${{s.ins_d.dominant}}</div>
      </div>`;
    }}).join('');

    container.insertAdjacentHTML('beforeend', `
<div class="snap-card">
  <div class="snap-header" onclick="toggleSnap(${{idx}})">
    <div>
      <div class="snap-ts">${{snap.ts_display}}</div>
      <div class="snap-alerts">${{chips || '<span style="font-size:11px;color:#546E7A">アラートなし</span>'}}</div>
    </div>
    <span class="snap-chevron" id="sc${{idx}}">▼</span>
  </div>
  <div class="snap-body" id="sb${{idx}}">
    <div class="mini-grid">${{cards}}</div>
    <button class="snap-copy-btn" onclick="copySnap(${{idx}}, this)">📋 AIにコピー</button>
  </div>
</div>`);
  }});
}}

render();
document.getElementById('updated-at').textContent =
  new Date('{build_time}').toLocaleString('ja-JP', {{timeZone:'Asia/Tokyo'}});
</script>
</body>
</html>"""


def make_stock_page(stock: dict, result: dict, build_time: str) -> str:
    code   = stock["code"]
    name   = stock["name"]
    ins_i  = result["ins_i"]
    ins_d  = result["ins_d"]
    fig_i  = result.get("fig_i")
    fig_d  = result.get("fig_d")
    score_7d      = result.get("score_7d", 0)
    score_entries = result.get("score_entries", [])
    _s, _label, _color = format_score(score_7d)
    _days = len(score_entries)

    fig_i_json = fig_i.to_json() if fig_i else "null"
    fig_d_json = fig_d.to_json() if fig_d else "null"
    ins_i_json = json.dumps(ins_i, ensure_ascii=False)
    ins_d_json = json.dumps(ins_d, ensure_ascii=False)
    hist_html = f"""<div class="hist-box">
  <div class="hist-label">ヒストリカル需給（直近{_days}日間）</div>
  <div class="hist-total" style="color:{_color}">7日間通算累積OFI: {_s}　（{_label}）</div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{code} {name} — OFI分析</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
{COMMON_CSS}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <a href="index.html" class="back-btn">← 一覧</a>
    <h1>{code} {name}</h1>
  </div>
  <div class="header-right">
    <span class="updated-at" id="updated-at"></span>
    <button class="copy-btn" id="copy-btn" onclick="copyBriefing()">📋 コピー</button>
    <button class="help-btn" onclick="openHelp()">?</button>
  </div>
</div>

<div class="tabs">
  <button class="tab active" onclick="showTab('i',this)">1分足</button>
  <button class="tab" onclick="showTab('d',this)">日足</button>
</div>

<div id="ins_i" class="insight-box active"></div>
<div id="ins_d" class="insight-box"></div>
<div id="chart_i" class="chart-wrap active"><div id="plt_i"></div></div>
<div id="chart_d" class="chart-wrap"><div id="plt_d"></div></div>

{hist_html}

<div class="status-bar">※ OHLC近似版 | Alpaca API 取得後に実板データへ差し替え予定</div>

{HELP_MODAL_HTML}

<script>
{COMMON_JS}
{_make_copy_js(ins_i, ins_d, code, name, score_7d, score_entries)}

const ins_i = {ins_i_json};
const ins_d = {ins_d_json};
const fig_i = {fig_i_json};
const fig_d = {fig_d_json};

const rendered = {{}};
function showTab(id, btn) {{
  document.querySelectorAll('.chart-wrap,.insight-box').forEach(e => e.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(e => e.classList.remove('active'));
  document.getElementById('chart_' + id).classList.add('active');
  document.getElementById('ins_' + id).classList.add('active');
  btn.classList.add('active');
  if (!rendered[id]) {{
    const fig = id === 'i' ? fig_i : fig_d;
    if (fig) Plotly.newPlot('plt_' + id, fig.data, fig.layout, {{responsive: true}});
    rendered[id] = true;
  }}
}}

renderInsight('i', ins_i);
renderInsight('d', ins_d);
if (fig_i) Plotly.newPlot('plt_i', fig_i.data, fig_i.layout, {{responsive: true}});
rendered['i'] = true;

document.getElementById('updated-at').textContent =
  new Date('{build_time}').toLocaleString('ja-JP', {{timeZone: 'Asia/Tokyo'}});
</script>
</body>
</html>"""


def make_index_page(all_results: list, build_time: str,
                    portfolio_text: str = "") -> str:
    # 銘柄カード HTML
    cards_html = ""
    for r in all_results:
        code   = r["code"]
        name   = r["name"]
        ins_i  = r["ins_i"]
        ins_d  = r["ins_d"]
        pc_i   = PHASE_COLOR.get(ins_i.get("dominant", ""), "#90A4AE")
        pc_d   = PHASE_COLOR.get(ins_d.get("dominant", ""), "#90A4AE")
        flag   = "🇺🇸" if r["market"] == "US" else "🇯🇵"
        alert  = "⚡" if ins_i.get("alert_trig") or ins_d.get("alert_trig") else ""
        summary = ins_i.get("summary", "")[:60] + "…" if len(ins_i.get("summary","")) > 60 else ins_i.get("summary","")
        s7d = r.get("score_7d", 0)
        s7_str, s7_label, s7_color = format_score(s7d)

        cards_html += f"""
<a href="{code.lower()}.html" class="stock-card">
  <div class="card-header">
    <span class="card-flag">{flag}</span>
    <span class="card-code">{code}</span>
    <span class="card-name">{name}</span>
    <span class="card-alert">{alert}</span>
  </div>
  <div class="card-phases">
    <div class="card-phase">
      <span class="phase-label">1分足</span>
      <span class="phase-val" style="color:{pc_i}">{ins_i.get('dominant','−')}</span>
      <span class="phase-pct">({ins_i.get('dominant_pct',0)}%)</span>
    </div>
    <div class="card-phase">
      <span class="phase-label">日足</span>
      <span class="phase-val" style="color:{pc_d}">{ins_d.get('dominant','−')}</span>
      <span class="phase-pct">({ins_d.get('dominant_pct',0)}%)</span>
    </div>
  </div>
  <div class="card-summary">{summary}</div>
  <div class="card-hist" style="color:{s7_color}">7日累積OFI: {s7_str}　{s7_label}</div>
</a>"""

    # 全銘柄ブリーフィング用JS
    all_ins_json = json.dumps(
        [{"code": r["code"], "name": r["name"],
          "ins_i": r["ins_i"], "ins_d": r["ins_d"],
          "score_7d": r.get("score_7d", 0),
          "score_entries": r.get("score_entries", [])} for r in all_results],
        ensure_ascii=False
    )

    # build_time を Python 側で JST 文字列に変換（JavaScript Date パース問題を回避）
    _jst = timezone(timedelta(hours=9))
    try:
        _dt = datetime.fromisoformat(build_time).astimezone(_jst)
        build_time_jst = _dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        build_time_jst = build_time

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OFI ダッシュボード</title>
<style>
{COMMON_CSS}
.page-title {{ font-size: 18px; font-weight: 700; }}
.badge {{ background: #243454; color: #90CAF9; font-size: 11px; padding: 2px 8px; border-radius: 4px; }}
.stock-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap: 12px; padding: 16px; }}
.stock-card {{
  background: #1A1A2E; border: 1px solid #2A3A5C; border-radius: 10px;
  padding: 14px 16px; display: block; transition: 0.15s;
}}
.stock-card:hover, .stock-card:active {{ border-color: #4A6A9C; background: #1E2A3E; }}
.card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
.card-flag {{ font-size: 16px; }}
.card-code {{ font-size: 16px; font-weight: 700; }}
.card-name {{ font-size: 13px; color: #78909C; }}
.card-alert {{ margin-left: auto; font-size: 16px; }}
.card-phases {{ display: flex; gap: 12px; margin-bottom: 8px; }}
.card-phase {{ flex: 1; background: #16213E; border-radius: 6px; padding: 6px 8px; }}
.phase-label {{ font-size: 10px; color: #546E7A; display: block; margin-bottom: 3px; }}
.phase-val {{ font-size: 12px; font-weight: 600; }}
.phase-pct {{ font-size: 11px; color: #546E7A; margin-left: 4px; }}
.card-summary {{ font-size: 12px; color: #78909C; line-height: 1.5; }}
.copy-all-btn {{
  background: #1B4332; color: #95D5B2; border: 1px solid #52B788;
  padding: 8px 18px; border-radius: 8px; cursor: pointer;
  font-size: 14px; font-weight: 600;
}}
.copy-all-btn.copied {{ background: #1565C0; color: #fff; border-color: #42A5F5; }}
.update-btn {{
  background: #1B3A5C; color: #64B5F6; border: 1px solid #2196F3;
  padding: 8px 14px; border-radius: 8px; cursor: pointer;
  font-size: 13px; font-weight: 600; transition: background 0.2s;
}}
.update-btn.running {{ background: #3E2723; color: #FF8A65; border-color: #FF5722; }}
.update-btn.done    {{ background: #1B5E20; color: #A5D6A7; border-color: #4CAF50; }}
.update-btn.error   {{ background: #4A1515; color: #EF9A9A; border-color: #E53935; }}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <h1 class="page-title">OFI 分析</h1>
    <span class="badge">6銘柄</span>
    <span class="badge">OHLC近似</span>
  </div>
  <div class="header-right">
    <span class="updated-at" id="updated-at"></span>
    <button class="update-btn" id="update-btn" onclick="triggerUpdate()">🔄 今すぐ更新</button>
    <button class="copy-all-btn" id="copy-all-btn" onclick="copyAll()">📋 全銘柄コピー</button>
    <a href="history.html" class="help-btn" style="text-decoration:none">🕐</a>
    <button class="help-btn" onclick="openHelp()">?</button>
  </div>
</div>

<div class="stock-grid">
{cards_html}
</div>

<div class="status-bar">タップで銘柄詳細へ | 毎朝 8:00 JST 自動更新</div>

{HELP_MODAL_HTML}

<script>
{COMMON_JS}

const allData = {all_ins_json};
const portfolioText = `__PORTFOLIO_TEXT__`;

function copyAll() {{
  let t = `=== OFI全銘柄ブリーフィング ===\\n更新完了: {build_time_jst}\\n`;
  if (portfolioText) t += `\\n${{portfolioText}}\\n`;
  t += `\\n`;
  for (const s of allData) {{
    t += `▶ ${{s.code}} ${{s.name}}\\n`;
    for (const [label, ins] of [['1分足', s.ins_i], ['日足', s.ins_d]]) {{
      t += `  【${{label}}】${{ins.dominant}} (${{ins.dominant_pct}}%) / OFI:${{ins.ofi_dir}}\\n`;
      t += `  示唆: ${{ins.summary}}\\n`;
      if (ins.alert_trig) t += `  ⚡ アラート発動中!\\n`;
    }}
    const sc = s.score_7d || 0;
    const scStr = sc > 0 ? `+${{sc.toLocaleString()}}` : sc.toLocaleString();
    const scLabel = sc > 0 ? '買い超過' : sc < 0 ? '売り超過' : '中立';
    const scDays = (s.score_entries || []).length;
    t += `  【ヒストリカル需給（直近${{scDays}}日間）】7日間通算累積OFI: ${{scStr}} (${{scLabel}})\\n`;
    t += `\\n`;
  }}
  t += `---\\n保有銘柄の状況を踏まえて、今日最も注目すべき銘柄と判断根拠を教えて。`;
  navigator.clipboard.writeText(t).then(() => {{
    const btn = document.getElementById('copy-all-btn');
    btn.textContent = '✅ コピー完了!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = '📋 全銘柄コピー'; btn.classList.remove('copied'); }}, 2500);
  }}).catch(() => {{
    const ta = document.createElement('textarea');
    ta.value = t; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
    alert('コピーしました！');
  }});
}}

document.getElementById('updated-at').textContent =
  new Date('{build_time}').toLocaleString('ja-JP', {{timeZone:'Asia/Tokyo'}});

async function triggerUpdate() {{
  const btn = document.getElementById('update-btn');
  let token = localStorage.getItem('gh_trigger_token') || '';
  if (!token) {{
    token = prompt('GitHub PAT (Actions権限) を入力してください。\\n一度入力するとこのデバイスに保存されます。');
    if (!token) return;
    localStorage.setItem('gh_trigger_token', token.trim());
  }}
  btn.textContent = '⏳ 更新中...';
  btn.className = 'update-btn running';
  btn.disabled = true;
  try {{
    const res = await fetch(
      'https://api.github.com/repos/mantech0/ofi-analysis/actions/workflows/update.yml/dispatches',
      {{
        method: 'POST',
        headers: {{
          'Authorization': 'token ' + token,
          'Accept': 'application/vnd.github.v3+json',
          'Content-Type': 'application/json',
        }},
        body: JSON.stringify({{ref: 'main'}}),
      }}
    );
    if (res.status === 204) {{
      btn.textContent = '✅ 更新開始! (約1分)';
      btn.className = 'update-btn done';
      setTimeout(() => {{ btn.textContent = '🔄 今すぐ更新'; btn.className = 'update-btn'; btn.disabled = false; }}, 8000);
    }} else if (res.status === 401) {{
      localStorage.removeItem('gh_trigger_token');
      btn.textContent = '❌ 認証エラー(再入力)';
      btn.className = 'update-btn error';
      setTimeout(() => {{ btn.textContent = '🔄 今すぐ更新'; btn.className = 'update-btn'; btn.disabled = false; }}, 3000);
    }} else {{
      btn.textContent = '❌ エラー ' + res.status;
      btn.className = 'update-btn error';
      setTimeout(() => {{ btn.textContent = '🔄 今すぐ更新'; btn.className = 'update-btn'; btn.disabled = false; }}, 3000);
    }}
  }} catch(e) {{
    btn.textContent = '❌ 通信エラー';
    btn.className = 'update-btn error';
    setTimeout(() => {{ btn.textContent = '🔄 今すぐ更新'; btn.className = 'update-btn'; btn.disabled = false; }}, 3000);
  }}
}}
</script>
</body>
</html>"""
    # portfolio_text はバックティックやブレースを含む可能性があるため replace で埋め込む
    html = html.replace("__PORTFOLIO_TEXT__", portfolio_text.replace("`", "'").replace("\\", "\\\\"))
    return html


# ── メイン ────────────────────────────────────────────────────────
if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    build_time = datetime.now(timezone.utc).isoformat()

    print("=" * 60)
    print("  OFI ダッシュボード生成 (全銘柄)")
    print("=" * 60)

    # ポートフォリオ取得
    print("\n[PORTFOLIO] Google Sheets からポートフォリオ取得")
    holdings = fetch_portfolio()
    ptxt = portfolio_to_text(holdings)
    if ptxt:
        print(ptxt)
    else:
        print("  （PORTFOLIO_CSV_URL 未設定 or 取得エラー — スキップ）")

    all_results = []
    for stock in STOCKS:
        print(f"\n[{stock['code']}] {stock['name']} ({stock['ticker']})")
        result = fetch_and_process(stock)
        result["code"]   = stock["code"]
        result["name"]   = stock["name"]
        result["market"] = stock["market"]
        all_results.append(result)

        # 銘柄別ページを出力
        html = make_stock_page(stock, result, build_time)
        out_path = OUT_DIR / f"{stock['code'].lower()}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"    → {out_path}")

    # 一覧ページを出力
    print("\n[INDEX] 銘柄一覧ページ生成")
    index_html = make_index_page(all_results, build_time, portfolio_text=ptxt)
    (OUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"    → {OUT_DIR}/index.html")

    # 履歴スナップショットを保存して history.html を生成
    print("\n[HISTORY] 履歴スナップショット保存 & history.html 生成")
    history = save_snapshot(all_results, build_time)
    history_html = make_history_page(history, build_time)
    (OUT_DIR / "history.html").write_text(history_html, encoding="utf-8")
    print(f"    → {OUT_DIR}/history.html")

    # アラート銘柄をハイライト
    print("\n" + "=" * 60)
    print("  アラート状況:")
    for r in all_results:
        i_alert = r["ins_i"].get("alert_trig", False)
        d_alert = r["ins_d"].get("alert_trig", False)
        mark = "⚡" if i_alert or d_alert else "  "
        i_phase = r["ins_i"].get("dominant","−")
        d_phase = r["ins_d"].get("dominant","−")
        print(f"  {mark} {r['code']:5s} {r['name']:8s}  1分足:{i_phase[:8]}  日足:{d_phase[:8]}")
    print("=" * 60)
    print(f"\n  → {OUT_DIR}/index.html を開いてください")
