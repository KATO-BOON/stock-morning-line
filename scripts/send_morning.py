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
from stock_universe import fetch_candidates
from trading_day import is_tse_holiday, reason as day_reason, today_jst

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.json"


def _load_settings() -> dict:
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


def _should_send_today(settings: dict) -> bool:
    """営業日(東証) もしくは 例外日付に含まれるなら配信。

    - 土日・祝日・年末年始は基本スキップ
    - allowed_weekends/allowed_dates に明示された日付は強制配信
    """
    today = today_jst()
    iso = today.isoformat()
    # 例外日付に含まれていれば強制配信
    exceptions: set[str] = set(settings.get("allowed_weekends", []))
    exceptions.update(settings.get("allowed_dates", []))
    if iso in exceptions:
        return True
    # 営業日なら配信
    if not is_tse_holiday(today):
        return True
    return False


def main() -> int:
    settings = _load_settings()

    if not _should_send_today(settings):
        t = today_jst()
        print(f"[skip] {t} は非配信日 ({day_reason(t)})")
        return 0

    print("[info] ニュース取得中…")
    news_items = fetch_news()
    print(f"[info] ニュース {len(news_items)} 件")

    print("[info] マーケットスナップショット取得中(日米指数・為替・商品)…")
    snaps = all_snapshots()
    print(f"[info] スナップショット {len(snaps)} 件")

    budget_man = int(settings.get("budget_man", 10))
    print(f"[info] 予算{budget_man}万円の候補銘柄取得中…")
    candidates = fetch_candidates(budget_man)

    print("[info] Gemini要約中…")
    message = summarize(
        budget_man=budget_man,
        snapshots=[s.to_dict() for s in snaps],
        news=[n.to_dict() for n in news_items],
        candidates=[c.to_dict() for c in candidates],
        max_news_chars=int(settings.get("max_news_chars", 220)),
        important_max_chars=int(settings.get("important_news_max_chars", 400)),
        allow_odd_lots=False,
    )

    # ハルシネーション後処理: 候補リストにない銘柄コードを警告
    cand_codes = {c.code for c in candidates}
    import re as _re
    found = set(_re.findall(r"(?<!\d)(\d{4})(?!\d)", message))
    bad = [c for c in found if c not in cand_codes]
    if bad:
        print(f"[warn] 候補外コード検出: {bad}")
        message += f"\n\n⚠️ 注意: 上記{','.join(bad[:5])}は候補外コードです。実在確認してから判断ください。"

    print("[info] LINE送信中…")
    status = broadcast(message)
    print(f"[ok] LINE送信完了 HTTP {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
