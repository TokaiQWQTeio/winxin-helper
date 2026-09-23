"""Send through the verified WeChat window without moving the mouse cursor."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import time

from .ui_diagnostics import _wechat_pids
from .uia_preview import _class, _name, _walk, new_items, read_group


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def _idle_seconds() -> float:
    user32 = ctypes.windll.user32
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        raise RuntimeError("无法确认电脑是否空闲")
    return ((user32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


class UIASender:
    def __init__(self, allow_focus: bool = False, idle_seconds: float = 10, max_wait_seconds: float = 300):
        self.allow_focus = allow_focus
        self.idle_seconds = idle_seconds
        self.max_wait_seconds = max_wait_seconds

    def send(self, group: str, recipient: str, text: str) -> bool:
        """Send once, verify the new message, and never retry an uncertain send."""
        if not self.allow_focus:
            raise RuntimeError("可能切换焦点的发送方式未获启用")
        import uiautomation as uia

        deadline = time.monotonic() + self.max_wait_seconds
        while _idle_seconds() < self.idle_seconds:
            if time.monotonic() >= deadline:
                raise RuntimeError("等待电脑空闲超时，未发送")
            time.sleep(0.5)

        before = read_group(group)
        pids = _wechat_pids()
        user32 = ctypes.windll.user32
        previous_foreground = user32.GetForegroundWindow()
        for window in uia.GetRootControl().GetChildren():
            if window.ProcessId not in pids or window.NativeWindowHandle != before.hwnd:
                continue
            for page in _walk(window):
                if _class(page) != "mmui::ChatMessagePage":
                    continue
                title_bar = next((n for n in _walk(page) if _class(n) == "mmui::ChatTitleBarChatRoomView"), None)
                if title_bar is None or not any(
                    _class(n) == "mmui::XTextView" and _name(n) == group for n in _walk(title_bar)
                ):
                    continue
                editor = next((n for n in _walk(page) if _class(n) == "mmui::ChatInputField"), None)
                button = next((n for n in _walk(page) if _class(n) == "mmui::XOutlineButton" and _name(n) == "发送"), None)
                if editor is None or button is None:
                    raise RuntimeError("找不到群输入框或发送按钮")
                value = editor.GetValuePattern()
                if value.Value:
                    raise RuntimeError("输入框已有草稿，未发送")
                try:
                    if _idle_seconds() < self.idle_seconds or read_group(group).hwnd != before.hwnd:
                        raise RuntimeError("电脑不再空闲或群窗口已变化，未发送")
                    value.SetValue(text)
                    if value.Value != text or not button.IsEnabled or read_group(group).hwnd != before.hwnd:
                        raise RuntimeError("群或草稿变化，未发送")
                    if _idle_seconds() < self.idle_seconds:
                        raise RuntimeError("用户开始操作电脑，未发送")
                    box = button.BoundingRectangle
                    point = _Point((box.left + box.right) // 2, (box.top + box.bottom) // 2)
                    if not user32.ScreenToClient(wintypes.HWND(before.hwnd), ctypes.byref(point)):
                        raise RuntimeError("发送按钮坐标转换失败，未发送")
                    location = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
                    # This WeChat build accepted posted mouse messages in the test group.
                    # PostMessage does not move the real cursor, but WeChat may take focus.
                    accepted = (
                        user32.PostMessageW(wintypes.HWND(before.hwnd), 0x0200, 0, location),
                        user32.PostMessageW(wintypes.HWND(before.hwnd), 0x0201, 0x0001, location),
                        user32.PostMessageW(wintypes.HWND(before.hwnd), 0x0202, 0, location),
                    )
                    if not all(accepted):
                        return False
                    for _ in range(30):
                        time.sleep(0.3)
                        after = read_group(group)
                        if after.hwnd != before.hwnd:
                            return False
                        if not value.Value and any(
                            item.kind == "mmui::ChatTextItemView" and item.text == text
                            for item in new_items(before.items, after.items)
                        ):
                            return True
                    return False
                finally:
                    if value.Value == text:
                        value.SetValue("")
                    if previous_foreground and previous_foreground != before.hwnd:
                        user32.SetForegroundWindow(previous_foreground)
        raise RuntimeError("群窗口已变化，未发送")
