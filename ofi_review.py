"""
ofi_review.py
過去のOFIスナップショットを一覧・表示・クリップボードコピーするツール。

使い方:
  python ofi_review.py list               # 過去の実行一覧を表示
  python ofi_review.py show 20240115_1400 # 指定IDのデータを表示
  python ofi_review.py copy 20240115_1400 # AIに貼り付けられる形でクリップボードにコピー
"""

import json
import os
import subprocess
import sys

import pandas as pd

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_INDEX_PATH = os.path.join(LOGS_DIR, "run_log.json")


def load_index() -> list:
    if not os.path.exists(LOG_INDEX_PATH):
        print("[ERROR] ログが見つかりません。先に OFI_dummy_gen.py を実行してください。")
        sys.exit(1)
    with open(LOG_INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_list():
    entries = load_index()
    print(f"{'ID':<18} {'実行日時':<22} {'行数':>5} {'価格(始)':>10} {'価格(終)':>10} {'累積OFI終値':>12} {'状態'}")
    print("-" * 90)
    for e in entries:
        print(
            f"{e['id']:<18} {e['timestamp']:<22} {e['rows']:>5} "
            f"{e['price_start']:>10.1f} {e['price_end']:>10.1f} "
            f"{e['cumulative_ofi_final']:>12.0f} {e['status']}"
        )


def find_entry(run_id: str) -> dict:
    entries = load_index()
    matches = [e for e in entries if e["id"] == run_id]
    if not matches:
        print(f"[ERROR] ID '{run_id}' が見つかりません。'python ofi_review.py list' で確認してください。")
        sys.exit(1)
    return matches[-1]


def load_csv(entry: dict) -> pd.DataFrame:
    csv_path = os.path.join(LOGS_DIR, entry["filename"])
    if not os.path.exists(csv_path):
        print(f"[ERROR] CSVが見つかりません: {csv_path}")
        sys.exit(1)
    return pd.read_csv(csv_path)


def cmd_show(run_id: str):
    entry = find_entry(run_id)
    df = load_csv(entry)

    print(f"\n{'='*60}")
    print(f"  OFI スナップショット  [{entry['id']}]")
    print(f"{'='*60}")
    print(f"  実行日時     : {entry['timestamp']}")
    print(f"  データ行数   : {entry['rows']} 行")
    print(f"  価格         : {entry['price_start']:.1f} → {entry['price_end']:.1f}  "
          f"(Δ{entry['price_end'] - entry['price_start']:+.1f})")
    print(f"  累積OFI終値  : {entry['cumulative_ofi_final']:,.0f}")
    print(f"  OFI 平均     : {entry['ofi_mean']:.2f}")
    print()

    cols = ["timestamp", "price", "ofi", "cumulative_ofi"]
    print("--- 先頭 5行 ---")
    print(df[cols].head(5).to_string(index=False))
    print()
    print("--- 末尾 5行 ---")
    print(df[cols].tail(5).to_string(index=False))
    print()

    print("--- 統計 ---")
    stats = df[["ofi", "cumulative_ofi"]].describe().round(2)
    print(stats.to_string())


def build_copy_text(entry: dict, df: pd.DataFrame) -> str:
    cols = ["timestamp", "price", "ofi", "cumulative_ofi"]

    def to_md_table(sub: pd.DataFrame) -> str:
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join(["---"] * len(cols)) + " |"
        rows = []
        for _, row in sub[cols].iterrows():
            rows.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
        return "\n".join([header, sep] + rows)

    price_delta = entry["price_end"] - entry["price_start"]
    stats = df[["ofi", "cumulative_ofi"]].describe().round(2)

    lines = [
        f"## OFI スナップショット ({entry['id']})",
        "",
        "### サマリー",
        f"- 実行日時: {entry['timestamp']}",
        f"- データ行数: {entry['rows']} 行",
        f"- 価格: {entry['price_start']:.1f} → {entry['price_end']:.1f} (Δ{price_delta:+.1f})",
        f"- 累積OFI 終値: {entry['cumulative_ofi_final']:,.0f}",
        f"- OFI 平均: {entry['ofi_mean']:.2f}",
        "",
        "### 先頭 10行",
        to_md_table(df.head(10)),
        "",
        "### 末尾 10行",
        to_md_table(df.tail(10)),
        "",
        "### OFI 統計",
        "```",
        stats.to_string(),
        "```",
    ]
    return "\n".join(lines)


def cmd_copy(run_id: str):
    entry = find_entry(run_id)
    df = load_csv(entry)
    text = build_copy_text(entry, df)

    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    print(f"[OK] '{run_id}' のスナップショットをクリップボードにコピーしました。")
    print("     AIチャットにそのまま貼り付けて議論できます。")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list()
    elif cmd == "show":
        if len(sys.argv) < 3:
            print("[ERROR] IDを指定してください。例: python ofi_review.py show 20240115_1400")
            sys.exit(1)
        cmd_show(sys.argv[2])
    elif cmd == "copy":
        if len(sys.argv) < 3:
            print("[ERROR] IDを指定してください。例: python ofi_review.py copy 20240115_1400")
            sys.exit(1)
        cmd_copy(sys.argv[2])
    else:
        print(f"[ERROR] 不明なコマンド: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
