"""メインエントリポイント。毎朝8時に呼ばれる。"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gemini_client import summarize
from holdings_analysis import analyze_holdings
from line_client import broadcast
from news_fetch import fetch_news
from stock_data import all_snapshots
from stock_universe import fetch_candidates
from trading_day import is_tse_holiday, reason as day_reason, today_jst

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.json"
STATE_PATH = ROOT / "state" / "last_sent.json"


def _load_settings() -> dict:
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


def _already_sent_today() -> bool:
    """本日(JST)既に配信済みなら True。冗長cron実行時の重複防止。"""
    if not STATE_PATH.exists():
        return False
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return state.get("morning_date") == today_jst().isoformat()
    except Exception:
        return False


def _mark_sent_today() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    state["morning_date"] = today_jst().isoformat()
    state["morning_at"] = datetime.now(JST).isoformat()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _should_send_today(settings: dict) -> bool:
    """配信スケジュール判定。

    delivery_mode:
      - "off": 配信しない
      - "weekdays": 営業日(月〜金、祝日・年末年始除く)のみ配信
      - "all": 毎日配信
    旧 delivery_enabled=False は "off" 互換扱い、未設定は "weekdays" デフォルト。
    """
    mode = settings.get("delivery_mode")
    if mode is None:
        mode = "off" if settings.get("delivery_enabled") is False else "weekdays"
    if mode == "off":
        return False
    if mode == "all":
        return True
    # weekdays
    return not is_tse_holiday(today_jst())


def main() -> int:
    settings = _load_settings()

    if not _should_send_today(settings):
        t = today_jst()
        mode = settings.get("delivery_mode") or ("off" if settings.get("delivery_enabled") is False else "weekdays")
        if mode == "off":
            print(f"[skip] 配信停止中（delivery_mode=off）")
        else:
            print(f"[skip] {t} は非配信日 ({day_reason(t)}) / mode={mode}")
        return 0

    # 冗長cron対策: 本日既に配信済みなら重複送信せず
    if _already_sent_today():
        print(f"[skip] 本日({today_jst()})は既に配信済み（冗長cron検知）")
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

    # 過去の推奨実績を検証して勝率を出す（当たっているか数字で確認するため）
    track_text = ""
    try:
        import pick_tracker
        pick_tracker.evaluate()
        track_text = pick_tracker.summary_text()
        if track_text:
            print(f"[info] 推奨実績: {track_text}")
    except Exception as e:
        print(f"[warn] 実績集計スキップ: {e}")

    holdings = settings.get("holdings", [])
    if holdings:
        print(f"[info] 保有{len(holdings)}銘柄の動向分析中…")
        h_briefs = analyze_holdings(holdings, news_items)
        h_briefs_dict = [b.to_dict() for b in h_briefs]
    else:
        h_briefs_dict = []

    print("[info] Gemini要約中…")
    message = summarize(
        budget_man=budget_man,
        snapshots=[s.to_dict() for s in snaps],
        news=[n.to_dict() for n in news_items],
        candidates=[c.to_dict() for c in candidates],
        holdings_briefs=h_briefs_dict,
        max_news_chars=int(settings.get("max_news_chars", 220)),
        important_max_chars=int(settings.get("important_news_max_chars", 400)),
        allow_odd_lots=False,
        track_text=track_text,
    )

    # ハルシネーション後処理: 注目銘柄セクション内のコードのみ検査
    # （ニュース本文の「6000億円」等を誤検知しないようセクション限定）
    cand_codes = {c.code for c in candidates}
    import re as _re
    # 🎯 セクションから次のセクション(⚠️/💡/━)までを抽出
    m = _re.search(r"🎯(.*?)(?:⚠️|💡|━━|$)", message, _re.DOTALL)
    rec_section = m.group(1) if m else ""
    # 「① 7203 銘柄名」形式 = 行頭マーカー直後の4桁のみ拾う
    rec_codes = set(_re.findall(r"[①②③④⑤\-・]\s*(\d{4})\b", rec_section))
    bad = [c for c in rec_codes if c not in cand_codes]
    if bad:
        print(f"[warn] 注目銘柄に候補外コード: {bad}")
        message += f"\n\n⚠️ {','.join(bad[:5])} は推奨候補外。実在をご確認ください。"
    else:
        print(f"[ok] 注目銘柄コードは全て候補内")

    # 推奨銘柄を記録（後日リターンを検証して勝率を出すため）
    try:
        import pick_tracker
        by_code = {c.code: c for c in candidates}
        to_record = [
            {"code": c, "name": by_code[c].name, "prev_close": by_code[c].prev_close}
            for c in rec_codes if c in by_code
        ]
        if to_record:
            pick_tracker.record_picks(to_record)
    except Exception as e:
        print(f"[warn] 推奨記録スキップ: {e}")

    print("[info] LINE送信中…")
    status = broadcast(message)
    print(f"[ok] LINE送信完了 HTTP {status}")
    _mark_sent_today()
    print(f"[ok] 本日配信済みフラグを保存")

    # AI予測(損切/利確) も生成しておく（失敗してもbrief配信は成功扱い）
    try:
        print("[info] SL/TP予測を生成中…")
        import predict_levels
        predict_levels.main()
    except Exception as e:
        print(f"[warn] 予測生成失敗（無視）: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
