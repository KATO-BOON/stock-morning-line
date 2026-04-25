"""メインエントリポイント。毎朝8時に呼ばれる。"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gemini_client import summarize
from line_client import broadcast
from news_fetch import fetch_news
from stock_data import all_snapshots

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.json"


def _load_settings() -> dict:
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


def _should_send_today(settings: dict) -> bool:
    """平日 or 許可週末リストに含まれるなら配信。"""
    today = datetime.now(JST).date()
    if today.weekday() < 5:  # Mon-Fri
        return True
    allowed = set(settings.get("allowed_weekends", []))
    return today.isoformat() in allowed


def main() -> int:
    settings = _load_settings()

    if not _should_send_today(settings):
        print(f"[skip] {datetime.now(JST).date()} は非配信日")
        return 0

    print("[info] ニュース取得中…")
    news_items = fetch_news()
    print(f"[info] ニュース {len(news_items)} 件")

    print("[info] マーケットスナップショット取得中(日米指数・為替・商品)…")
    snaps = all_snapshots()
    print(f"[info] スナップショット {len(snaps)} 件")

    print("[info] Gemini要約中…")
    message = summarize(
        budget_man=int(settings.get("budget_man", 10)),
        snapshots=[s.to_dict() for s in snaps],
        news=[n.to_dict() for n in news_items],
        max_news_chars=int(settings.get("max_news_chars", 220)),
        important_max_chars=int(settings.get("important_news_max_chars", 400)),
        allow_odd_lots=bool(settings.get("allow_odd_lots", True)),
    )

    print("[info] LINE送信中…")
    status = broadcast(message)
    print(f"[ok] LINE送信完了 HTTP {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
