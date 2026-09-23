"""Live group loop; activation is gated by config and sender validation."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import logging
import os
import time
from uuid import uuid4

from .config import Config
from .llm import ChatModel
from .models import GroupMessage
from .service import Assistant
from .store import Store
from .uia_preview import has_mention_marker, has_verified_mention, identify_sender, new_items, read_group, sender_from_session_preview
from .uia_sender import UIASender


LOG = logging.getLogger(__name__)


def run(config: Config, interval: float = 2.0, one_shot: bool = False) -> None:
    if not config.auto_send_enabled and not one_shot:
        raise RuntimeError("自动发送未启用；先用 watch-preview 完成群聊验证")
    if not config.focus_send_enabled:
        raise RuntimeError("发送可能短暂切换焦点；须在本机控制页明确启用")
    if one_shot and len(config.groups) != 1:
        raise RuntimeError("单次发送测试只能配置一个群")
    if config.api_base_url == "https://api.example.com/v1" or config.model == "your-model-name":
        raise RuntimeError("模型地址和名称仍是示例值")
    if not config.is_local_model and not os.environ.get(config.api_key_env):
        raise RuntimeError(f"缺少模型 API 密钥环境变量：{config.api_key_env}")

    # No old UI messages are replayed when the process starts or reconnects.
    previous = {}
    for group in config.groups:
        previous[group] = read_group(group)
    session_id = uuid4().hex
    sequence = 0
    store = Store(config.database_path)
    active_config = replace(config, auto_send_enabled=True) if one_shot else config
    assistant = Assistant(active_config, store, ChatModel(config), UIASender(allow_focus=True))
    next_maintenance = time.monotonic() + 24 * 60 * 60
    if one_shot:
        LOG.info("单次自动回复测试已启动：等待 %s 群下一条真正 @ %s", config.groups[0], config.bot_name)
    else:
        LOG.info("实时监听已启动：%s", ", ".join(config.groups))
    try:
        while True:
            time.sleep(interval)
            if time.monotonic() >= next_maintenance:
                try:
                    removed = assistant.maintenance()
                    LOG.info("每日清理完成：删除 %s 条过期原文", removed)
                except Exception:
                    LOG.exception("每日清理失败")
                finally:
                    next_maintenance = time.monotonic() + 24 * 60 * 60
            for group in config.groups:
                try:
                    current = read_group(group)
                except RuntimeError:
                    if group in previous:
                        LOG.warning("群窗口不可读取，恢复后将重新建立基线：%s", group)
                    previous.pop(group, None)
                    continue
                earlier = previous.get(group)
                previous[group] = current
                if earlier is None or earlier.hwnd != current.hwnd:
                    LOG.info("群窗口已恢复，重新建立消息基线：%s", group)
                    continue
                for item in new_items(earlier.items, current.items):
                    if item.kind != "mmui::ChatTextItemView" or not item.text.strip():
                        continue
                    is_candidate = has_mention_marker(item.text, config.bot_name)
                    sender = (
                        sender_from_session_preview(current, item, config.bot_name)
                        if is_candidate else None
                    )
                    visual_sender_confirmed = False
                    if sender is None:
                        sender = identify_sender(current, item)
                        visual_sender_confirmed = sender is not None
                    if sender is None:
                        LOG.warning("发送者无法确认，跳过：%s", group)
                        continue
                    sequence += 1
                    event = GroupMessage(
                        group=group,
                        sender=sender,
                        text=item.text,
                        source_id=f"{session_id}-{sequence}",
                        received_at=datetime.now(timezone.utc),
                        mention_verified=has_verified_mention(
                            current, item, config.bot_name, sender,
                            visual_sender_confirmed=visual_sender_confirmed,
                        ),
                        group_member_count=current.member_count,
                    )
                    result = assistant.ingest(event)
                    LOG.info("消息处理结果：%s %s", group, result)
                    if one_shot and event.mention_verified and sender != config.bot_name:
                        LOG.info("单次发送测试已处理一条合格 @，正在退出")
                        return
    finally:
        store.close()
