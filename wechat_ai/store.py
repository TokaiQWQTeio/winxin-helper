from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3

from .models import GroupMessage, utcnow


class Store:
    def __init__(self, path: str | Path):
        database = Path(path)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(database, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                group_name TEXT NOT NULL,
                source_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                body TEXT NOT NULL,
                received_at TEXT NOT NULL,
                is_self INTEGER NOT NULL,
                mention_verified INTEGER NOT NULL,
                UNIQUE(group_name, source_id)
            );
            CREATE INDEX IF NOT EXISTS messages_group_time
                ON messages(group_name, id);
            CREATE TABLE IF NOT EXISTS summaries (
                group_name TEXT PRIMARY KEY,
                body TEXT NOT NULL,
                through_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                group_name TEXT NOT NULL,
                source_id TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(group_name, source_id)
            );
            CREATE TABLE IF NOT EXISTS history_imports (
                group_name TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                requested_since TEXT NOT NULL,
                oldest_visible TEXT,
                newest_visible TEXT,
                scanned_count INTEGER NOT NULL DEFAULT 0,
                gap_note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        self.conn.close()

    def save_message(self, message: GroupMessage) -> bool:
        message.validate()
        with self.conn:
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO messages
                   (group_name, source_id, sender, body, received_at,
                    is_self, mention_verified) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (message.group, message.source_id, message.sender, message.text,
                 message.received_at.astimezone(timezone.utc).isoformat(),
                 int(message.is_self), int(message.mention_verified)),
            )
        return cursor.rowcount == 1

    def request_history(self, group: str, days: int = 30) -> None:
        if not group.strip() or days != 30:
            raise ValueError("历史导入只支持已命名群最近 30 天")
        since = (utcnow() - timedelta(days=days)).isoformat()
        with self.conn:
            self.conn.execute(
                """INSERT INTO history_imports(group_name,status,requested_since,updated_at)
                   VALUES (?, 'paused', ?, ?)
                   ON CONFLICT(group_name) DO UPDATE SET status='paused',
                     requested_since=excluded.requested_since, updated_at=excluded.updated_at""",
                (group, since, utcnow().isoformat()),
            )

    def history_state(self, group: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM history_imports WHERE group_name=?", (group,)
        ).fetchone()
        return dict(row) if row else None

    def set_history_status(self, group: str, status: str) -> None:
        if status not in {"paused", "running", "complete", "needs_review"}:
            raise ValueError("无效历史任务状态")
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE history_imports SET status=?,updated_at=? WHERE group_name=?",
                (status, utcnow().isoformat(), group),
            )
        if not cursor.rowcount:
            raise ValueError("历史任务不存在")

    def record_history_batch(self, group: str, messages: list[GroupMessage], *,
                             complete: bool = False, gap_note: str = "") -> int:
        """Persist a read-only page; historical mentions never enter deliveries."""
        state = self.history_state(group)
        if state is None or state["status"] != "running":
            raise ValueError("历史任务没有运行")
        since = datetime.fromisoformat(state["requested_since"])
        for message in messages:
            message.validate()
            if message.group != group:
                raise ValueError("历史批次群名不匹配")
        valid = [m for m in messages if m.received_at >= since]
        with self.conn:
            added = 0
            for message in valid:
                cursor = self.conn.execute(
                    """INSERT OR IGNORE INTO messages
                       (group_name,source_id,sender,body,received_at,is_self,mention_verified)
                       VALUES (?,?,?,?,?,?,0)""",
                    (group, message.source_id, message.sender, message.text,
                     message.received_at.astimezone(timezone.utc).isoformat(),
                     int(message.is_self)),
                )
                added += cursor.rowcount
            dates = [m.received_at.astimezone(timezone.utc).isoformat() for m in valid]
            oldest = min(([state["oldest_visible"]] if state["oldest_visible"] else []) + dates, default=None)
            newest = max(([state["newest_visible"]] if state["newest_visible"] else []) + dates, default=None)
            self.conn.execute(
                """UPDATE history_imports SET status=?,oldest_visible=?,newest_visible=?,
                   scanned_count=scanned_count+?,gap_note=?,updated_at=? WHERE group_name=?""",
                ("complete" if complete else "running", oldest, newest, added,
                 gap_note, utcnow().isoformat(), group),
            )
        return added

    def recent(self, group: str, limit: int) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            """SELECT sender, body, received_at FROM messages
               WHERE group_name=? ORDER BY received_at DESC, id DESC LIMIT ?""", (group, limit)
        ).fetchall()
        return list(reversed(rows))

    def relevant_history(self, group: str, query: str, limit: int = 5) -> list[sqlite3.Row]:
        """Small local lexical search, scoped to one group and older than recent chat."""
        words = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query.casefold())
        terms = {word[i:i+2] for word in words for i in range(max(0, len(word)-1))}
        if not terms:
            return []
        recent_ids = {row[0] for row in self.conn.execute(
            "SELECT id FROM messages WHERE group_name=? ORDER BY received_at DESC,id DESC LIMIT 50",
            (group,),
        )}
        rows = self.conn.execute(
            """SELECT id,sender,body,received_at FROM messages
               WHERE group_name=? ORDER BY received_at DESC,id DESC LIMIT 500""", (group,)
        ).fetchall()
        ranked = []
        for row in rows:
            if row["id"] in recent_ids:
                continue
            body = row["body"].casefold()
            score = sum(term in body for term in terms)
            if score:
                ranked.append((score, row))
        ranked.sort(key=lambda pair: (pair[0], pair[1]["received_at"]), reverse=True)
        return [row for _, row in ranked[:limit]]

    def summary(self, group: str) -> tuple[str, int]:
        row = self.conn.execute(
            "SELECT body, through_id FROM summaries WHERE group_name=?", (group,)
        ).fetchone()
        return (row["body"], row["through_id"]) if row else ("", 0)

    def pending_summary(self, group: str) -> list[sqlite3.Row]:
        _, through_id = self.summary(group)
        return self.conn.execute(
            """SELECT id, sender, body, received_at FROM messages
               WHERE group_name=? AND id>? ORDER BY id""", (group, through_id)
        ).fetchall()

    def save_summary(self, group: str, body: str, through_id: int) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO summaries(group_name, body, through_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(group_name) DO UPDATE SET
                     body=excluded.body, through_id=excluded.through_id,
                     updated_at=excluded.updated_at
                   WHERE excluded.through_id > summaries.through_id""",
                (group, body, through_id, utcnow().isoformat()),
            )

    def clear_summary(self, group: str) -> None:
        latest = self.conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM messages WHERE group_name=?", (group,)
        ).fetchone()[0]
        with self.conn:
            self.conn.execute(
                """INSERT INTO summaries(group_name, body, through_id, updated_at)
                   VALUES (?, '', ?, ?)
                   ON CONFLICT(group_name) DO UPDATE SET
                     body='', through_id=excluded.through_id,
                     updated_at=excluded.updated_at""",
                (group, latest, utcnow().isoformat()),
            )

    def begin_delivery(self, group: str, source_id: str) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO deliveries
                   (group_name, source_id, status, updated_at)
                   VALUES (?, ?, 'started', ?)""",
                (group, source_id, utcnow().isoformat()),
            )
        return cursor.rowcount == 1

    def finish_delivery(self, group: str, source_id: str, status: str, error: str = "") -> None:
        if status not in {"sent", "skipped", "failed", "uncertain"}:
            raise ValueError("invalid delivery status")
        with self.conn:
            self.conn.execute(
                """UPDATE deliveries SET status=?, error=?, updated_at=?
                   WHERE group_name=? AND source_id=?""",
                (status, error[:500], utcnow().isoformat(), group, source_id),
            )

    def purge_raw(self, days: int) -> int:
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM messages WHERE received_at < ?", (cutoff,)
            )
        return cursor.rowcount

    def raw_expiring_groups(self, days: int) -> list[str]:
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        return [row[0] for row in self.conn.execute(
            """SELECT DISTINCT m.group_name FROM messages m
               LEFT JOIN summaries s ON s.group_name=m.group_name
               WHERE m.received_at < ? AND m.id > COALESCE(s.through_id, 0)""",
            (cutoff,),
        )]
