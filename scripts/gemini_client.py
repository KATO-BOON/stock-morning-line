"""Gemini APIクライアント。朝のモーニングブリーフィングを生成する。"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List

import requests

JST = timezone(timedelta(hours=9))

# 優先順にモデル名を並べる。最初が429なら次をリトライ。
MODEL_FALLBACKS = [
    os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash",
]


def _endpoint(model: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _fmt_snap(s: dict) -> str:
    sign = "+" if s["change_pct"] >= 0 else ""
    return (
        f"{s['name']}: {s['prev_close']:,.2f} "
        f"({sign}{s['change_pct']:.2f}%) / "
        f"予想レンジ {s['range_low']:,.0f}〜{s['range_high']:,.0f}"
    )


def _build_prompt(
    budget_man: int,
    snapshots: list[dict],
    news: list[dict],
    candidates: list[dict],
    holdings_briefs: list[dict],
    max_news_chars: int,
    important_max_chars: int,
    allow_odd_lots: bool,
) -> str:
    today = datetime.now(JST)
    date_str = today.strftime("%Y-%m-%d(%a)")
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]

    by_cat: dict[str, list] = {}
    for s in snapshots:
        by_cat.setdefault(s["category"], []).append(s)

    jp = "\n".join(_fmt_snap(s) for s in by_cat.get("jp_index", []))
    us = "\n".join(_fmt_snap(s) for s in by_cat.get("us_index", []))
    fx = "\n".join(_fmt_snap(s) for s in by_cat.get("fx", []))
    comm = "\n".join(_fmt_snap(s) for s in by_cat.get("commodity", []))

    def _rel_mark(r: str) -> str:
        return {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(r, "")

    news_txt = "\n".join(
        f"- {_rel_mark(n.get('reliability','medium'))}[{n['source']}] {n['title']}\n  要約: {n['summary'][:180]}\n  URL: {n['link']}"
        for n in news[:25]
    )

    # 保有銘柄ブロック
    if holdings_briefs:
        h_lines = []
        for b in holdings_briefs:
            news_lines = "\n      ".join(
                f"・{_rel_mark(n.get('reliability','medium'))}[{n['source']}] {n['title']}"
                for n in b.get("related_news", [])[:3]
            ) or "・関連ニュースなし"
            pct5 = f"{b['pct_5d']:+.2f}%" if b.get("pct_5d") is not None else "?"
            pnl_pct = f"{b['pnl_pct']:+.2f}%" if b.get("pnl_pct") is not None else "?"
            pnl_total = f"{b['pnl_total']:+,.0f}円" if b.get("pnl_total") is not None else "?"
            latest = f"{b['latest_close']:,.0f}円" if b.get("latest_close") else "?"
            er = f"次回決算: {b['next_earnings']}" if b.get("next_earnings") else "次回決算: 不明"
            h_lines.append(
                f"  ▼ {b['code']} {b['name']} ({b['shares']}株 取得{b['avg_price']:,.0f}円)\n"
                f"    最新値: {latest} / 5日変化: {pct5} / 評価損益: {pnl_total}({pnl_pct})\n"
                f"    損切{b['stop_loss']:,.0f}円 / 利確{b['take_profit']:,.0f}円 / {er}\n"
                f"    関連ニュース:\n      {news_lines}"
            )
        holdings_txt = "\n".join(h_lines)
    else:
        holdings_txt = ""

    cand_txt = "\n".join(
        f"  {c['code']} {c['name']}: 前日終値 {c['prev_close']:,}円 / 100株購入 {c['lot_total']:,}円"
        for c in candidates
    ) or "  （候補なし）"

    # ミニ株(単元未満株)は推奨しない方針 - 必ず100株単位
    budget_yen = budget_man * 10000
    max_share_price = budget_yen // 100  # 100株買える上限株価

    return f"""あなたは日本株マーケットの専門アナリストです。
以下のデータから、本日{date_str.replace('Mon','月曜').replace('Tue','火曜').replace('Wed','水曜').replace('Thu','木曜').replace('Fri','金曜').replace('Sat','土曜').replace('Sun','日曜')}の朝のLINEモーニングブリーフィングを作成してください。
読者は個人投資家1名。予算は{budget_man}万円({budget_yen:,}円)、**100株単位で買える銘柄のみ推奨**(ミニ株禁止)。

━━━━━ 入力データ ━━━━━

【日本市場 前日終値】
{jp}

【米国市場 前日終値】
{us}

【為替 前日終値】
{fx}

【商品市況 前日終値】
{comm}

【関連ニュース（直近18時間以内・🟢=高信頼/🟡=中/🟠=低）】
{news_txt}

【**推奨候補銘柄リスト（このリストの中からのみ選ぶこと・絶対に他銘柄を作らない**）】
{cand_txt}

【**ユーザー保有銘柄**（あれば下記の銘柄を必ず取り上げる）】
{holdings_txt or "（保有なし）"}

━━━━━ 出力仕様 ━━━━━

