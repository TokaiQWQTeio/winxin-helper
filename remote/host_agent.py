"""Run on the Windows host; relay only status and control metadata."""
from __future__ import annotations

import ipaddress
import json
import os
import time
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen

from wechat_ai.web_control import Controller


def relay_url() -> str:
    url = os.environ.get("ASSISTANT_RELAY_URL", "")
    parsed = urlparse(url)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise RuntimeError("relay URL must use a WireGuard IP address") from exc
    if parsed.scheme != "http" or not address.is_private or address.is_loopback or parsed.path not in {"", "/"}:
        raise RuntimeError("relay URL must use a private WireGuard HTTP address")
    return url.rstrip("/")


class RelayClient:
    def __init__(self, url: str, token: str, agent_id: str):
        if len(token) < 32 or not agent_id:
            raise ValueError("missing relay credentials")
        self.url, self.token, self.agent_id = url, token, agent_id

    def call(self, path: str, data: dict | None = None):
        target = self.url + path
        if data is None:
            target += "?" + urlencode({"agent_id": self.agent_id})
        else:
            data = {"agent_id": self.agent_id, **data}
        request = Request(
            target,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)


def run() -> None:
    client = RelayClient(relay_url(), os.environ.get("ASSISTANT_AGENT_TOKEN", ""),
                         os.environ.get("ASSISTANT_AGENT_ID", "home-pc"))
    controller = Controller()
    while True:
        try:
            status = controller.status()
            client.call("/heartbeat", {"running": status["running"],
                                       "task_state": "running" if status["running"] else "idle"})
            for command in client.call("/commands"):
                outcome = "done"
                try:
                    if command["action"] in {"start", "resume"}:
                        controller.start({"accept_focus": True})
                    elif command["action"] in {"stop", "pause"}:
                        controller.stop()
                    else:
                        raise ValueError("invalid action")
                except Exception:
                    outcome = "failed"
                client.call("/ack", {"id": command["id"], "state": outcome})
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"relay unavailable: {exc}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    run()
