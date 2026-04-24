"""日本株関連ニュースを複数RSSから収集する。"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List

import feedparser

JST = timezone(timedelta(hours=9))

# 主要RSSフィード（日本株・マーケット・トランプ/米国関連）
FEEDS = [
    # Yahoo!ニュース 経済
    "https://news.yahoo.co.jp/rss/categories/business.xml",
    # Yahoo!ニュース 国際（トランプ関連など）
    "https://news.yahoo.co.jp/rss/categories/world.xml",
    # 株探 注目株
    "https://s.kabutan.jp/news/marketnews/?category=9&rss=on",
    # ロイター ビジネス
    "https://jp.reuters.com/rssFeed/businessNews",
    # NHK 経済
    "https://www3.nhk.or.jp/rss/news/cat5.xml",
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

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "link": self.link,
            "published": self.published.isoformat() if self.published else None,
            "source": self.source,
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


def fetch_news(hours: int = 18, max_per_feed: int = 15, max_total: int = 25) -> List[NewsItem]:
    """直近`hours`時間以内の日本株関連ニュースを収集。"""
    cutoff = datetime.now(JST) - timedelta(hours=hours)
    collected: List[NewsItem] = []

    for feed_url in FEEDS:
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
                )
            )
            count += 1

    # 新しい順にソートして重複タイトル排除
    seen = set()
    dedup = []
    for item in sorted(collected, key=lambda x: x.published or datetime.min.replace(tzinfo=JST), reverse=True):
        if item.title in seen:
            continue
        seen.add(item.title)
        dedup.append(item)
    return dedup[:max_total]


if __name__ == "__main__":
    import json

    for n in fetch_news():
        print(json.dumps(n.to_dict(), ensure_ascii=False))
