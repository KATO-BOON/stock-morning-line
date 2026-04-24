"""LINE Messaging APIクライアント。"""
from __future__ import annotations

import os
from typing import List

import requests

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _chunks(text: str, size: int = 4900) -> List[str]:
    """LINEは1メッセージ5000字上限。余裕を持って4900で分割。"""
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def broadcast(message: str, token: str | None = None) -> int:
    token = token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN が未設定です")

    msgs = [{"type": "text", "text": c} for c in _chunks(message)]
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
