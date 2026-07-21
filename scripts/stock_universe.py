"""主要日本株100銘柄ユニバースから、予算内で買える銘柄候補を返す。
Gemini に渡してハルシネーション銘柄を防ぐ。
"""
from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf

# 流動性・知名度の高い主要日本株（時価総額・個人投資家人気で選定）
UNIVERSE: list[tuple[str, str]] = [
    # 自動車
    ("7203", "トヨタ自動車"), ("7267", "ホンダ"), ("7269", "スズキ"),
    ("7270", "SUBARU"), ("7272", "ヤマハ発動機"), ("7211", "三菱自動車"),
    ("7202", "いすゞ自動車"), ("7261", "マツダ"), ("6201", "豊田自動織機"),
    ("6902", "デンソー"), ("7259", "アイシン"), ("7276", "小糸製作所"),
    # 電機・半導体
    ("6758", "ソニーG"), ("6501", "日立"), ("6502", "東芝"),
    ("6503", "三菱電機"), ("6752", "パナソニックHD"), ("6701", "NEC"),
    ("6702", "富士通"), ("6723", "ルネサス"), ("6724", "セイコーエプソン"),
    ("6770", "アルプスアルパイン"), ("6857", "アドバンテスト"), ("6861", "キーエンス"),
    ("6920", "レーザーテック"), ("6954", "ファナック"), ("6971", "京セラ"),
    ("6976", "太陽誘電"), ("6981", "村田製作所"), ("8035", "東京エレクトロン"),
    ("4063", "信越化学"),
    # 通信・IT
    ("9432", "NTT"), ("9433", "KDDI"), ("9434", "ソフトバンク"),
    ("9984", "ソフトバンクG"), ("9613", "NTTデータ"), ("4385", "メルカリ"),
    ("4307", "野村総研"), ("6098", "リクルートHD"),
    # 金融
    ("8306", "三菱UFJ"), ("8316", "三井住友FG"), ("8411", "みずほFG"),
    ("8591", "オリックス"), ("8601", "大和証券G"), ("8604", "野村HD"),
    ("8630", "SOMPOHD"), ("8725", "MS&AD"), ("8766", "東京海上HD"),
    ("6178", "日本郵政"),
    # 商社
    ("8001", "伊藤忠"), ("8002", "丸紅"), ("8015", "豊田通商"),
    ("8031", "三井物産"), ("8053", "住友商事"), ("8058", "三菱商事"),
    # 不動産
    ("8801", "三井不動産"), ("8802", "三菱地所"), ("1925", "大和ハウス"),
    ("1928", "積水ハウス"),
    # 製薬・医療
    ("4502", "武田薬品"), ("4503", "アステラス"), ("4519", "中外製薬"),
    ("4523", "エーザイ"), ("4543", "テルモ"), ("4568", "第一三共"),
    # 食品・小売・消費財
    ("2502", "アサヒG"), ("2503", "キリンHD"), ("2914", "JT"),
    ("8267", "イオン"), ("3382", "セブン&アイ"), ("9983", "ファーストリテ"),
    ("8113", "ユニチャーム"), ("4452", "花王"), ("4901", "富士フイルム"),
    ("4911", "資生堂"),
    # 機械・工作
    ("6273", "SMC"), ("6301", "コマツ"), ("6326", "クボタ"),
    ("6367", "ダイキン"), ("7011", "三菱重工"), ("7012", "川崎重工"),
    ("5108", "ブリヂストン"),
    # 化学・素材
    ("4188", "三菱ケミG"), ("3402", "東レ"), ("3407", "旭化成"),
    ("5201", "AGC"), ("5401", "日本製鉄"), ("5411", "JFE"),
    ("5713", "住友金属鉱山"), ("5802", "住友電工"),
    # エンタメ・サービス
    ("7974", "任天堂"), ("7832", "バンダイナムコ"), ("4661", "オリエンタルランド"),
    ("4324", "電通G"),
    # 運輸
    ("9020", "JR東日本"), ("9021", "JR西日本"), ("9022", "JR東海"),
    ("9101", "日本郵船"), ("9104", "商船三井"), ("9202", "ANA"),
    # 公益
    ("9501", "東京電力HD"), ("9502", "中部電力"), ("9503", "関西電力"),
    ("9531", "東京ガス"),
    # 光学・精密
    ("7733", "オリンパス"), ("7741", "HOYA"), ("7751", "キヤノン"),
    ("7752", "リコー"),
]


