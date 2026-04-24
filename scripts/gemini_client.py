"""Gemini APIクライアント。朝のまとめを生成する。"""
from __future__ import annotations

import json
import os
from typing import List

import requests

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
)


def _build_prompt(
    budget_man: int,
    indices: list,
    news: list,
    max_news_chars: int,
    important_max_chars: int,
    allow_odd_lots: bool,
) -> str:
    idx_txt = "\n".join(
        f"- {s['name']}({s['symbol']}): 前日終値 {s['prev_close']:,.2f} / "
        f"予想レンジ {s['range_low']:,.0f}〜{s['range_high']:,.0f} / "
        f"20日レンジ {s['low_20d']:,.0f}〜{s['high_20d']:,.0f}"
        for s in indices
    )

    news_txt = "\n".join(
        f"- [{n['source']}] {n['title']} {n['link']} | {n['summary'][:200]}"
        for n in news[:20]
    )

    lot_hint = "単元未満株（1株）購入可" if allow_odd_lots else "単元株(100株)購入想定"
    budget_yen = budget_man * 10000

    return f"""あなたは日本株専門のマーケットアナリストです。以下の情報をもとに、
朝の8時にLINE通知で送る短いマーケットブリーフィングを作成してください。

【予算】{budget_man}万円({budget_yen:,}円) / {lot_hint}

【主要指数スナップショット】
{idx_txt}

【直近の関連ニュース】
{news_txt}

以下のフォーマットで出力してください（絵文字・記号は最小限、LINEメッセージ向けに読みやすく）:

━━━━━━━━━━━━━━━━
📈 {{日付}}(曜日) モーニングブリーフ
━━━━━━━━━━━━━━━━
■ 相場サマリー（{max_news_chars}字以内）
（円相場・米株動向・日経平均の想定レンジを含め簡潔に）

■ 前日終値＋予想レンジ
・日経平均: {{値}}円 ／ 予想 {{下}}〜{{上}}
・TOPIX  : {{値}} ／ 予想 {{下}}〜{{上}}

■ 注目ニュース（最大4件・{max_news_chars}字程度。重要なものは最大{important_max_chars}字まで可）
① {{見出し}} / 要約 / リンク
② ...

■ 注目銘柄（予算{budget_man}万円で買える日本株3銘柄）
・{{銘柄コード 銘柄名}}: 株価◯円／推奨理由（1行）
（※ 投資判断はご自身の責任で）

本文のみ出力してください。JSONやコードブロックは不要です。日付は本日(JST)で記入してください。
"""


def summarize(
    budget_man: int,
    indices: list[dict],
    news: list[dict],
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
        indices=indices,
        news=news,
        max_news_chars=max_news_chars,
        important_max_chars=important_max_chars,
        allow_odd_lots=allow_odd_lots,
    )

    resp = requests.post(
        ENDPOINT,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.6,
                "maxOutputTokens": 1600,
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Geminiレスポンス解析失敗: {json.dumps(data)[:500]}")