以下のフォーマットで、**LINEメッセージとして読みやすく**出力してください。
絵文字は各セクション冒頭にのみ使用（過剰使用しない）。
記号の罫線は「━━━」を使う。
重要な数字は太字風に（**使わず**、代わりに改行で目立たせる）。

━━━━━━━━━━━━━━━━
📊 {today.strftime('%-m月%-d日')}({weekday_jp}) モーニングブリーフ
━━━━━━━━━━━━━━━━

🌏 海外市場サマリー
（NYダウ・ナスダック・S&P500・SOXの動向、主要材料を200字程度で）

💴 為替・商品
ドル円: XXX円台(前日比+/-X.XX)
原油・金: 簡潔に

📈 日経平均 本日の展望
前日終値: XX,XXX円(+/-X.XX%)
予想レンジ: XX,XXX〜XX,XXX円
想定シナリオ: （寄付動向の予想、上振れ/下振れ要因を120字程度）

📰 重要ニュース3〜4件
信頼度高い(🟢)を優先。低信頼(🟠)は重要な独自情報のみ採用。
① 【見出し】 [🟢/🟡/🟠]
   簡潔な要約(150〜{max_news_chars}字、重要なものは最大{important_max_chars}字)
   日本株への影響: (1行)
   URL: [記事リンク]

② ...

📌 保有銘柄ウォッチ（保有がある場合のみ。保有なしならこのセクションは丸ごと省略）
各銘柄について以下を必ず含める:
- 評価損益と直近5日トレンド
- 価格動向の解釈（モメンタム・調整・横ばい等）
- 関連ニュースから読み取れる材料・リスク（あれば）
- 次回決算前後の注意点（決算日が近い場合）
- 損切/利確ラインへの距離感（◯%手前など）
- 短期見通し（1〜2文。ホールド/警戒/利確検討等の具体的なアクション示唆）

🎯 本日の注目銘柄（予算{budget_man}万円={budget_yen:,}円・**100株単位**）

【絶対厳守】
- **上記「推奨候補銘柄リスト」に載っている銘柄からのみ選ぶ**
- リストにない銘柄コード・銘柄名を**絶対に作らない**（実在しない銘柄を作るのは重大な誤り）
- ミニ株(単元未満株)は推奨禁止
- 株価×100株が予算以内であることを必ず確認
- 「絶対買い」は存在しない前提。根拠・リスクを明示

ニュース・テーマに合致する候補を3〜5銘柄、リストから選ぶ。

① 銘柄コード 銘柄名
   前日終値: XXX円
   100株購入額: XX,XXX円（予算{budget_man}万円の○○%）
   選定理由: (2〜3行。具体的な材料、直近決算、テーマ関連を明記)
   想定: 損切▲X%（XXX円）/ 利確+X%（XXX円）
   注意点: 1行（決算リスク・需給・地合い等）

② ...

**条件に合う銘柄が思い浮かばない場合は無理に挙げず、3銘柄でも可。**

⚠️ 本日のリスク要因
- 箇条書き2〜3個（FOMC、決算、地政学、為替急変など）

💡 朝の一言
1文。本日のマーケットへの向き合い方アドバイス。

━━━━━━━━━━━━━━━━
※ 情報提供のみ、投資判断はご自身で。

本文のみ出力。JSON・コードブロック・前置き不要。
"""


def summarize(
    budget_man: int,
    snapshots: list[dict],
    news: list[dict],
    candidates: list[dict] | None = None,
    holdings_briefs: list[dict] | None = None,
    max_news_chars: int = 220,
    important_max_chars: int = 400,
    allow_odd_lots: bool = True,
    api_key: str | None = None,
) -> str:
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が未設定です")

    prompt = _build_prompt(
        budget_man=budget_man,
        snapshots=snapshots,
        news=news,
        candidates=candidates or [],
        holdings_briefs=holdings_briefs or [],
        max_news_chars=max_news_chars,
        important_max_chars=important_max_chars,
        allow_odd_lots=allow_odd_lots,
    )

    last_err = None
    tried = []
    for model in dict.fromkeys(MODEL_FALLBACKS):
        tried.append(model)
        try:
            resp = requests.post(
                _endpoint(model),
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 8192,
                    },
                },
                timeout=90,
            )
            if resp.status_code == 429:
                print(f"[warn] {model} 429 -> next model")
                time.sleep(2)
                last_err = f"{model} 429"
                continue
            if resp.status_code == 404:
                print(f"[warn] {model} 404 -> next model")
                last_err = f"{model} 404"
                continue
            resp.raise_for_status()
            data = resp.json()
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                print(f"[ok] モデル {model} 応答成功")
                return text
            except (KeyError, IndexError):
                last_err = f"解析失敗 {model}: {json.dumps(data)[:300]}"
                continue
        except requests.HTTPError as e:
            last_err = f"{model} HTTP {e.response.status_code}: {e.response.text[:200]}"
            continue
        except Exception as e:
            last_err = f"{model} exception: {e}"
            continue
    raise RuntimeError(f"全モデル失敗 (試行={tried}) 最後のエラー: {last_err}")
