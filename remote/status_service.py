"""Metadata-only control relay. Bind only to a WireGuard address.

No message body, media, prompt, summary, group title or member name is accepted.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import ipaddress
import json
import os
import sqlite3
import threading
import time


COMMANDS = {"start", "stop", "pause", "resume"}


class State:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY, seen_at INTEGER NOT NULL,
                    running INTEGER NOT NULL, task_state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL,
                    action TEXT NOT NULL, state TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                );
            """)

    def heartbeat(self, agent_id: str, running: bool, task_state: str) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO agents VALUES (?,?,?,?) ON CONFLICT(agent_id)
                   DO UPDATE SET seen_at=excluded.seen_at,running=excluded.running,
                     task_state=excluded.task_state""",
                (agent_id, int(time.time()), int(running), task_state),
            )

    def status(self, agent_id: str) -> dict:
        with self.lock:
            row = self.conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        online = bool(row and int(time.time()) - row["seen_at"] <= 30)
        return {"online": online, "running": bool(row["running"]) if online else False,
                "task_state": row["task_state"] if online else "offline",
                "last_seen": row["seen_at"] if row else None}

    def enqueue(self, agent_id: str, action: str) -> int:
        if action not in COMMANDS:
            raise ValueError("invalid action")
        now = int(time.time())
        with self.lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO commands(agent_id,action,state,created_at,updated_at) VALUES (?,?, 'pending',?,?)",
                (agent_id, action, now, now),
            )
            return cursor.lastrowid

    def pending(self, agent_id: str) -> list[dict]:
        with self.lock, self.conn:
            self.conn.execute(
                """UPDATE commands SET state='expired',updated_at=?
                   WHERE agent_id=? AND state='pending' AND created_at<?""",
                (int(time.time()), agent_id, int(time.time()) - 60),
            )
            return [dict(row) for row in self.conn.execute(
                "SELECT id,action FROM commands WHERE agent_id=? AND state='pending' ORDER BY id LIMIT 20",
                (agent_id,),
            )]

    def acknowledge(self, agent_id: str, command_id: int, state: str) -> None:
        if state not in {"done", "failed"}:
            raise ValueError("invalid state")
        with self.lock, self.conn:
            cursor = self.conn.execute(
                """UPDATE commands SET state=?,updated_at=?
                   WHERE id=? AND agent_id=? AND state='pending'""",
                (state, int(time.time()), command_id, agent_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("unknown command")


def handler_factory(state: State, agent_token: str, admin_token: str):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, value: dict | list) -> None:
            body = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, role: str) -> bool:
            supplied = self.headers.get("Authorization", "")
            token = admin_token if role == "admin" else agent_token
            return hmac.compare_digest(supplied, "Bearer " + token)

        def _agent(self, value: object) -> str:
            if not isinstance(value, str) or not value.isascii() or not (1 <= len(value) <= 64) or not all(c.isalnum() or c in "_-" for c in value):
                raise ValueError("invalid agent_id")
            return value

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 512:
                raise ValueError("invalid body length")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("invalid body")
            return data

        def do_GET(self) -> None:
            route, _, query = self.path.partition("?")
            if not self._authorized("admin" if route == "/status" else "agent"):
                self._reply(403, {"error": "forbidden"})
                return
            try:
                from urllib.parse import parse_qs
                agent_id = self._agent(parse_qs(query).get("agent_id", [""])[0])
                if route == "/status":
                    self._reply(200, state.status(agent_id))
                elif route == "/commands":
                    self._reply(200, state.pending(agent_id))
                else:
                    self._reply(404, {"error": "not found"})
            except (ValueError, TypeError):
                self._reply(400, {"error": "bad request"})

        def do_POST(self) -> None:
            role = "admin" if self.path == "/command" else "agent"
            if not self._authorized(role):
                self._reply(403, {"error": "forbidden"})
                return
            try:
                data = self._json_body()
                agent_id = self._agent(data.get("agent_id"))
                if self.path == "/heartbeat" and set(data) == {"agent_id", "running", "task_state"}:
                    if not isinstance(data["running"], bool) or data["task_state"] not in {"idle", "running", "paused", "error"}:
                        raise ValueError("invalid heartbeat")
                    state.heartbeat(agent_id, data["running"], data["task_state"])
                    result = {"ok": True}
                elif self.path == "/command" and set(data) == {"agent_id", "action"}:
                    result = {"id": state.enqueue(agent_id, data["action"])}
                elif self.path == "/ack" and set(data) == {"agent_id", "id", "state"}:
                    if type(data["id"]) is not int:
                        raise ValueError("invalid id")
                    state.acknowledge(agent_id, data["id"], data["state"])
                    result = {"ok": True}
                else:
                    raise ValueError("invalid route or fields")
                self._reply(200, result)
            except (ValueError, TypeError, json.JSONDecodeError):
                self._reply(400, {"error": "bad request"})

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def main() -> None:
    bind = os.environ.get("ASSISTANT_WG_BIND", "")
    agent_token = os.environ.get("ASSISTANT_AGENT_TOKEN", "")
    admin_token = os.environ.get("ASSISTANT_ADMIN_TOKEN", "")
    try:
        address = ipaddress.ip_address(bind)
    except ValueError as exc:
        raise SystemExit("bind must be a WireGuard IPv4 address") from exc
    if (address.version != 4 or not address.is_private or address.is_loopback
            or min(len(agent_token), len(admin_token)) < 32 or agent_token == admin_token):
        raise SystemExit("set a private WireGuard bind address and two distinct 32+ character tokens")
    port = int(os.environ.get("ASSISTANT_RELAY_PORT", "8787"))
    state = State(os.environ.get("ASSISTANT_RELAY_DB", "relay.db"))
    ThreadingHTTPServer((bind, port), handler_factory(state, agent_token, admin_token)).serve_forever()


if __name__ == "__main__":
    main()
