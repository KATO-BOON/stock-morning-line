"""スクリーニングロジックの検証（バックテスト）。

過去データで「その時点だけの情報」からスコアを計算し、
その後の実リターンと関係があるかを検証する。
先読み(lookahead)を避けるため、判定日iまでの終値のみを使い、
エントリーは翌日始値、リターンは i+1+h の終値で測る。

使い方: py scripts/backtest.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from stock_universe import UNIVERSE, _classify_trend, _rsi

HORIZONS = (5, 20)
STEP = 5          # 何営業日ごとに判定するか
LOOKBACK_DAYS = 500  # 取得期間


def _pct(a: float, b: float) -> float:
    return (a - b) / b * 100 if b else 0.0


def main() -> int:
    tickers = " ".join(f"{c}.T" for c, _ in UNIVERSE)
    print(f"[info] {len(UNIVERSE)}銘柄 × {LOOKBACK_DAYS}日 を取得中…")
    df = yf.download(tickers, period=f"{LOOKBACK_DAYS}d", interval="1d",
                     progress=False, group_by="ticker",
                     auto_adjust=False, threads=True)

    # 市場基準(日経ETF)の系列
    mkt = yf.Ticker("1321.T").history(period=f"{LOOKBACK_DAYS}d",
                                      interval="1d", auto_adjust=False)["Close"].dropna()

    # 観測をすべて貯めて、後で「同じ日の全銘柄平均」を引いた超過リターンで評価する。
    # （相場全体の上昇/下落を除去して、純粋な"選別力"を見るため）
    obs: list[dict] = []
    n_obs = 0

    for code, name in UNIVERSE:
        sym = f"{code}.T"
        try:
            sub = df[sym] if sym in df.columns.get_level_values(0) else None
            if sub is None or sub.empty:
                continue
            sub = sub.dropna(subset=["Close"])
            closes = sub["Close"]
            opens = sub["Open"]
            vols = sub["Volume"] if "Volume" in sub else None
            if len(closes) < 120:
                continue

            # 判定可能な範囲: MA75に75本必要、先に最大20営業日の先行きが必要
            start_i = 80
            end_i = len(closes) - max(HORIZONS) - 2
            for i in range(start_i, end_i, STEP):
                window = closes.iloc[: i + 1]          # i時点まで（先読みなし）
                price = float(window.iloc[-1])
                ma25 = float(window.tail(25).mean())
                ma75 = float(window.tail(75).mean())
                p5 = float(window.iloc[-6])
                p20 = float(window.iloc[-21])
                mom_5d = _pct(price, p5)
                mom_20d = _pct(price, p20)
                rsi14 = _rsi(window, 14)

                # 市場対比（同じ日付で日経の20日騰落率）
                d = window.index[-1]
                rel = 0.0
                try:
                    mpos = mkt.index.get_indexer([d], method="ffill")[0]
                    if mpos >= 20:
                        m_now = float(mkt.iloc[mpos])
                        m_prev = float(mkt.iloc[mpos - 20])
                        rel = mom_20d - _pct(m_now, m_prev)
                except Exception:
                    pass

                vol_ratio = 1.0
                if vols is not None:
                    try:
                        vw = vols.iloc[: i + 1].dropna()
                        if len(vw) >= 25:
                            vol_ratio = float(vw.tail(5).mean()) / float(vw.tail(25).mean())
                    except Exception:
                        pass

                trend, score = _classify_trend(price, ma25, ma75, mom_5d, mom_20d,
                                               rsi14, rel, vol_ratio)

                # エントリー = 翌日始値
                try:
                    entry = float(opens.iloc[i + 1])
                except Exception:
                    continue
                if not entry:
                    continue

                rec = {
                    "date": str(d.date()), "code": code, "trend": trend, "score": score,
                    "mom_20d": mom_20d, "rel_str": rel, "rsi14": rsi14,
                    "vol_ratio": vol_ratio,
                }
                ok = False
                for h in HORIZONS:
                    j = i + 1 + h
                    if j < len(closes):
                        rec[f"ret_{h}"] = _pct(float(closes.iloc[j]), entry)
                        ok = True
                if ok:
                    obs.append(rec)
                    n_obs += 1
        except Exception as e:
            print(f"[warn] {code}: {e}")
            continue

    # 同じ日の全銘柄平均を引いて「超過リターン」にする（市場要因を除去）
    for h in HORIZONS:
        key = f"ret_{h}"
        day_sum: dict[str, list[float]] = defaultdict(list)
        for o in obs:
            if key in o:
                day_sum[o["date"]].append(o[key])
        day_avg = {d: sum(v) / len(v) for d, v in day_sum.items()}
        for o in obs:
            if key in o:
                o[f"ex_{h}"] = o[key] - day_avg[o["date"]]

    def stats(vals: list[float]) -> str:
        if not vals:
            return "データなし"
        wins = sum(1 for v in vals if v > 0)
        avg = sum(vals) / len(vals)
        return f"n={len(vals):>5}  勝率{wins/len(vals)*100:5.1f}%  平均{avg:+6.2f}%"

    print(f"\n[info] 判定回数 {n_obs:,}")

    print("\n===== ① 生リターン（相場全体の動きを含む）=====")
    for h in HORIZONS:
        print(f"--- {h}営業日後 ---")
        for t in ["強い上昇", "上昇", "横ばい", "弱い下降", "下降"]:
            vals = [o[f"ret_{h}"] for o in obs if o["trend"] == t and f"ret_{h}" in o]
            print(f"  {t:<5} {stats(vals)}")

    print("\n===== ② 超過リターン（同日の全銘柄平均を引いた＝純粋な選別力）=====")
    print("  ※ 平均が+なら『市場平均より良い銘柄を選べている』, 0前後なら選別力なし")
    for h in HORIZONS:
        print(f"--- {h}営業日後 ---")
        for t in ["強い上昇", "上昇", "横ばい", "弱い下降", "下降"]:
            vals = [o[f"ex_{h}"] for o in obs if o["trend"] == t and f"ex_{h}" in o]
            print(f"  {t:<5} {stats(vals)}")

    print("\n===== ③ スコア帯別の超過リターン =====")
    def bucket_of(s: float) -> str:
        return ("A:score>=6" if s >= 6 else "B:4-6" if s >= 4 else
                "C:2-4" if s >= 2 else "D:0-2" if s >= 0 else "E:<0")
    for h in HORIZONS:
        print(f"--- {h}営業日後 ---")
        for b in ["A:score>=6", "B:4-6", "C:2-4", "D:0-2", "E:<0"]:
            vals = [o[f"ex_{h}"] for o in obs
                    if bucket_of(o["score"]) == b and f"ex_{h}" in o]
            print(f"  {b:<12} {stats(vals)}")

    print("\n===== ④ 各シグナルと超過リターンの相関 =====")
    def corr(pairs: list[tuple[float, float]]) -> float:
        if len(pairs) < 30:
            return 0.0
        xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
        mx = sum(xs)/len(xs); my = sum(ys)/len(ys)
        num = sum((x-mx)*(y-my) for x, y in pairs)
        dx = sum((x-mx)**2 for x in xs) ** 0.5
        dy = sum((y-my)**2 for y in ys) ** 0.5
        return num/(dx*dy) if dx and dy else 0.0
    for h in HORIZONS:
        print(f"--- {h}営業日後の超過リターンとの相関 ---")
        for k in ["score", "mom_20d", "rel_str", "rsi14", "vol_ratio"]:
            pairs = [(o[k], o[f"ex_{h}"]) for o in obs if f"ex_{h}" in o]
            print(f"  {k:<10} 相関 {corr(pairs):+.3f}  (n={len(pairs)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
