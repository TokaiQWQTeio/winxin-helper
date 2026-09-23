from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from wechat_ai import web_control


class ControlPageTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config_path = Path(self.directory.name) / "config.json"
        self.config_path.write_text(json.dumps({
            "bot_name": "hi～", "groups": ["text"],
            "api_base_url": "http://127.0.0.1:11434/v1", "model": "deepseek-r1:8b",
            "auto_send_enabled": False, "focus_send_enabled": False,
        }), encoding="utf-8")
        patcher = patch.object(web_control, "CONFIG_PATH", self.config_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(web_control, "_process", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(web_control, "_local_model_status", return_value="Ollama 已运行")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_model_switch_preserves_disabled_state_and_rejects_http_api(self):
        controller = web_control.Controller()
        result = controller.save_model({
            "provider": "api", "api_base_url": "https://example.com/v1",
            "model": "other-model", "api_key_env": "MY_MODEL_KEY",
        })
        self.assertEqual(result["model"], "other-model")
        stored = web_control.Config.load(self.config_path)
        self.assertFalse(stored.auto_send_enabled)
        self.assertFalse(stored.focus_send_enabled)
        with self.assertRaises(ValueError):
            controller.save_model({
                "provider": "api", "api_base_url": "http://example.com/v1",
                "model": "other-model", "api_key_env": "MY_MODEL_KEY",
            })

    def test_start_requires_focus_acknowledgement_before_any_process_change(self):
        controller = web_control.Controller()
        with self.assertRaisesRegex(ValueError, "确认"):
            controller.start({"accept_focus": False})
        self.assertFalse(web_control.Config.load(self.config_path).auto_send_enabled)

    def test_start_and_stop_update_flags_and_supervise_bot(self):
        controller = web_control.Controller()
        controller.save_model({
            "provider": "api", "api_base_url": "https://example.com/v1",
            "model": "other-model", "api_key_env": "MY_MODEL_KEY",
        })
        process = MagicMock()
        process.pid = 12345
        with patch.object(web_control, "_process", side_effect=[None, process, process]), \
             patch.object(web_control.subprocess, "run", return_value=MagicMock(returncode=0)), \
             patch.dict(web_control.os.environ, {"MY_MODEL_KEY": "test-key"}):
            result = controller.start({"accept_focus": True})
        self.assertTrue(result["running"])
        self.assertTrue(web_control.Config.load(self.config_path).auto_send_enabled)
        self.assertTrue(web_control.Config.load(self.config_path).focus_send_enabled)
        pid_path = Path(self.directory.name) / "bot.pid"
        pid_path.write_text("12345", encoding="utf-8")
        with patch.object(web_control, "PID_PATH", pid_path), \
             patch.object(web_control, "_process", side_effect=[process, None]):
            result = controller.stop()
        self.assertFalse(result["running"])
        self.assertFalse(web_control.Config.load(self.config_path).auto_send_enabled)
        self.assertFalse(web_control.Config.load(self.config_path).focus_send_enabled)
        self.assertFalse(pid_path.exists())
        process.terminate.assert_called_once()

    def test_http_status_and_token_guard(self):
        controller = web_control.Controller()
        web_control.Handler.controller = controller
        server = ThreadingHTTPServer(("127.0.0.1", 0), web_control.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        with urlopen(url + "/api/status") as response:
            status = json.load(response)
        self.assertFalse(status["running"])
        self.assertEqual(status["model"], "deepseek-r1:8b")
        with urlopen(url) as response:
            page = response.read().decode("utf-8")
        self.assertIn(controller.token, page)
        request = Request(url + "/api/start", b'{"accept_focus":true}', {
            "Content-Type": "application/json",
        })
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)
