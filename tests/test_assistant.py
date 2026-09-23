from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import tempfile
import unittest

from wechat_ai.config import Config
from wechat_ai.models import GroupMessage, utcnow
from wechat_ai.service import Assistant
from wechat_ai.store import Store


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail = False

    def complete(self, system, user):
        self.calls.append((system, user))
        if self.fail:
            raise RuntimeError("API unavailable")
        return "收到，我来回答。"


class FakeSender:
    def __init__(self):
        self.calls = []
        self.fail = False

    def send(self, group, recipient, text):
        self.calls.append((group, recipient, text))
        return not self.fail


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + "/assistant.db")
        self.config = Config(
            bot_name="小助手", groups=("甲群", "乙群"),
            api_base_url="https://example.com/v1", model="test",
            auto_send_enabled=True, summary_batch_size=2,
        )
        self.model = FakeModel()
        self.sender = FakeSender()
        self.bot = Assistant(self.config, self.store, self.model, self.sender)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def event(self, group="甲群", source_id="1", text="@小助手 问题", **kwargs):
        return GroupMessage(
            group=group, sender="张三", text=text, source_id=source_id,
            received_at=kwargs.get("received_at", utcnow()),
            is_self=kwargs.get("is_self", False),
            mention_verified=kwargs.get("mention_verified", True),
            group_member_count=kwargs.get("group_member_count"),
        )

    def test_verified_mention_only_and_deduplication(self):
        self.assertEqual(self.bot.ingest(self.event(source_id="1", mention_verified=False)), "context_only")
        self.assertEqual(self.bot.ingest(self.event(source_id="2")), "sent")
        self.assertEqual(self.bot.ingest(self.event(source_id="2")), "duplicate")
        self.assertEqual(len(self.sender.calls), 1)
        self.assertEqual(self.sender.calls[0][:2], ("甲群", "张三"))

    def test_group_isolation_and_self_filter(self):
        self.bot.ingest(self.event(group="甲群", source_id="1", text="甲群秘密", mention_verified=False))
        self.bot.ingest(self.event(group="乙群", source_id="2"))
        self.assertNotIn("甲群秘密", self.model.calls[-1][1])
        self.assertEqual(self.bot.ingest(self.event(group="丙群", source_id="3")), "group_not_allowed")
        self.assertEqual(self.bot.ingest(self.event(source_id="4", is_self=True)), "self_message")

    def test_group_count_and_sent_reply_are_in_context(self):
        self.bot.ingest(self.event(source_id="context", text="青山之东: 大家好", mention_verified=False))
        self.assertEqual(self.bot.ingest(self.event(
            source_id="question", text="@小助手 群里有几个人", group_member_count=3,
        )), "sent")
        prompt = self.model.calls[-1][1]
        self.assertIn("当前群成员总数（微信标题栏）：3", prompt)
        self.assertIn("青山之东: 大家好", prompt)
        self.assertEqual(self.bot.ingest(self.event(source_id="followup", text="@小助手 刚才说了什么")), "sent")
        self.assertIn("小助手: 收到，我来回答。", self.model.calls[-1][1])

    def test_disabled_and_api_failure_do_not_send(self):
        disabled = Assistant(replace(self.config, auto_send_enabled=False), self.store, self.model, self.sender)
        self.assertEqual(disabled.ingest(self.event(source_id="1")), "send_disabled")
        self.model.fail = True
        self.assertEqual(self.bot.ingest(self.event(source_id="2")), "model_failed")
        self.assertEqual(self.sender.calls, [])

    def test_uncertain_send_never_retries(self):
        self.sender.fail = True
        event = self.event(source_id="1")
        self.assertEqual(self.bot.ingest(event), "send_uncertain")
        self.assertEqual(self.bot.ingest(event), "duplicate")
        self.assertEqual(len(self.sender.calls), 1)

    def test_summary_and_retention(self):
        old = utcnow() - timedelta(days=8)
        self.bot.ingest(self.event(source_id="1", text="决定周五见", received_at=old, mention_verified=False))
        self.bot.ingest(self.event(source_id="2", text="地点待定", received_at=old, mention_verified=False))
        self.assertTrue(self.bot.summarize("甲群"))
        self.assertEqual(self.store.summary("甲群")[0], "收到，我来回答。")
        self.assertEqual(self.bot.maintenance(), 2)
        self.assertEqual(self.store.recent("甲群", 50), [])
        self.store.clear_summary("甲群")
        self.assertEqual(self.store.summary("甲群"), ("", 0))

    def test_retention_even_when_summary_api_fails(self):
        old = utcnow() - timedelta(days=8)
        self.bot.ingest(self.event(source_id="1", text="旧消息", received_at=old, mention_verified=False))
        self.model.fail = True
        self.assertEqual(self.bot.maintenance(), 1)
        self.assertEqual(self.store.recent("甲群", 50), [])

    def test_clear_summary_does_not_regenerate_old_text(self):
        self.bot.ingest(self.event(source_id="1", text="旧事实", mention_verified=False))
        self.store.clear_summary("甲群")
        self.assertEqual(self.store.pending_summary("甲群"), [])


if __name__ == "__main__":
    unittest.main()
