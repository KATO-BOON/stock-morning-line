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
    lot_total: float  # 100株時の合計金額

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "prev_close": round(self.prev_close, 1),
            "lot_total": int(self.lot_total),
        }


def fetch_candidates(budget_man: int, max_count: int = 50) -> list[Candidate]:
    """予算内で100株購入できる銘柄を返す。"""
    budget_yen = budget_man * 10000
    max_share_price = budget_yen // 100  # 100株買える上限株価

    tickers = " ".join(f"{code}.T" for code, _ in UNIVERSE)
    print(f"[info] {len(UNIVERSE)}銘柄を一括取得中…")
    try:
        df = yf.download(
            tickers, period="5d", interval="1d",
            progress=False, group_by="ticker", auto_adjust=False, threads=True,
        )
    except Exception as e:
        print(f"[warn] 一括取得失敗: {e}")
        return []

    candidates: list[Candidate] = []
    for code, name in UNIVERSE:
        sym = f"{code}.T"
        try:
            sub = df[sym] if sym in df.columns.get_level_values(0) else None
            if sub is None or sub.empty:
                continue
            closes = sub["Close"].dropna()
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            if price <= 0 or price > max_share_price:
                continue
            candidates.append(Candidate(
                code=code, name=name,
                prev_close=price,
                lot_total=price * 100,
            ))
        except Exception as e:
            print(f"[warn] {code} skip: {e}")
            continue

    # 価格高い順 = 予算をフル活用しやすい順 → 多様性のため価格分位でサンプリング
    candidates.sort(key=lambda c: c.prev_close, reverse=True)
    if len(candidates) > max_count:
        # 価格帯を3分割して各から均等に
        step = max(1, len(candidates) // max_count)
        candidates = candidates[::step][:max_count]
    print(f"[info] 予算{budget_man}万円(株価{max_share_price:,}円以下) 候補 {len(candidates)}件")
    return candidates


if __name__ == "__main__":
    import json
    for c in fetch_candidates(20):
        print(json.dumps(c.to_dict(), ensure_ascii=False))
