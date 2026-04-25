"""日本株・海外市場・為替・商品のスナップショット取得。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import yfinance as yf


@dataclass
class Snapshot:
    symbol: str
    name: str
    category: str  # "jp_index", "us_index", "fx", "commodity", "sector"
    prev_close: float
    change_pct: float
    high_20d: float
    low_20d: float
    atr14: float
    range_low: float
    range_high: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "category": self.category,
            "prev_close": round(self.prev_close, 2),
            "change_pct": round(self.change_pct, 2),
            "high_20d": round(self.high_20d, 2),
            "low_20d": round(self.low_20d, 2),
            "atr14": round(self.atr14, 2),
            "range_low": round(self.range_low, 2),
            "range_high": round(self.range_high, 2),
        }


# カテゴリ別シンボル定義
TARGETS: list[tuple[str, str, str]] = [
    # 日本市場
    ("^N225", "日経平均", "jp_index"),
    ("1306.T", "TOPIX(ETF)", "jp_index"),
    # 米国市場
    ("^DJI", "NYダウ", "us_index"),
    ("^IXIC", "ナスダック", "us_index"),
    ("^GSPC", "S&P500", "us_index"),
    ("^SOX", "フィラデルフィア半導体(SOX)", "us_index"),
    # 為替
    ("JPY=X", "ドル円", "fx"),
    ("EURJPY=X", "ユーロ円", "fx"),
    # 商品
    ("CL=F", "WTI原油", "commodity"),
    ("GC=F", "金", "commodity"),
]


def _atr(hist, period: int = 14) -> float:
    high = hist["High"]
    low = hist["Low"]
    close_prev = hist["Close"].shift(1)
    tr = (high - low).combine((high - close_prev).abs(), max).combine(
        (low - close_prev).abs(), max
    )
    return float(tr.tail(period).mean())


def snapshot(symbol: str, name: str, category: str) -> Snapshot | None:
    try:
        hist = yf.Ticker(symbol).history(period="40d", interval="1d", auto_adjust=False)
        hist = hist.dropna(subset=["Close"])
        if hist.empty or len(hist) < 15:
            return None
        prev_close = float(hist["Close"].iloc[-1])
        prev_prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else prev_close
        change_pct = (prev_close - prev_prev) / prev_prev * 100 if prev_prev else 0.0
        high_20d = float(hist["High"].tail(20).max())
        low_20d = float(hist["Low"].tail(20).min())
        atr14 = _atr(hist, 14)
        return Snapshot(
            symbol=symbol,
            name=name,
            category=category,
            prev_close=prev_close,
            change_pct=change_pct,
            high_20d=high_20d,
            low_20d=low_20d,
            atr14=atr14,
            range_low=prev_close - atr14,
            range_high=prev_close + atr14,
        )
    except Exception as e:
        print(f"[warn] {symbol} 取得失敗: {e}")
        return None


def all_snapshots() -> list[Snapshot]:
    result = []
    for sym, name, cat in TARGETS:
        snap = snapshot(sym, name, cat)
        if snap:
            result.append(snap)
    return result


if __name__ == "__main__":
    import json
    for snap in all_snapshots():
        print(json.dumps(snap.to_dict(), ensure_ascii=False))
