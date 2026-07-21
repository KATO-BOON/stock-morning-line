"""朝ブリーフの推奨銘柄を記録し、後日の実績を検証して勝率を出す。

「精度が上がった」を感想でなく数字で確認するための仕組み。
- 推奨日の始値をエントリー価格とみなす（ブリーフは寄付前に届くため現実的）
- 5営業日後・20営業日後のリターンを計測
- 勝率/平均リターンを集計して翌朝のブリーフに載せる
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
PICKS_PATH = ROOT / "state" / "picks.json"

HORIZONS = (5, 20)  # 営業日


def _load() -> dict:
    if not PICKS_PATH.exists():
        return {"picks": []}
    try:
        return json.loads(PICKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"picks": []}


def _save(data: dict) -> None:
    PICKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PICKS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_picks(picks: list[dict]) -> int:
    """本日の推奨を記録。picks=[{code,name,prev_close}]。同日重複はスキップ。"""
    data = _load()
    today = datetime.now(JST).date().isoformat()
    existing = {(p["date"], p["code"]) for p in data["picks"]}
    added = 0
    for p in picks:
        key = (today, p["code"])
        if key in existing:
            continue
        data["picks"].append({
            "date": today,
            "code": p["code"],
            "name": p.get("name", p["code"]),
            "ref_close": p.get("prev_close"),  # 推奨時点の前日終値(参考)
            "entry": None,                      # 推奨日の始値(検証時に確定)
            "ret_5d": None,
            "ret_20d": None,
        })
        added += 1
    if added:
        _save(data)
        print(f"[ok] 推奨{added}件を記録 ({today})")
    return added


def evaluate() -> int:
    """未評価の推奨について、経過営業日数が足りていればリターンを確定する。"""
    data = _load()
    picks = data.get("picks", [])
    if not picks:
        return 0

    # 銘柄ごとにまとめて価格取得（API節約）
    pending = [p for p in picks
               if any(p.get(f"ret_{h}d") is None for h in HORIZONS)]
    if not pending:
        return 0

    codes = sorted({p["code"] for p in pending})
    updated = 0
    for code in codes:
        try:
            # 最古の未評価日から取得
            oldest = min(p["date"] for p in pending if p["code"] == code)
            start = (datetime.fromisoformat(oldest).date() - timedelta(days=5)).isoformat()
            hist = yf.Ticker(f"{code}.T").history(start=start, interval="1d",
                                                  auto_adjust=False)
            hist = hist.dropna(subset=["Close"])
            if hist.empty:
                continue
            dates = [d.date().isoformat() for d in hist.index]
            for p in pending:
                if p["code"] != code:
                    continue
                if p["date"] not in dates:
                    continue  # 推奨日が休場等でデータなし
                i = dates.index(p["date"])
                # エントリー = 推奨日の始値（寄付で買う想定）
                if p.get("entry") is None:
                    try:
                        p["entry"] = round(float(hist["Open"].iloc[i]), 1)
                    except Exception:
                        p["entry"] = round(float(hist["Close"].iloc[i]), 1)
                entry = p.get("entry")
                if not entry:
                    continue
                for h in HORIZONS:
                    key = f"ret_{h}d"
                    if p.get(key) is not None:
                        continue
                    if i + h < len(hist):
                        px = float(hist["Close"].iloc[i + h])
                        p[key] = round((px - entry) / entry * 100, 2)
                        updated += 1
        except Exception as e:
            print(f"[warn] {code} 評価失敗: {e}")
            continue

    if updated:
        _save(data)
        print(f"[ok] {updated}件の実績を確定")
    return updated


def summary(limit: int = 30) -> dict:
    """直近の推奨実績を集計。limit=集計対象の最大件数(新しい順)。"""
    data = _load()
    picks = sorted(data.get("picks", []), key=lambda p: p["date"], reverse=True)
    out: dict = {"total_recorded": len(picks)}
    for h in HORIZONS:
        key = f"ret_{h}d"
        vals = [p[key] for p in picks if p.get(key) is not None][:limit]
        if vals:
            wins = sum(1 for v in vals if v > 0)
            out[f"{h}d"] = {
                "n": len(vals),
                "win_rate": round(wins / len(vals) * 100, 1),
                "avg_ret": round(sum(vals) / len(vals), 2),
                "best": round(max(vals), 2),
                "worst": round(min(vals), 2),
            }
    return out


def summary_text() -> str:
    """ブリーフに載せる短い実績テキスト。データ不足なら空文字。"""
    s = summary()
    parts = []
    for h in HORIZONS:
        d = s.get(f"{h}d")
        if d and d["n"] >= 3:
            parts.append(
                f"{h}日後: 勝率{d['win_rate']}% 平均{d['avg_ret']:+.1f}% (n={d['n']})"
            )
    if not parts:
        n = s.get("total_recorded", 0)
        if n:
            return f"（検証中: 推奨{n}件を記録済み。実績は5営業日後から集計されます）"
        return ""
    return " / ".join(parts)


if __name__ == "__main__":
    evaluate()
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    print("TEXT:", summary_text())
