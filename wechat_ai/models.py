from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class GroupMessage:
    group: str
    sender: str
    text: str
    source_id: str
    received_at: datetime
    is_self: bool = False
    mention_verified: bool = False
    group_member_count: int | None = None

    def validate(self) -> None:
        if not self.group or not self.sender or not self.source_id:
            raise ValueError("消息缺少群、发送者或稳定的来源标识")
        if self.received_at.tzinfo is None:
            raise ValueError("received_at 必须带时区")
        if self.group_member_count is not None and self.group_member_count < 1:
            raise ValueError("群成员总数必须为正数")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