@dataclass
class Candidate:
    code: str
    name: str
    prev_close: float
    lot_total: float       # 100株時の合計金額
    ma25: float            # 25日移動平均
    ma75: float            # 75日移動平均
    mom_5d: float          # 5日モメンタム(%)
    mom_20d: float         # 20日モメンタム(%)
    rsi14: float           # RSI(14) 過熱・売られ過ぎ判定
    rel_str: float         # 市場対比の強さ(銘柄20日 - 日経20日, %pt)
    vol_ratio: float       # 直近5日平均出来高 / 25日平均出来高
    trend: str             # 強い上昇/上昇/横ばい/弱い下降/下降
    trend_score: float     # 並べ替え用スコア

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "prev_close": round(self.prev_close, 1),
            "lot_total": int(self.lot_total),
            "ma25": round(self.ma25, 1),
            "ma75": round(self.ma75, 1),
            "mom_5d": round(self.mom_5d, 1),
            "mom_20d": round(self.mom_20d, 1),
            "rsi14": round(self.rsi14, 0),
            "rel_str": round(self.rel_str, 1),
            "vol_ratio": round(self.vol_ratio, 2),
            "trend": self.trend,
        }


def _rsi(closes, period: int = 14) -> float:
    """RSI(14)。70超=買われ過ぎ、30未満=売られ過ぎの目安。"""
    diff = closes.diff().dropna()
    if len(diff) < period:
        return 50.0
    recent = diff.tail(period)
    gain = float(recent[recent > 0].sum())
    loss = float(-recent[recent < 0].sum())
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    rs = (gain / period) / (loss / period)
    return 100.0 - (100.0 / (1.0 + rs))


def _classify_trend(price: float, ma25: float, ma75: float,
                    mom_5d: float, mom_20d: float,
                    rsi14: float = 50.0, rel_str: float = 0.0,
                    vol_ratio: float = 1.0) -> tuple[str, float]:
    """移動平均・モメンタム・RSI・市場対比・出来高からトレンドを分類しスコア化。

    スコアが高い=上昇基調。並べ替えと足切りに使う。
    """
    score = 0.0
    # 価格と移動平均の位置関係（パーフェクトオーダー重視）
    if price > ma25:
        score += 1.5
    if price > ma75:
        score += 1.5
    if ma25 > ma75:
        score += 2.0  # ゴールデンクロス状態（中期上昇）
    # モメンタム
    score += mom_20d * 0.15   # 20日の地合い
    score += mom_5d * 0.10    # 直近の勢い
    # 市場対比の強さ（日経より強い＝相対的に資金が向いている）
    score += rel_str * 0.12
    # 出来高増加を伴う動きは信頼度が高い
    if vol_ratio >= 1.5:
        score += 1.0
    elif vol_ratio >= 1.2:
        score += 0.5
    elif vol_ratio < 0.7:
        score -= 0.5   # 閑散＝勢い続きにくい
    # RSIによる過熱／売られ過ぎ調整
    if rsi14 >= 80:
        score -= 2.0   # 極端な過熱＝高値掴みリスク大
    elif rsi14 >= 72:
        score -= 1.0
    elif rsi14 <= 30:
        score -= 0.5   # 下落継続中の可能性
    # 過熱気味（5日で+12%超）は少し減点（高値掴みリスク）
    if mom_5d > 12:
        score -= 1.0

    if score >= 5.0:
        return "強い上昇", score
    if score >= 3.0:
        return "上昇", score
    if score >= 1.0:
        return "横ばい", score
    if score >= -1.0:
        return "弱い下降", score
    return "下降", score


