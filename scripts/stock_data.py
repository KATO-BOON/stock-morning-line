"""日本株・海外市場・為替・商品のスナップショット取得。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict

import yfinance as yf

# 予想レンジの幅 = 前日終値 ± (ATR14 × RANGE_MULT)
# ±1ATRは広すぎるため0.7に。環境変数RANGE_ATR_MULTで上書き可。
RANGE_MULT = float(os.environ.get("RANGE_ATR_MULT", "0.7"))


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
    as_of: str  # 終値の日付 YYYY-MM-DD（鮮度確認用）

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
            "as_of": self.as_of,
        }


# カテゴリ別シンボル定義
# 注: 日経平均は専用ロジック(_nikkei_snapshot)で取得するためTARGETSには入れない。
#     ^N225は1日遅延、ETF(1321.T)は指数の約1.047倍で取引されるため、
#     両方使って「鮮度=ETF, 水準=指数」に変換する。
TARGETS: list[tuple[str, str, str]] = [
    # 日本市場（日経は別処理。TOPIXはETF値そのまま=変化率は同じ）
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
        as_of = hist.index[-1].strftime("%Y-%m-%d")
        return Snapshot(
            symbol=symbol,
            name=name,
            category=category,
            prev_close=prev_close,
            change_pct=change_pct,
            high_20d=high_20d,
            low_20d=low_20d,
            atr14=atr14,
            range_low=prev_close - atr14 * RANGE_MULT,
            range_high=prev_close + atr14 * RANGE_MULT,
            as_of=as_of,
        )
    except Exception as e:
        print(f"[warn] {symbol} 取得失敗: {e}")
        return None


def _nikkei_snapshot() -> Snapshot | None:
    """日経平均を「鮮度=ETF / 水準=指数」で取得。

    ^N225は1日遅延、1321.T(ETF)は指数の約1.047倍で取引される。
    直近の共通日で 指数/ETF 比率を求め、最新ETF値に掛けて指数水準を推定する。
    ^N225が最新まで揃っていればそのまま使う。
    """
    try:
        idx = yf.Ticker("^N225").history(period="40d", interval="1d", auto_adjust=False)
        etf = yf.Ticker("1321.T").history(period="40d", interval="1d", auto_adjust=False)
        idx_c = idx["Close"].dropna()
        etf_c = etf["Close"].dropna()
        if etf_c.empty or len(etf_c) < 15:
            # ETFが取れなければ指数だけで通常処理にフォールバック
            return snapshot("^N225", "日経平均", "jp_index")

        # 直近の共通日で比率(指数/ETF)を算出（直近5共通日の中央値で安定化）
        common = idx_c.index.intersection(etf_c.index)
        if len(common) >= 3:
            import statistics
            ratios = [float(idx_c[d]) / float(etf_c[d]) for d in common[-5:] if etf_c[d]]
            ratio = statistics.median(ratios) if ratios else 1.0
        else:
            ratio = 0.955  # 経験値フォールバック

        # ^N225が最新まで揃っているならそのまま（最も正確）
        if not idx_c.empty and idx_c.index[-1] >= etf_c.index[-1]:
            return snapshot("^N225", "日経平均", "jp_index")

        # ETF系列を指数水準に変換して通常計算（鮮度はETF基準）
        synth = etf_c * ratio
        prev_close = float(synth.iloc[-1])
        prev_prev = float(synth.iloc[-2]) if len(synth) >= 2 else prev_close
        change_pct = (prev_close - prev_prev) / prev_prev * 100 if prev_prev else 0.0
        # ATR/レンジも合成系列(指数水準)で計算
        synth_df = etf.copy()
        for col in ("High", "Low", "Close"):
            if col in synth_df:
                synth_df[col] = synth_df[col] * ratio
        synth_df = synth_df.dropna(subset=["Close"])
        atr14 = _atr(synth_df, 14)
        high_20d = float(synth_df["High"].tail(20).max())
        low_20d = float(synth_df["Low"].tail(20).min())
        as_of = etf_c.index[-1].strftime("%Y-%m-%d")
        print(f"[info] 日経平均: ETF×比率{ratio:.3f}で指数換算 {prev_close:,.0f} (as_of {as_of})")
        return Snapshot(
            symbol="^N225", name="日経平均", category="jp_index",
            prev_close=prev_close, change_pct=change_pct,
            high_20d=high_20d, low_20d=low_20d, atr14=atr14,
            range_low=prev_close - atr14 * RANGE_MULT,
            range_high=prev_close + atr14 * RANGE_MULT,
            as_of=as_of,
        )
    except Exception as e:
        print(f"[warn] 日経平均取得失敗: {e}")
        return snapshot("^N225", "日経平均", "jp_index")


def all_snapshots() -> list[Snapshot]:
    result = []
    nk = _nikkei_snapshot()
    if nk:
        result.append(nk)
    for sym, name, cat in TARGETS:
        snap = snapshot(sym, name, cat)
        if snap:
            result.append(snap)
    return result


if __name__ == "__main__":
    import json
    for snap in all_snapshots():
        print(json.dumps(snap.to_dict(), ensure_ascii=False))
