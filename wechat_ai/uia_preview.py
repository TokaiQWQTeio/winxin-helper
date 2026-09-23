"""Read-only preview of new messages in one visible WeChat group window.

The UIA text for a real mention currently contains U+2005 after the nickname.
That marker is a candidate signal, not proof that the user selected a mention.
This module never calls the model or sends a WeChat message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unicodedata

from .ui_diagnostics import _wechat_pids


@dataclass(frozen=True)
class Item:
    kind: str
    text: str
    rect: tuple[int, int, int, int] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Snapshot:
    hwnd: int
    origin: tuple[int, int]
    items: tuple[Item, ...]
    session_preview: str = ""
    member_count: int | None = None


def new_items(previous: tuple[Item, ...], current: tuple[Item, ...]) -> tuple[Item, ...]:
    """Return appended items when the snapshots overlap; fail closed on a reset."""
    if not previous:
        return current
    for size in range(min(len(previous), len(current)), 0, -1):
        if previous[-size:] == current[:size]:
            return current[size:]
    return ()


def has_mention_marker(text: str, nickname: str) -> bool:
    return f"@{nickname}\u2005" in text


def _normalized(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def has_verified_mention(
    snapshot: Snapshot, item: Item, nickname: str, sender: str,
    *, visual_sender_confirmed: bool = False,
) -> bool:
    """Verify a selected @ using the badge, or OCR in chat-only layout."""
    if not has_mention_marker(item.text, nickname):
        return False
    if not snapshot.session_preview:
        return visual_sender_confirmed and bool(sender.strip())
    lines = snapshot.session_preview.splitlines()
    if "[有人@我]" not in lines:
        return False
    expected = _normalized(f"{sender}: {item.text}")
    return any(_normalized(line) == expected for line in lines)


def sender_from_session_preview(snapshot: Snapshot, item: Item, nickname: str) -> str | None:
    """Use WeChat's latest-message preview to name a verified @ sender."""
    if not has_mention_marker(item.text, nickname):
        return None
    lines = snapshot.session_preview.splitlines()
    if "[有人@我]" not in lines:
        return None
    for line in lines:
        if line.endswith(item.text):
            prefix = line[:-len(item.text)]
            if prefix.endswith(": ") and prefix[:-2].strip():
                return prefix[:-2].strip()
    return None


def _walk(control, depth: int = 0):
    if depth > 35:
        return
    yield control
    try:
        children = control.GetChildren()
    except Exception:
        return
    for child in children:
        yield from _walk(child, depth + 1)


def _class(control) -> str:
    try:
        return control.ClassName
    except Exception:
        return ""


def _name(control) -> str:
    try:
        return control.Name or ""
    except Exception:
        return ""


def _rect(control) -> tuple[int, int, int, int] | None:
    try:
        box = control.BoundingRectangle
        return box.left, box.top, box.right, box.bottom
    except Exception:
        return None


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR
    return RapidOCR()


def read_group(group: str) -> Snapshot:
    """Read the selected group's currently exposed UIA message list."""
    import uiautomation as uia

    pids = _wechat_pids()
    uia.SetGlobalSearchTimeout(1)
    root = uia.GetRootControl()
    for window in root.GetChildren():
        try:
            if window.ProcessId not in pids:
                continue
        except Exception:
            continue
        for page in _walk(window):
            if _class(page) != "mmui::ChatMessagePage":
                continue
            title_bar = next((node for node in _walk(page) if _class(node) == "mmui::ChatTitleBarChatRoomView"), None)
            if title_bar is None or not any(
                _class(node) == "mmui::XTextView" and _name(node) == group
                for node in _walk(title_bar)
            ):
                continue
            counts = [
                int(match.group(1))
                for node in _walk(title_bar)
                if _class(node) == "mmui::XTextView"
                if (match := re.fullmatch(r"\((\d+)\)", _name(node)))
            ]
            member_count = counts[0] if len(counts) == 1 and counts[0] > 0 else None
            message_list = next((node for node in _walk(page) if _class(node) == "mmui::RecyclerListView" and _name(node) == "消息"), None)
            if message_list is None:
                raise RuntimeError("已找到测试群，但消息列表不可读取")
            window_rect = _rect(window)
            if window_rect is None or not window.NativeWindowHandle:
                raise RuntimeError("无法获取微信窗口位置或句柄")
            items = tuple(
                Item(_class(node), _name(node), _rect(node))
                for node in message_list.GetChildren()
            )
            session_preview = next((
                _name(node) for node in _walk(window)
                if _class(node) == "mmui::ChatSessionCell"
                and _name(node).splitlines()[:1] == [group]
            ), "")
            return Snapshot(window.NativeWindowHandle, window_rect[:2], items, session_preview, member_count)
    raise RuntimeError(f"没有找到已打开的测试群窗口：{group}")


