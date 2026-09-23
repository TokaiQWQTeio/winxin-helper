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
from wechat_ai.uia_preview import Snapshot


class ControlPageTests(TestCase):
    def test_powershell_environment_has_one_path_key(self):
        with patch.object(web_control.os, "environ", {"PATH": "first", "Path": "second", "OTHER": "yes"}):
            environment = web_control._powershell_env()
        self.assertEqual([key for key in environment if key.casefold() == "path"], ["Path"])
        self.assertEqual(environment["Path"], "second")

    def test_start_error_uses_utf8_bot_log(self):
        with TemporaryDirectory() as directory:
            log = Path(directory) / "bot.stderr.log"
            log.write_text("__main__.py: error: 没有找到已打开的测试群窗口：text\n", encoding="utf-8")
            with patch.object(web_control, "BOT_ERROR_LOG", log):
                self.assertEqual(web_control._bot_start_error(), "没有找到已打开的测试群窗口：text")

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
        patcher = patch.object(web_control, "_wechat_window_visible", return_value=False)
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

    def test_hidden_wechat_prevents_start(self):
        controller = web_control.Controller()
        with patch.object(web_control, "_require_visible_wechat", side_effect=ValueError("微信已缩到托盘")):
            with self.assertRaisesRegex(ValueError, "缩到托盘"):
                controller.start({"accept_focus": True})
        self.assertFalse(web_control.Config.load(self.config_path).auto_send_enabled)

    def test_group_only_window_is_readable_without_session_preview(self):
        with patch("wechat_ai.uia_preview.read_group", return_value=Snapshot(1, (0, 0), (), "")):
            self.assertTrue(web_control._target_group_readable(("text",)))
        with patch("wechat_ai.uia_preview.read_group", return_value=Snapshot(1, (0, 0), (), "text\n张三: 消息")):
            self.assertTrue(web_control._target_group_readable(("text",)))
        with patch("wechat_ai.uia_preview.read_group", side_effect=RuntimeError("group missing")):
            self.assertFalse(web_control._target_group_readable(("text",)))

    def test_start_and_stop_update_flags_and_supervise_bot(self):
        controller = web_control.Controller()
        controller.save_model({
            "provider": "api", "api_base_url": "https://example.com/v1",
            "model": "other-model", "api_key_env": "MY_MODEL_KEY",
        })
        process = MagicMock()
        process.pid = 12345
        with patch.object(web_control, "_process", side_effect=[None, process, process]), \
             patch.object(web_control, "_require_visible_wechat"), \
             patch.object(web_control, "_target_group_readable", return_value=True), \
             patch.object(web_control.subprocess, "run", return_value=MagicMock(returncode=0)) as launch, \
             patch.dict(web_control.os.environ, {"MY_MODEL_KEY": "test-key"}):
            result = controller.start({"accept_focus": True})
        self.assertEqual(launch.call_args.kwargs["stdout"], web_control.subprocess.DEVNULL)
        self.assertEqual(launch.call_args.kwargs["stderr"], web_control.subprocess.DEVNULL)
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
        self.assertFalse(status["wechat_window_visible"])
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
