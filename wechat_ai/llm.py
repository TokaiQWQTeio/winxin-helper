from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config


class ModelError(RuntimeError):
    pass


class ChatModel:
    def __init__(self, config: Config):
        self.config = config

    def complete(self, system: str, user: str) -> str:
        local = self.config.is_local_model
        key = os.environ.get(self.config.api_key_env)
        if not local and not key:
            raise ModelError(f"缺少环境变量 {self.config.api_key_env}")
        payload = json.dumps({
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if not local:
            headers["Authorization"] = "Bearer " + key
        request = Request(
            self.config.api_base_url + "/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            # A local model can need extra time for its first GPU load.
            with urlopen(request, timeout=180 if local else 40) as response:
                data = json.load(response)
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ModelError("模型返回空回复")
            return content.strip()
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
            raise ModelError(f"模型请求失败：{type(exc).__name__}") from exc
