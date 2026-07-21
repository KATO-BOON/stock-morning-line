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
    as_of = f" [終値日:{s['as_of']}]" if s.get("as_of") else ""
    return (
        f"{s['name']}: {s['prev_close']:,.2f} "
        f"({sign}{s['change_pct']:.2f}%){as_of} / "
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
    track_text: str = "",
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
        f"  {c['code']} {c['name']}: {c['prev_close']:,}円(100株{c['lot_total']:,}円) "
        f"[{c.get('trend','?')}] 20日{c.get('mom_20d',0):+.1f}% "
        f"市場対比{c.get('rel_str',0):+.1f}pt RSI{c.get('rsi14',50):.0f} "
        f"出来高比{c.get('vol_ratio',1):.2f} 25日線{c.get('ma25','?'):,}"
        for c in candidates
    ) or "  （候補なし）"

    # ミニ株(単元未満株)は推奨しない方針 - 必ず100株単位
    budget_yen = budget_man * 10000
    max_share_price = budget_yen // 100  # 100株買える上限株価

    return f"""あなたは日本株のアナリスト。本日{date_str.replace('Mon','月曜').replace('Tue','火曜').replace('Wed','水曜').replace('Thu','木曜').replace('Fri','金曜').replace('Sat','土曜').replace('Sun','日曜')}の朝のLINEブリーフを作る。
読者は個人投資家1名。予算{budget_man}万円({budget_yen:,}円)・100株単位のみ。

【日本市場】
{jp}

【米国市場】
{us}

【為替】
{fx}

【商品】
{comm}

【関連ニュース（鮮度順=新しい順。🟢高/🟡中/🟠低の信頼度付き）】
※リストは新しい順。**夜間の値動き材料（米株安・半導体急落・為替急変など）を最優先**で取り上げる。
{news_txt}

【推奨候補銘柄リスト（**絶対にこの中からのみ選ぶ**・テクニカル分析済み）】
※指標の意味（過去500日・8,400回の検証に基づく）:
  ・[強い上昇/上昇/横ばい/弱い下降] = トレンド分類。
    検証では20営業日後に「強い上昇」が市場平均を+0.74%上回り、「下降」は-0.88%下回った。
    ただし5営業日では差がほぼ無い（±0.2%程度）＝短期の当てものには向かない。
  ・市場対比 = 日経より何ポイント強いか（資金が向いている度合いの目安）
  ・RSI = 検証では高RSIほど成績が良い傾向。70超でも過度に警戒しないでよい（85超だけ反動注意）
  ・出来高比 = 参考程度（検証では成績との関係はほぼ無かった）
{cand_txt}

【ユーザー保有銘柄（あれば言及）】
{holdings_txt or "（保有なし）"}

━━━━━ 出力ルール（厳守）━━━━━
・LINEで読むので**スマホで見やすく**。長文禁止、箇条書き中心。
・各項目は「・」で始め、1行は短く。ダラダラした文章にしない。
・セクション間は必ず空行を1つ入れる。
・数字は実際の値を入れる（◯のまま残さない）。
・全体1200字以内。
・下のテンプレの【】や（指示文）は出力に含めない。指示に従い中身だけ書く。

📊 {today.strftime('%-m月%-d日')}({weekday_jp}) 朝の株ブリーフ

🌏 海外市場
・NYダウ ◯◯,◯◯◯（前日比±◯%）
・ナスダック ◯◯,◯◯◯（±◯%）
・SOX半導体 ±◯%／一言で材料
・全体ムード: リスクオン or リスクオフ を一言

💴 為替
・ドル円 ◯◯◯円台（円安/円高どちら寄りか一言）

📈 日経平均 きょうの見立て
・前日終値 ◯◯,◯◯◯円（±◯%）※データの[終値日]をそのまま使う。古い日付なら使わない
・予想レンジ ◯◯,◯◯◯〜◯◯,◯◯◯円
・地合い: 上昇基調/横ばい/下落基調 のどれか＋理由を1行

📰 注目ニュース（最大3件・🟢🟡優先）
①［🟢］見出し
　→ 株への影響を1行
　→ {{記事URL}}

②／③も同じ形で

📌 保有銘柄（保有なしなら「📌」ごと省略）
・銘柄名: 評価損益±◯円(±◯%)／損切まで◯%・利確まで◯%
・ひとこと: ホールド/警戒/利確検討 のどれか＋理由1行

🎯 きょうの注目（予算{budget_man}万・100株）
選定の優先順位（厳守）:
　1. [強い上昇] を最優先。次に[上昇]。横ばいは1つまで。下降は選ばない
　2. 20日モメンタムと市場対比が強い銘柄を重視
　3. RSIが85超の銘柄のみ「反動注意」と明記（70台は過度に警戒しない）
　4. **想定保有期間は3〜4週間**（検証上、数日では差が出ない）。短期売買前提の書き方はしない
候補リスト外の銘柄は絶対に作らない。2〜3銘柄でよい。
① コード 銘柄名（トレンド: 強い上昇 等）
　・株価◯円 → 100株 ◯◯,◯◯◯円
　・市場対比+◯pt・RSI◯ ← 数値を必ず入れる
　・選ぶ理由を1行（なぜ他より強いかを具体的に）
　・損切 ◯円(▲◯%)／利確 ◯円(+◯%)

②／③も同じ形で

{("📉 これまでの推奨実績\n・" + track_text) if track_text else ""}

⚠️ きょうの注意
・最大2件（決算/FOMC/地政学/為替急変など）

💡 ひとこと
・1行だけ

━━━━━━━━━━
※ あくまで情報提供。売買はご自身の判断で。

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
    track_text: str = "",
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
        track_text=track_text,
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
