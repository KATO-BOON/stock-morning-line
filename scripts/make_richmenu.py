"""リッチメニュー画像を生成し、LINE Bot に登録する。

実行方法:
  LINE_CHANNEL_ACCESS_TOKEN=xxx PAGES_URL=https://... py scripts/make_richmenu.py
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
PAGES_URL = os.environ.get("PAGES_URL", "https://kato-boon.github.io/stock-morning-line/")

# リッチメニューサイズ: 2500x843 (コンパクト)
# 3エリアに分割: 左=設定, 中=今すぐ配信, 右=最新ニュース
W, H = 2500, 843


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/YuGothB.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_image() -> bytes:
    img = Image.new("RGB", (W, H), (6, 199, 85))  # LINE green
    d = ImageDraw.Draw(img)

    # 3分割
    w3 = W // 3
    # 罫線（白の細いライン）
    line_color = (255, 255, 255)
    d.line([(w3, 60), (w3, H - 60)], fill=line_color, width=4)
    d.line([(w3 * 2, 60), (w3 * 2, H - 60)], fill=line_color, width=4)

    title_font = _find_font(120)
    sub_font = _find_font(60)

    # 左: 朝ニュース設定
    _draw_cell(d, 0, 0, w3, H, "📰", "朝ニュース", "予算・配信日", title_font, sub_font)
    # 中: 保有銘柄
    _draw_cell(d, w3, 0, w3, H, "📊", "保有銘柄", "損切・利確通知", title_font, sub_font)
    # 右: 今すぐ配信
    _draw_cell(d, w3 * 2, 0, w3, H, "🚀", "今すぐ配信", "ブリーフ実行", title_font, sub_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_cell(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
               emoji: str, title: str, sub: str,
               title_font, sub_font) -> None:
    # アイコン風絵文字（大）
    cx = x + w // 2
    cy_emoji = y + int(h * 0.25)
    d.text((cx, cy_emoji), emoji, fill=(255, 255, 255), font=title_font, anchor="mm")
    # タイトル
    d.text((cx, y + int(h * 0.55)), title, fill=(255, 255, 255), font=title_font, anchor="mm")
    # サブ
    d.text((cx, y + int(h * 0.80)), sub, fill=(240, 255, 240), font=sub_font, anchor="mm")


def create_richmenu() -> str:
    body = {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "stock-morning-main",
        "chatBarText": "メニュー",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": W // 3, "height": H},
                "action": {"type": "uri", "label": "朝ニュース", "uri": PAGES_URL + "morning.html"},
            },
            {
                "bounds": {"x": W // 3, "y": 0, "width": W // 3, "height": H},
                "action": {"type": "uri", "label": "保有銘柄", "uri": PAGES_URL + "holdings.html"},
            },
            {
                "bounds": {"x": 2 * W // 3, "y": 0, "width": W // 3, "height": H},
                "action": {"type": "uri", "label": "今すぐ配信", "uri": PAGES_URL + "morning.html?auto=run"},
            },
        ],
    }
    resp = requests.post(
        "https://api.line.me/v2/bot/richmenu",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    rid = resp.json()["richMenuId"]
    print(f"[ok] richmenu作成: {rid}")
    return rid


def upload_image(rid: str, png: bytes) -> None:
    resp = requests.post(
        f"https://api-data.line.me/v2/bot/richmenu/{rid}/content",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "image/png",
        },
        data=png,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"upload失敗 {resp.status_code}: {resp.text}")
    print(f"[ok] 画像アップロード完了")


def set_default(rid: str) -> None:
    resp = requests.post(
        f"https://api.line.me/v2/bot/user/all/richmenu/{rid}",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"default設定失敗 {resp.status_code}: {resp.text}")
    print(f"[ok] デフォルトに設定")


def delete_existing() -> None:
    """既存のリッチメニューを削除して重複防止。"""
    resp = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )
    if resp.status_code == 200:
        for m in resp.json().get("richmenus", []):
            if m.get("name", "").startswith("stock-morning"):
                rid = m["richMenuId"]
                requests.delete(
                    f"https://api.line.me/v2/bot/richmenu/{rid}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    timeout=15,
                )
                print(f"[info] 既存メニュー削除: {rid}")


def main() -> int:
    delete_existing()
    png = make_image()
    out_path = ROOT / "docs" / "richmenu.png"
    out_path.write_bytes(png)
    print(f"[info] 画像保存: {out_path} ({len(png)} bytes)")
    rid = create_richmenu()
    upload_image(rid, png)
    set_default(rid)
    print("[done] 完了。LINEアプリを一度閉じて再度開くとメニュー表示されます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
