from __future__ import annotations

import json
import os
from unittest import TestCase
from unittest.mock import patch

from wechat_ai.config import Config
from wechat_ai.llm import ChatModel, ModelError


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return b'{"choices":[{"message":{"content":" reply "}}]}'


class ConfigAndModelTests(TestCase):
    def test_reject_insecure_api_url(self):
        config = Config("bot", ("group",), "http://example.com/v1", "model")
        with self.assertRaises(ValueError):
            config.validate()

    def test_local_model_needs_no_api_key(self):
        config = Config("bot", ("group",), "http://127.0.0.1:11434/v1", "deepseek-r1:8b")
        config.validate()
        with patch.dict(os.environ, {}, clear=True):
            with patch("wechat_ai.llm.urlopen", return_value=FakeResponse()) as call:
                self.assertEqual(ChatModel(config).complete("system", "user"), "reply")
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertFalse(request.has_header("Authorization"))

    def test_model_request_uses_key_and_two_messages(self):
        config = Config("bot", ("group",), "https://example.com/v1", "model")
        with patch.dict(os.environ, {"WECHAT_AI_API_KEY": "test-key"}):
            with patch("wechat_ai.llm.urlopen", return_value=FakeResponse()) as call:
                self.assertEqual(ChatModel(config).complete("system", "user"), "reply")
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        payload = json.loads(request.data)
        self.assertEqual([message["role"] for message in payload["messages"]], ["system", "user"])

    def test_missing_key_fails_without_network(self):
        config = Config("bot", ("group",), "https://example.com/v1", "model")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ModelError):
                ChatModel(config).complete("system", "user")
