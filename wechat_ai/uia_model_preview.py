"""Preview model answers for verified group mentions without sending them."""
from __future__ import annotations

import sys
import time

from .config import Config
from .llm import ChatModel, ModelError
from .uia_preview import (
    has_mention_marker,
    has_verified_mention,
    new_items,
    read_group,
    sender_from_session_preview,
)


def watch_model(config: Config, interval: float = 2.0) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    group = config.groups[0]
    previous = read_group(group)
    model = ChatModel(config)
    print(f"问答预览已启动：{group}；请在群里真正 @ {config.bot_name} 提问。", flush=True)
    while True:
        time.sleep(interval)
        try:
            current = read_group(group)
        except RuntimeError:
            print("群窗口暂时不可读取，等待恢复。", flush=True)
            previous = None
            continue
        if previous is None or current.hwnd != previous.hwnd:
            previous = current
            continue
        for item in new_items(previous.items, current.items):
            if item.kind != "mmui::ChatTextItemView" or not has_mention_marker(item.text, config.bot_name):
                continue
            sender = sender_from_session_preview(current, item, config.bot_name)
            if sender is None or not has_verified_mention(current, item, config.bot_name, sender):
                print("检测到候选 @，但发送者或 @ 信号未确认；已跳过。", flush=True)
                continue
            if sender == config.bot_name:
                continue
            print(f"已确认提问者：{sender}；问题：{item.text}", flush=True)
            try:
                reply = model.complete(
                    "你是微信群里的 AI 助手。请用简洁中文回答提问，只输出要发到群里的回复正文。",
                    item.text,
                )
            except ModelError as exc:
                print(f"模型出错：{exc}", flush=True)
            else:
                print(f"预览回复（未发送）：{reply}", flush=True)
        previous = current
