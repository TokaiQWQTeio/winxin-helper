from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from wechat_ai.config import Config
from wechat_ai.uia_live import run
from wechat_ai.uia_preview import Item, Snapshot
from wechat_ai.uia_sender import UIASender


class LiveOneShotTests(TestCase):
    def test_default_sender_never_uses_mouse(self):
        with self.assertRaisesRegex(RuntimeError, "可能切换焦点的发送方式未获启用"):
            UIASender().send("text", "张三", "回复")

    def test_next_verified_mention_sends_once_and_exits(self):
        old = Item("mmui::ChatTextItemView", "旧消息")
        mention = Item("mmui::ChatTextItemView", "@hi～\u2005你好")
        before = Snapshot(1, (0, 0), (old,), "text\n")
        after = Snapshot(1, (0, 0), (old, mention), f"text\n[有人@我]\n张三: {mention.text}\n")
        model = MagicMock()
        model.complete.return_value = "你好！"
        sender = MagicMock()
        sender.send.return_value = True
        with TemporaryDirectory() as directory:
            config = Config("hi～", ("text",), "http://127.0.0.1:11434/v1", "deepseek-r1:8b",
                            database_path=str(Path(directory) / "assistant.db"), auto_send_enabled=False,
                            focus_send_enabled=True)
            with patch("wechat_ai.uia_live.read_group", side_effect=[before, after]), \
                 patch("wechat_ai.uia_live.time.sleep"), \
                 patch("wechat_ai.uia_live.sender_from_session_preview", return_value=None), \
                 patch("wechat_ai.uia_live.identify_sender", return_value="张三") as identify, \
                 patch("wechat_ai.uia_live.ChatModel", return_value=model), \
                 patch("wechat_ai.uia_live.UIASender", return_value=sender):
                run(config, one_shot=True)
        identify.assert_called_once_with(after, mention)
        sender.send.assert_called_once_with("text", "张三", "你好！")
        self.assertFalse(config.auto_send_enabled)

    def test_chat_only_mention_uses_visual_sender(self):
        old = Item("mmui::ChatTextItemView", "旧消息")
        mention = Item("mmui::ChatTextItemView", "@hi～\u2005你好")
        before = Snapshot(1, (0, 0), (old,), "")
        after = Snapshot(1, (0, 0), (old, mention), "")
        with TemporaryDirectory() as directory:
            config = Config("hi～", ("text",), "http://127.0.0.1:11434/v1", "deepseek-r1:8b",
                            database_path=str(Path(directory) / "assistant.db"), auto_send_enabled=False,
                            focus_send_enabled=True)
            model = MagicMock()
            model.complete.return_value = "你好！"
            sender = MagicMock()
            sender.send.return_value = True
            with patch("wechat_ai.uia_live.read_group", side_effect=[before, after]), \
                 patch("wechat_ai.uia_live.time.sleep"), \
                 patch("wechat_ai.uia_live.identify_sender", return_value="李四"), \
                 patch("wechat_ai.uia_live.ChatModel", return_value=model), \
                 patch("wechat_ai.uia_live.UIASender", return_value=sender):
                run(config, one_shot=True)
        sender.send.assert_called_once_with("text", "李四", "你好！")