def identify_sender(snapshot: Snapshot, item: Item) -> str | None:
    """Read the sender label above a message via an occlusion-safe window frame."""
    if item.rect is None:
        return None
    from PIL import Image
    import numpy as np

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as output:
        path = Path(output.name)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "wechat_ai.wgc_capture", str(snapshot.hwnd), str(path)],
            capture_output=True, text=True, timeout=12, check=False,
        )
        if result.returncode or not path.exists() or path.stat().st_size == 0:
            return None
        with Image.open(path) as image:
            left, top, right, bottom = item.rect
            ox, oy = snapshot.origin
            box = (left - ox + 90, top - oy + 5, left - ox + 500, top - oy + 55)
            if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
                return None
            sender_crop = image.crop(box)
            message_box = (left - ox + 90, top - oy + 45, right - ox - 10, bottom - oy)
            if message_box[2] > image.width or message_box[3] > image.height:
                return None
            message_crop = image.crop(message_box)
        engine = _ocr_engine()
        message_scan = engine(np.asarray(message_crop))
        observed = "".join(message_scan.txts or [])
        expected = _normalized(item.text)
        if not observed:
            # Short bubbles are missed when surrounded by a large blank area.
            narrow = message_crop.crop((0, 0, min(240, message_crop.width), message_crop.height))
            narrow = narrow.resize((narrow.width * 2, narrow.height * 2))
            observed = "".join(engine(np.asarray(narrow)).txts or [])
        if not observed or SequenceMatcher(None, expected, _normalized(observed)).ratio() < 0.7:
            return None
        scan = engine(np.asarray(sender_crop))
        candidates = [
            text.strip() for text, score in zip(scan.txts or [], scan.scores or [])
            if score >= 0.85 and text.strip() and "@" not in text and len(text.strip()) <= 50
        ]
        if not candidates:
            narrow = sender_crop.crop((0, 0, min(200, sender_crop.width), sender_crop.height))
            narrow = narrow.resize((narrow.width * 2, narrow.height * 2))
            scan = engine(np.asarray(narrow))
            candidates = [
                text.strip() for text, score in zip(scan.txts or [], scan.scores or [])
                if score >= 0.85 and text.strip() and "@" not in text and len(text.strip()) <= 50
            ]
        return candidates[0] if len(candidates) == 1 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    finally:
        path.unlink(missing_ok=True)


def watch(group: str, nickname: str, interval: float = 2.0) -> None:
    """Print only new text items; never send or call a model."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    previous = read_group(group)
    print(f"只读监听已启动：{group}；当前 {len(previous.items)} 条可见项作为基线，不处理旧消息。", flush=True)
    while True:
        time.sleep(interval)
        current = read_group(group)
        for item in new_items(previous.items, current.items):
            if item.kind != "mmui::ChatTextItemView":
                continue
            is_candidate = has_mention_marker(item.text, nickname)
            status = "候选 @" if is_candidate else "普通消息"
            sender = identify_sender(current, item) if is_candidate else None
            if sender and has_verified_mention(current, item, nickname, sender, visual_sender_confirmed=True):
                status = "已确认 @"
            print(f"{status}（发送者：{sender or '未确认'}）: {item.text}", flush=True)
        previous = current
