"""日経平均・TOPIXの前日終値と予想レンジ（ATRベース）を算出。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import yfinance as yf


@dataclass
class IndexSnapshot:
    symbol: str
    name: str
    prev_close: float
    high_20d: float
    low_20d: float
    atr14: float
    # 予想レンジ = 前日終値 ± ATR14
    range_low: float
    range_high: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "prev_close": round(self.prev_close, 2),
            "high_20d": round(self.high_20d, 2),
            "low_20d": round(self.low_20d, 2),
            "atr14": round(self.atr14, 2),
            "range_low": round(self.range_low, 2),
            "range_high": round(self.range_high, 2),
        }


NAMES: Dict[str, str] = {
    "^N225": "日経平均",
    "1306.T": "TOPIX(ETF)",
    "^TPX": "TOPIX",
}


def _atr(hist, period: int = 14) -> float:
    """Average True Range (簡易)"""
    high = hist["High"]
    low = hist["Low"]
    close_prev = hist["Close"].shift(1)
    tr = (high - low).combine((high - close_prev).abs(), max).combine(
        (low - close_prev).abs(), max
    )
    return float(tr.tail(period).mean())


def snapshot(symbol: str) -> IndexSnapshot | None:
    try:
        hist = yf.Ticker(symbol).history(period="40d", interval="1d", auto_adjust=False)
        # 当日データが未確定(NaN)な場合があるので除外
        hist = hist.dropna(subset=["Close"])
        if hist.empty or len(hist) < 15:
            return None
        prev_close = float(hist["Close"].iloc[-1])
        high_20d = float(hist["High"].tail(20).max())
        low_20d = float(hist["Low"].tail(20).min())
        atr14 = _atr(hist, 14)
        return IndexSnapshot(
            symbol=symbol,
            name=NAMES.get(symbol, symbol),
            prev_close=prev_close,
            high_20d=high_20d,
            low_20d=low_20d,
            atr14=atr14,
            range_low=prev_close - atr14,
            range_high=prev_close + atr14,
        )
    except Exception as e:
        print(f"[warn] {symbol} 取得失敗: {e}")
        return None


def all_indices(symbols) -> list[IndexSnapshot]:
    result = []
    for s in symbols:
        snap = snapshot(s)
        if snap:
            result.append(snap)
    return result


if __name__ == "__main__":
    import json
    for snap in all_indices(["^N225", "^TOPX"]):
        print(json.dumps(snap.to_dict(), ensure_ascii=False))