def fetch_candidates(budget_man: int, max_count: int = 50) -> list[Candidate]:
    """予算内で100株購入できる銘柄を返す。"""
    budget_yen = budget_man * 10000
    max_share_price = budget_yen // 100  # 100株買える上限株価

    tickers = " ".join(f"{code}.T" for code, _ in UNIVERSE)
    print(f"[info] {len(UNIVERSE)}銘柄を一括取得中(トレンド分析用90日)…")
    try:
        df = yf.download(
            tickers, period="90d", interval="1d",
            progress=False, group_by="ticker", auto_adjust=False, threads=True,
        )
    except Exception as e:
        print(f"[warn] 一括取得失敗: {e}")
        return []

    # 市場対比の基準（日経ETFの20日騰落率）。個別がこれを上回れば相対的に強い。
    mkt_20d = 0.0
    try:
        mk = yf.Ticker("1321.T").history(period="60d", interval="1d",
                                         auto_adjust=False)["Close"].dropna()
        if len(mk) >= 21:
            mkt_20d = (float(mk.iloc[-1]) - float(mk.iloc[-21])) / float(mk.iloc[-21]) * 100
        print(f"[info] 市場基準(日経20日騰落率): {mkt_20d:+.1f}%")
    except Exception as e:
        print(f"[warn] 市場基準取得失敗(相対強度は0扱い): {e}")

    candidates: list[Candidate] = []
    for code, name in UNIVERSE:
        sym = f"{code}.T"
        try:
            sub = df[sym] if sym in df.columns.get_level_values(0) else None
            if sub is None or sub.empty:
                continue
            closes = sub["Close"].dropna()
            if len(closes) < 25:
                continue
            price = float(closes.iloc[-1])
            if price <= 0 or price > max_share_price:
                continue
            # 移動平均
            ma25 = float(closes.tail(25).mean())
            ma75 = float(closes.tail(75).mean()) if len(closes) >= 75 else float(closes.mean())
            # モメンタム(%)
            p5 = float(closes.iloc[-6]) if len(closes) >= 6 else price
            p20 = float(closes.iloc[-21]) if len(closes) >= 21 else price
            mom_5d = (price - p5) / p5 * 100 if p5 else 0.0
            mom_20d = (price - p20) / p20 * 100 if p20 else 0.0
            # RSI(14)
            rsi14 = _rsi(closes, 14)
            # 市場対比の強さ（銘柄20日 − 日経20日）
            rel_str = mom_20d - mkt_20d
            # 出来高比（直近5日平均 ÷ 25日平均）
            vol_ratio = 1.0
            try:
                vols = sub["Volume"].dropna()
                if len(vols) >= 25:
                    v5 = float(vols.tail(5).mean())
                    v25 = float(vols.tail(25).mean())
                    vol_ratio = v5 / v25 if v25 else 1.0
            except Exception:
                pass
            trend, tscore = _classify_trend(price, ma25, ma75, mom_5d, mom_20d,
                                            rsi14, rel_str, vol_ratio)
            candidates.append(Candidate(
                code=code, name=name,
                prev_close=price,
                lot_total=price * 100,
                ma25=ma25, ma75=ma75,
                mom_5d=mom_5d, mom_20d=mom_20d,
                rsi14=rsi14, rel_str=rel_str, vol_ratio=vol_ratio,
                trend=trend, trend_score=tscore,
            ))
        except Exception as e:
            print(f"[warn] {code} skip: {e}")
            continue

    # 下降トレンドは除外（弱い下降までは残す＝逆張り余地も少し残す）
    uptrend = [c for c in candidates if c.trend != "下降"]
    # 全部下降なら足切りせず全件（地合い悪い日でも候補ゼロを防ぐ）
    pool = uptrend if uptrend else candidates
    # トレンドスコア降順（上昇基調を優先）
    pool.sort(key=lambda c: c.trend_score, reverse=True)
    result = pool[:max_count]

    n_strong = sum(1 for c in result if c.trend == "強い上昇")
    n_up = sum(1 for c in result if c.trend == "上昇")
    print(f"[info] 予算{budget_man}万円(株価{max_share_price:,}円以下) "
          f"候補{len(result)}件 (強い上昇{n_strong}/上昇{n_up}, 下降除外{len(candidates)-len(uptrend)})")
    return result


if __name__ == "__main__":
    import json
    for c in fetch_candidates(20):
        print(json.dumps(c.to_dict(), ensure_ascii=False))
