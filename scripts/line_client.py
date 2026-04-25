"""LINE Messaging APIクライアント。"""
from __future__ import annotations

import os
from typing import List

import requests

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _chunks(text: str, size: int = 4900) -> List[str]:
    """LINEは1メッセージ5000字上限。改行境界で分割して途切れを防ぐ。"""
    if len(text) <= size:
        return [text] if text else [""]
    result = []
    remaining = text
    while len(remaining) > size:
        # size手前から最も近い改行を探す
        cut = remaining.rfind("\n", 0, size)
        if cut < size // 2:  # 改行が近すぎて無駄 → 空白境界
            cut = remaining.rfind(" ", 0, size)
        if cut < 0:
            cut = size
        result.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n ")
    if remaining:
        result.append(remaining)
    return result[:5]  # 1回のbroadcastで最大5通


def broadcast(message: str, token: str | None = None) -> int:
    token = token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN が未設定です")

    chunks = _chunks(message)
    print(f"[info] LINE分割: {len(chunks)}通 / 各{[len(c) for c in chunks]}字")
    msgs = [{"type": "text", "text": c} for c in chunks]
    resp = requests.post(
        BROADCAST_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"messages": msgs[:5]},  # 1APIで最大5通
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"LINE broadcast失敗 {resp.status_code}: {resp.text}")
    return resp.status_code
