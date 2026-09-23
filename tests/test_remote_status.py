from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

from remote.status_service import State, handler_factory


class RelayTests(TestCase):
    def test_offline_status_and_stale_command_expiry(self):
        with TemporaryDirectory() as directory:
            state = State(str(Path(directory) / "status.db"))
            self.assertEqual(state.status("vm1")["task_state"], "offline")
            with patch("remote.status_service.time.time", return_value=100):
                state.heartbeat("vm1", True, "running")
                command_id = state.enqueue("vm1", "stop")
                self.assertEqual(state.pending("vm1"), [{"id": command_id, "action": "stop"}])
            with patch("remote.status_service.time.time", return_value=200):
                self.assertFalse(state.status("vm1")["online"])
                self.assertFalse(state.status("vm1")["running"])
                self.assertEqual(state.pending("vm1"), [])
            state.conn.close()

    def test_relay_schema_has_no_chat_payload(self):
        with TemporaryDirectory() as directory:
            state = State(str(Path(directory) / "status.db"))
            tables = {row[0]: row[1] for row in state.conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table'"
            )}
            self.assertIn("agents", tables)
            self.assertIn("commands", tables)
            self.assertNotIn("body", " ".join(tables.values()).lower())
            state.conn.close()

    def test_rejects_chat_payload_and_separates_agent_admin_tokens(self):
        with TemporaryDirectory() as directory:
            state = State(str(Path(directory) / "status.db"))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(state, "a" * 32, "b" * 32))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            def post(path, token, body):
                request = Request(base + path, data=json.dumps(body).encode(),
                                  headers={"Authorization": "Bearer " + token,
                                           "Content-Type": "application/json"})
                try:
                    with urlopen(request) as response:
                        return response.status
                except HTTPError as exc:
                    return exc.code
            try:
                self.assertEqual(post("/heartbeat", "a" * 32,
                                      {"agent_id": "vm1", "running": True,
                                       "task_state": "running", "body": "secret"}), 400)
                self.assertEqual(post("/command", "a" * 32,
                                      {"agent_id": "vm1", "action": "stop"}), 403)
                self.assertEqual(post("/command", "b" * 32,
                                      {"agent_id": "vm1", "action": "stop"}), 200)
            finally:
                server.shutdown()
                server.server_close()
                state.conn.close()
