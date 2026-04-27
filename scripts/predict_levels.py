"""主要日本株の損切/利確ラインをGeminiで予測してJSON出力。

UNIVERSE全108銘柄分を1プロンプトでバッチ予測 → docs/predictions.json
holdings.html がこれを読んで取得単価入力時に自動埋め込み。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from stock_universe import UNIVERSE
from gemini_client import MODEL_FALLBACKS, _endpoint

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "predictions.json"


def _atr(hist, period: int = 14) -> float:
    high = hist["High"]
    low = hist["Low"]
    close_prev = hist["Close"].shift(1)
    tr = (high - low).combine((high - close_prev).abs(), max).combine(
        (low - close_prev).abs(), max
    )
    return float(tr.tail(period).mean())


def _fetch_stock_data() -> list[dict]:
    """全UNIVERSE銘柄の前日終値・ATR・20日レンジを取得。"""
    tickers = " ".join(f"{code}.T" for code, _ in UNIVERSE)
    print(f"[info] {len(UNIVERSE)}銘柄バルク取得…")
    df = yf.download(
        tickers, period="40d", interval="1d",
        progress=False, group_by="ticker", auto_adjust=False, threads=True,
    )

    rows: list[dict] = []
    for code, name in UNIVERSE:
        sym = f"{code}.T"
        try:
            sub = df[sym] if sym in df.columns.get_level_values(0) else None
            if sub is None or sub.empty:
                continue
            sub = sub.dropna(subset=["Close"])
            if len(sub) < 15:
                continue
            price = float(sub["Close"].iloc[-1])
            atr = _atr(sub, 14)
            high20 = float(sub["High"].tail(20).max())
            low20 = float(sub["Low"].tail(20).min())
            atr_pct = atr / price * 100 if price else 0
            rows.append({
                "code": code, "name": name,
                "price": round(price, 1),
                "atr": round(atr, 1),
                "atr_pct": round(atr_pct, 2),
                "high20": round(high20, 1),
                "low20": round(low20, 1),
            })
        except Exception as e:
            print(f"[skip] {code}: {e}")
    print(f"[info] データ取得 {len(rows)}件")
    return rows


def _heuristic(row: dict) -> dict:
    """ATRベースの簡易フォールバック。"""
    a = row["atr_pct"]
    return {
        "sl_pct": round(-1.5 * a, 1),
        "tp_pct": round(2.5 * a, 1),
        "rationale": f"ATR({a:.1f}%)ベース",
    }


def _build_prompt(rows: list[dict]) -> str:
    rows_json = json.dumps(
        [{"c": r["code"], "n": r["name"], "p": r["price"],
          "atr_pct": r["atr_pct"], "h20": r["high20"], "l20": r["low20"]} for r in rows],
        ensure_ascii=False,
    )
    return f"""日本株の損切ライン(stop_loss)と利確ライン(take_profit)を予測してください。

【入力データ】(c=コード, n=名称, p=前日終値, atr_pct=14日ATR%, h20=20日高値, l20=20日安値)
{rows_json}

【出力ルール】
- 各銘柄について sl_pct(損切%, マイナス値) と tp_pct(利確%, プラス値) をATR・直近高安・テクニカル観点から提示
- 一般的な目安: SL=-1〜-8%, TP=+3〜+15% の範囲
- ボラ高い銘柄は幅広く、低い銘柄は狭く
- 必ず**全ての銘柄**について返す
- JSONのみ出力（前置き・コードブロック・説明文不要）

【出力フォーマット】
{{
  "7203": {{"sl_pct": -5.0, "tp_pct": 8.5, "r": "短い根拠"}},
  "6758": {{"sl_pct": -6.0, "tp_pct": 10.0, "r": "短い根拠"}},
  ...
}}
"""


def _call_gemini(prompt: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    last_err = None
    for model in dict.fromkeys(MODEL_FALLBACKS):
        try:
            resp = requests.post(
                _endpoint(model),
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 8192,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=120,
            )
            if resp.status_code in (404, 429):
                last_err = f"{model} HTTP {resp.status_code}"
                time.sleep(2); continue
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
            print(f"[ok] {model} で {len(data)}銘柄予測")
            return data
        except Exception as e:
            last_err = f"{model}: {e}"
            continue
    raise RuntimeError(f"全モデル失敗: {last_err}")


def main() -> int:
    rows = _fetch_stock_data()
    if not rows:
        print("[err] データ取得失敗")
        return 1

    predictions: dict[str, dict] = {}
    try:
        ai_result = _call_gemini(_build_prompt(rows))
        for code, name in UNIVERSE:
            r = next((x for x in rows if x["code"] == code), None)
            if r is None:
                continue
            ai = ai_result.get(code)
            if ai and isinstance(ai.get("sl_pct"), (int, float)) and isinstance(ai.get("tp_pct"), (int, float)):
                predictions[code] = {
                    "sl_pct": float(ai["sl_pct"]),
                    "tp_pct": float(ai["tp_pct"]),
                    "rationale": ai.get("r", "")[:80],
                    "source": "ai",
                    "name": name,
                    "price": r["price"],
                }
            else:
                h = _heuristic(r)
                predictions[code] = {**h, "source": "heuristic", "name": name, "price": r["price"]}
    except Exception as e:
        print(f"[warn] Gemini失敗 → ATR heuristic で全銘柄補完: {e}")
        for r in rows:
            h = _heuristic(r)
            predictions[r["code"]] = {**h, "source": "heuristic", "name": r["name"], "price": r["price"]}

    out = {
        "generated_at": datetime.now(JST).isoformat(),
        "predictions": predictions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] {OUT} に {len(predictions)}銘柄保存")
    ai_count = sum(1 for p in predictions.values() if p["source"] == "ai")
    print(f"[stats] AI予測={ai_count}, ヒューリスティック={len(predictions)-ai_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
