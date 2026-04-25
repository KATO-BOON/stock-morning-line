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

# 日本株・マーケットに関連しそうなキーワード
REL_KEYS = [
    "日経", "株価", "株式", "東証", "TOPIX", "日銀", "金利", "円安", "円高",
    "為替", "ドル円", "FOMC", "FRB", "トランプ", "関税", "決算", "四半期",
    "米国株", "NYダウ", "ナスダック", "S&P", "半導体", "AI", "自動車",
    "原油", "金先物", "インフレ", "景気", "GDP", "雇用", "増配", "自社株買い",
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
    blob = f"{title} {summary}"
    return any(k in blob for k in REL_KEYS)


def _parse_published(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        tm = getattr(entry, field, None)
        if tm:
            return datetime(*tm[:6], tzinfo=timezone.utc).astimezone(JST)
    return None


_REL_RANK = {"high": 0, "medium": 1, "low": 2}


def fetch_news(hours: int = 18, max_per_feed: int = 15, max_total: int = 25) -> List[NewsItem]:
    """直近`hours`時間以内の日本株関連ニュースを収集。信頼度高い順に優先。"""
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

    # 重複タイトル排除→信頼度→新しい順
    seen = set()
    dedup: list[NewsItem] = []
    for item in sorted(
        collected,
        key=lambda x: (
            _REL_RANK.get(x.reliability, 9),
            -(x.published.timestamp() if x.published else 0),
        ),
    ):
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
