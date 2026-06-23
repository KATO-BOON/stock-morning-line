"""日本株関連ニュースを複数RSSから収集する。"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List

import feedparser

JST = timezone(timedelta(hours=9))

# 主要RSSフィード（信頼度別: high/medium/low）
# 「high」を優先的に拾う設計
FEEDS: list[tuple[str, str]] = [
    # 信頼度: high（一次・伝統メディア）
    ("https://www3.nhk.or.jp/rss/news/cat5.xml", "high"),                     # NHK経済
    ("https://jp.reuters.com/rssFeed/businessNews", "high"),                  # ロイター
    ("https://feeds.bloomberg.co.jp/rss/japan-markets-news.xml", "high"),     # Bloomberg JP
    ("https://toyokeizai.net/list/feed/rss", "high"),                         # 東洋経済
    ("https://diamond.jp/list/feed/all_rss", "high"),                         # ダイヤモンド
    # 信頼度: medium（金融特化・株専門）
    ("https://s.kabutan.jp/news/marketnews/?category=9&rss=on", "medium"),    # 株探
    ("https://minkabu.jp/news/news.rss", "medium"),                           # みんかぶ
    # 信頼度: low（一般アグリゲーター・タブロイドが混じる）
    ("https://news.yahoo.co.jp/rss/categories/business.xml", "low"),          # Yahoo!経済
    ("https://news.yahoo.co.jp/rss/categories/world.xml", "low"),             # Yahoo!国際
]

# 関連度キーワードを2段階に分離して精度を上げる。
# STRONG: 含めば確実に市場ニュース（単独で採用）
STRONG_KEYS = [
    "日経平均", "日経", "TOPIX", "東証", "株価", "株式市場", "上場", "株主",
    "日銀", "金利", "利上げ", "利下げ", "為替", "円安", "円高", "ドル円", "円相場",
    "FOMC", "FRB", "ECB", "米国株", "NYダウ", "ナスダック", "S&P500", "S&P",
    "決算", "四半期", "業績", "増配", "減配", "自社株買い", "上方修正", "下方修正",
    "M&A", "TOB", "新高値", "ストップ高", "ストップ安", "出来高", "売買代金",
    "原油", "WTI", "金先物", "半導体株", "国債", "長期金利", "日経先物", "先物",
]
# SOFT: 市場文脈(STRONG)と同時に出た時だけ採用（単独では雑音になりやすい）
SOFT_KEYS = [
    "トランプ", "関税", "AI", "半導体", "自動車", "EV", "インフレ", "景気",
    "GDP", "雇用統計", "中国", "地政学", "原発", "防衛", "賃上げ",
]


@dataclass
class NewsItem:
    title: str
    summary: str
    link: str
    published: datetime | None
    source: str
    reliability: str = "medium"  # high/medium/low

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "link": self.link,
            "published": self.published.isoformat() if self.published else None,
            "source": self.source,
            "reliability": self.reliability,
        }


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _is_relevant(title: str, summary: str) -> bool:
    """強い市場用語が1つでもあれば採用。弱い用語のみなら2つ以上で採用。
    （「W杯でトランプ」のような単独ソフト一致＝雑音を除外）"""
    blob = f"{title} {summary}"
    if any(k in blob for k in STRONG_KEYS):
        return True
    soft_hits = sum(1 for k in SOFT_KEYS if k in blob)
    return soft_hits >= 2


def _parse_published(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        tm = getattr(entry, field, None)
        if tm:
            return datetime(*tm[:6], tzinfo=timezone.utc).astimezone(JST)
    return None


# 信頼度ペナルティ(時間換算)。鮮度を主軸に、低信頼ソースは相応に後ろへ。
_REL_PENALTY_H = {"high": 0.0, "medium": 5.0, "low": 12.0}


def _rank_key(item: NewsItem) -> float:
    """小さいほど上位。実年齢(時間) + 信頼度ペナルティ。
    鮮度を最優先しつつ、低信頼ソースが古い高信頼記事を押しのけないよう調整。"""
    if item.published:
        age_h = (datetime.now(JST) - item.published).total_seconds() / 3600
    else:
        age_h = 24.0  # 日付不明は1日前相当として後ろへ
    return age_h + _REL_PENALTY_H.get(item.reliability, 9.0)


def fetch_news(hours: int = 20, max_per_feed: int = 15, max_total: int = 25) -> List[NewsItem]:
    """直近`hours`時間以内の日本株関連ニュースを収集。鮮度優先で並べる。"""
    cutoff = datetime.now(JST) - timedelta(hours=hours)
    collected: List[NewsItem] = []

    for feed_url, reliability in FEEDS:
        try:
            fp = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[warn] RSS取得失敗 {feed_url}: {e}")
            continue

        source = fp.feed.get("title", feed_url)
        count = 0
        for entry in fp.entries:
            if count >= max_per_feed:
                break
            title = _clean_html(entry.get("title", ""))
            summary = _clean_html(entry.get("summary", entry.get("description", "")))
            link = entry.get("link", "")
            published = _parse_published(entry)

            if published and published < cutoff:
                continue
            if not _is_relevant(title, summary):
                continue

            collected.append(
                NewsItem(
                    title=title,
                    summary=summary[:500],
                    link=link,
                    published=published,
                    source=source,
                    reliability=reliability,
                )
            )
            count += 1

    # 重複タイトル排除 → 鮮度優先スコアで昇順
    seen = set()
    dedup: list[NewsItem] = []
    for item in sorted(collected, key=_rank_key):
        if item.title in seen:
            continue
        seen.add(item.title)
        dedup.append(item)
    return dedup[:max_total]


def filter_by_keywords(items: list[NewsItem], keywords: list[str]) -> list[NewsItem]:
    """銘柄名・コード等のキーワードを含むニュースのみ抽出。"""
    matched = []
    for it in items:
        blob = f"{it.title} {it.summary}"
        if any(k in blob for k in keywords):
            matched.append(it)
    return matched


if __name__ == "__main__":
    import json

    for n in fetch_news():
        print(json.dumps(n.to_dict(), ensure_ascii=False))
