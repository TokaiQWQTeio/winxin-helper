from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from wechat_ai import uia_preview
from wechat_ai.uia_preview import Item, Snapshot, has_mention_marker, has_verified_mention, new_items, sender_from_session_preview


class PreviewTests(unittest.TestCase):
    def test_switch_requires_unique_session_and_verified_title(self):
        cell = MagicMock()
        cell.ClassName = "mmui::ChatSessionCell"
        cell.Name = "甲群\n张三: 你好"
        window = SimpleNamespace(ProcessId=123)
        uia = SimpleNamespace(SetGlobalSearchTimeout=lambda _: None,
                              GetRootControl=lambda: SimpleNamespace(GetChildren=lambda: [window]))
        snapshot = Snapshot(1, (0, 0), ())
        with patch.dict("sys.modules", {"uiautomation": uia}), \
             patch.object(uia_preview, "_wechat_pids", return_value={123}), \
             patch.object(uia_preview, "_walk", return_value=[cell]), \
             patch.object(uia_preview, "read_group", return_value=snapshot) as read:
            self.assertEqual(uia_preview.select_group("甲群"), snapshot)
            read.assert_called_with("甲群")
            with self.assertRaisesRegex(RuntimeError, "唯一定位"):
                uia_preview.select_group("乙群")

    def test_overlap_detects_repeated_new_message(self):
        a = Item("text", "一样")
        b = Item("text", "另一条")
        self.assertEqual(new_items((a, b), (a, b, a)), (a,))
        self.assertEqual(new_items((a, b), (b, a)), (a,))

    def test_reset_does_not_replay_old_items(self):
        self.assertEqual(new_items((Item("text", "旧"),), (Item("text", "不同窗口"),)), ())

    def test_mention_marker_requires_exact_nickname_and_separator(self):
        self.assertTrue(has_mention_marker("@hi～\u2005123", "hi～"))
        self.assertFalse(has_mention_marker("@hi～123", "hi～"))
        self.assertFalse(has_mention_marker("@hi~123", "hi～"))

    def test_verified_mention_requires_matching_session_badge_and_sender(self):
        item = Item("mmui::ChatTextItemView", "@hi～\u2005你好")
        snapshot = Snapshot(1, (0, 0), (item,), "text\n[1条]\n[有人@我]\n张三: @hi～\u2005你好\n")
        self.assertTrue(has_verified_mention(snapshot, item, "hi～", "张三"))
        self.assertFalse(has_verified_mention(snapshot, item, "hi～", "李四"))
        stale = Snapshot(1, (0, 0), (item,), "text\n[有人@我]\n张三: 别的消息\n")
        self.assertFalse(has_verified_mention(stale, item, "hi～", "张三"))

    def test_chat_only_mention_requires_visual_sender_confirmation(self):
        item = Item("mmui::ChatTextItemView", "@hi～\u2005你好")
        snapshot = Snapshot(1, (0, 0), (item,), "")
        self.assertFalse(has_verified_mention(snapshot, item, "hi～", "张三"))
        self.assertTrue(has_verified_mention(
            snapshot, item, "hi～", "张三", visual_sender_confirmed=True,
        ))
        typed = Item("mmui::ChatTextItemView", "@hi～ 你好")
        self.assertFalse(has_verified_mention(
            snapshot, typed, "hi～", "张三", visual_sender_confirmed=True,
        ))

    def test_latest_preview_extracts_different_group_senders(self):
        item = Item("mmui::ChatTextItemView", "@hi～\u2005你好")
        for sender in ("张三", "李四", "TokaiTeio"):
            snapshot = Snapshot(1, (0, 0), (item,), f"text\n[有人@我]\n{sender}: {item.text}\n")
            self.assertEqual(sender_from_session_preview(snapshot, item, "hi～"), sender)
        unrelated = Snapshot(1, (0, 0), (item,), "text\n[有人@我]\n李四: 别的消息\n")
        self.assertIsNone(sender_from_session_preview(unrelated, item, "hi～"))


if __name__ == "__main__":
    unittest.main()
