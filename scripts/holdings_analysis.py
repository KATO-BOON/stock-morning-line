"""保有銘柄の動向分析（Geminiに渡す材料を構築）。
- 直近5日の値動き
- 評価損益
- 関連ニュース抽出
- 決算予定（取得できれば）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yfinance as yf

from news_fetch import NewsItem, filter_by_keywords


@dataclass
class HoldingBrief:
    code: str
    name: str
    shares: int
    avg_price: float
    stop_loss: float
    take_profit: float
    latest_close: float | None = None
    pct_5d: float | None = None
    pnl_pct: float | None = None
    pnl_total: float | None = None
    next_earnings: str | None = None
    related_news: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "shares": self.shares,
            "avg_price": self.avg_price, "stop_loss": self.stop_loss,
            "take_profit": self.take_profit, "latest_close": self.latest_close,
            "pct_5d": self.pct_5d, "pnl_pct": self.pnl_pct, "pnl_total": self.pnl_total,
            "next_earnings": self.next_earnings, "related_news": self.related_news,
        }


def _earnings_date(t: yf.Ticker) -> str | None:
    try:
        cal = t.calendar
        if cal is None:
            return None
        # yfinance returns dict-like for new versions
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                return str(ed[0]) if isinstance(ed, list) else str(ed)
        # 旧版DataFrame
        try:
            ed = cal.loc["Earnings Date"][0]
            return str(ed.date())
        except Exception:
            pass
    except Exception:
        pass
    return None


def analyze_holdings(holdings: list[dict], news: list[NewsItem]) -> list[HoldingBrief]:
    briefs: list[HoldingBrief] = []
    for h in holdings:
        code = str(h["code"])
        name = h.get("name", code)
        brief = HoldingBrief(
            code=code, name=name,
            shares=int(h["shares"]), avg_price=float(h["avg_price"]),
            stop_loss=float(h.get("stop_loss", 0)),
            take_profit=float(h.get("take_profit", 0)),
        )
        # 価格動向
        try:
            t = yf.Ticker(f"{code}.T")
            hist = t.history(period="10d", interval="1d", auto_adjust=False)
            hist = hist.dropna(subset=["Close"])
            if not hist.empty:
                latest = float(hist["Close"].iloc[-1])
                brief.latest_close = latest
                if len(hist) >= 5:
                    five_ago = float(hist["Close"].iloc[-5])
                    brief.pct_5d = (latest - five_ago) / five_ago * 100
                pnl_per_share = latest - brief.avg_price
                brief.pnl_total = pnl_per_share * brief.shares
                brief.pnl_pct = pnl_per_share / brief.avg_price * 100 if brief.avg_price else 0
            brief.next_earnings = _earnings_date(t)
        except Exception as e:
            print(f"[warn] {code} 価格取得失敗: {e}")

        # 関連ニュース（コードか銘柄名にマッチ）
        keywords = [code, name]
        # 銘柄名から接尾辞を除いた短縮形も追加（例: 「日産自動車」→「日産」）
        if len(name) > 2:
            keywords.append(name[:2])
            keywords.append(name[:3])
        matched = filter_by_keywords(news, list(set(keywords)))
        brief.related_news = [
            {"title": n.title, "source": n.source, "link": n.link, "reliability": n.reliability}
            for n in matched[:5]
        ]
        briefs.append(brief)
    return briefs
