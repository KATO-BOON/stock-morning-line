"""保有銘柄の現在値をチェックして、損切・利確ライン突破時にLINE通知。

settings.json の holdings 配列の各エントリ:
  {
    "id": "uniq",
    "code": "7201",          # 4桁証券コード
    "name": "日産自動車",
    "shares": 100,
    "avg_price": 502,         # 取得単価
    "stop_loss": 480,         # 円。これ以下で通知
    "take_profit": 540,       # 円。これ以上で通知
    "added_at": "ISO8601"
  }

state/alerts.json で重複通知を防止する（同じ条件は1日1回まで）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from line_client import broadcast

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "config" / "settings.json"
STATE_DIR = ROOT / "state"
ALERT_STATE = STATE_DIR / "alerts.json"


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_current_price(code: str) -> float | None:
    """4桁コード → yfinance で現在値（intraday）取得。"""
    try:
        t = yf.Ticker(f"{code}.T")
        # まず直近1分足をトライ（市場時間中）
        try:
            hist = t.history(period="1d", interval="1m", auto_adjust=False)
            hist = hist.dropna(subset=["Close"])
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        # フォールバック: 日足の前日終値
        hist = t.history(period="5d", interval="1d", auto_adjust=False)
        hist = hist.dropna(subset=["Close"])
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"[warn] {code} 価格取得失敗: {e}")
    return None


def _is_market_hours() -> bool:
    now = datetime.now(JST)
    if now.weekday() >= 5:
        return False
    # 9:00 - 15:30
    open_ = now.replace(hour=9, minute=0, second=0, microsecond=0)
    close_ = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_ <= now <= close_


def main() -> int:
    settings = _load(SETTINGS, {})
    holdings: list[dict] = settings.get("holdings", [])
    if not holdings:
        print("[info] 保有銘柄なし → 終了")
        return 0

    state: dict = _load(ALERT_STATE, {})
    today = datetime.now(JST).date().isoformat()
    notify_buf: list[str] = []
    state_changed = False

    for h in holdings:
        hid = h["id"]
        code = str(h["code"])
        name = h.get("name", code)
        shares = int(h["shares"])
        avg_price = float(h["avg_price"])
        stop_loss = float(h.get("stop_loss", 0))
        take_profit = float(h.get("take_profit", 0))

        price = _get_current_price(code)
        if price is None:
            print(f"[skip] {code} {name}: 価格取得不可")
            continue

        breach: str | None = None
        if stop_loss > 0 and price <= stop_loss:
            breach = "stop_loss"
        elif take_profit > 0 and price >= take_profit:
            breach = "take_profit"
        if not breach:
            # 突破解消なら state クリア
            if hid in state:
                del state[hid]
                state_changed = True
            continue

        # 同じ突破タイプを今日すでに通知済みならスキップ
        prev = state.get(hid, {})
        if prev.get("date") == today and prev.get("type") == breach:
            print(f"[skip] {code} 本日通知済み({breach})")
            continue

        pnl_per_share = price - avg_price
        pnl_total = pnl_per_share * shares
        pnl_pct = pnl_per_share / avg_price * 100 if avg_price else 0

        if breach == "stop_loss":
            emoji, label = "🚨", "損切ライン突破"
            line = f"現在値 {price:,.0f}円 ≤ 損切 {stop_loss:,.0f}円"
        else:
            emoji, label = "🎯", "利確ライン突破"
            line = f"現在値 {price:,.0f}円 ≥ 利確 {take_profit:,.0f}円"

        msg = (
            f"{emoji} {label}\n"
            f"━━━━━━━━━━━━━━\n"
            f"{code} {name}\n"
            f"{line}\n"
            f"\n"
            f"取得 {avg_price:,.0f}円 × {shares}株\n"
            f"損益 {pnl_per_share:+,.0f}円/株 (合計 {pnl_total:+,.0f}円, {pnl_pct:+.2f}%)\n"
            f"\n"
            f"※ 売却したら設定画面の「売却済」を押してください"
        )
        notify_buf.append(msg)
        state[hid] = {"date": today, "type": breach, "price": price}
        state_changed = True
        print(f"[alert] {code} {name} {breach}")

    if notify_buf:
        # 1メッセージにまとめる（複数銘柄でも1通）
        broadcast("\n\n".join(notify_buf))
        print(f"[ok] LINE送信 {len(notify_buf)}件のアラート")
    else:
        print("[info] アラート対象なし")

    if state_changed:
        _save(ALERT_STATE, state)

    return 0


if __name__ == "__main__":
    if not _is_market_hours():
        # cron で毎日呼ばれるため、市場時間外は早期終了
        print(f"[skip] 市場時間外({datetime.now(JST).strftime('%H:%M')})")
        sys.exit(0)
    sys.exit(main())
