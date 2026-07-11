"""
ofi_daily_score.py
日足OFIスコアを直近7日分だけJSONに永続化する超軽量モジュール。
依存: 標準ライブラリのみ（pandas/numpy不使用）
メモリ: 最大 7件 × 6銘柄 ≈ 1KB 未満
"""
import json
from pathlib import Path

_SCORE_FILE = Path(__file__).parent / "logs" / "ofi_daily_scores.json"
_MAX_DAYS = 7


def _load() -> dict:
    if not _SCORE_FILE.exists():
        return {}
    try:
        with open(_SCORE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    _SCORE_FILE.parent.mkdir(exist_ok=True)
    with open(_SCORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def update_score(code: str, score_date: str, daily_ofi: int) -> None:
    """その日の確定OFIスコアを保存。同一日付は上書き、7件超は古い順に自動削除。"""
    data = _load()
    entries = [e for e in data.get(code, []) if e["d"] != score_date]
    entries.append({"d": score_date, "v": int(daily_ofi)})
    entries.sort(key=lambda x: x["d"])
    data[code] = entries[-_MAX_DAYS:]
    _save(data)


def get_7day_summary(code: str) -> tuple:
    """
    Returns:
        total (int)  : 直近7日間の通算OFI合計
        entries (list): [{"d": "2026-07-07", "v": 125000}, ...]
    """
    entries = _load().get(code, [])
    return sum(e["v"] for e in entries), list(entries)


def format_score(total: int) -> tuple:
    """
    Returns:
        sign_str (str)  : "+25,000" / "-12,000" / "0"
        label    (str)  : "買い超過" / "売り超過" / "中立"
        color    (str)  : CSS color string
    """
    if total > 0:
        return f"+{total:,}", "買い超過", "#4CAF50"
    elif total < 0:
        return f"{total:,}", "売り超過", "#FF5722"
    else:
        return "0", "中立", "#78909C"
