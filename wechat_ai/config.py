from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    bot_name: str
    groups: tuple[str, ...]
    api_base_url: str
    model: str
    api_key_env: str = "WECHAT_AI_API_KEY"
    database_path: str = "data/assistant.db"
    auto_send_enabled: bool = False
    focus_send_enabled: bool = False
    recent_message_limit: int = 50
    raw_retention_days: int = 30
    summary_batch_size: int = 20
    enabled_groups: tuple[str, ...] | None = None
    dedicated_vm: bool = False

    @property
    def active_groups(self) -> tuple[str, ...]:
        # Legacy configs keep their existing groups enabled until explicitly edited.
        return self.groups if self.enabled_groups is None else self.enabled_groups

    @property
    def is_local_model(self) -> bool:
        parsed = urlparse(self.api_base_url)
        return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("配置文件必须是 JSON 对象")
        config = cls(
            bot_name=str(raw["bot_name"]).strip(),
            groups=tuple(str(group).strip() for group in raw["groups"]),
            api_base_url=str(raw["api_base_url"]).rstrip("/"),
            model=str(raw["model"]).strip(),
            api_key_env=str(raw.get("api_key_env", "WECHAT_AI_API_KEY")),
            database_path=str(raw.get("database_path", "data/assistant.db")),
            auto_send_enabled=raw.get("auto_send_enabled", False),
            focus_send_enabled=raw.get("focus_send_enabled", False),
            recent_message_limit=raw.get("recent_message_limit", 50),
            raw_retention_days=raw.get("raw_retention_days", 30),
            summary_batch_size=raw.get("summary_batch_size", 20),
            enabled_groups=(tuple(str(group).strip() for group in raw["enabled_groups"])
                            if "enabled_groups" in raw else None),
            dedicated_vm=raw.get("dedicated_vm", False),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.bot_name or not self.groups or any(not group for group in self.groups):
            raise ValueError("需要填写 bot_name 和至少一个群名")
        if len(set(self.groups)) != len(self.groups):
            raise ValueError("群名不能重复")
        if len({group.casefold() for group in self.groups}) != len(self.groups):
            raise ValueError("群名不能仅大小写不同")
        if self.enabled_groups is not None and (
            len(set(self.enabled_groups)) != len(self.enabled_groups)
            or any(group not in self.groups for group in self.enabled_groups)
        ):
            raise ValueError("启用群必须是已添加的群，且不能重复")
        if not self.model or not self.api_key_env:
            raise ValueError("需要填写模型名称和 API 密钥环境变量名")
        parsed = urlparse(self.api_base_url)
        if (parsed.scheme != "https" and not self.is_local_model) or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("api_base_url 必须是 HTTPS 地址或本机 localhost HTTP 地址，且不能包含账号密码")
        if not isinstance(self.auto_send_enabled, bool):
            raise ValueError("auto_send_enabled 必须为布尔值")
        if not isinstance(self.focus_send_enabled, bool):
            raise ValueError("focus_send_enabled 必须为布尔值")
        if not isinstance(self.dedicated_vm, bool):
            raise ValueError("dedicated_vm 必须为布尔值")
        for field in ("recent_message_limit", "raw_retention_days", "summary_batch_size"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field} 必须是正整数")
