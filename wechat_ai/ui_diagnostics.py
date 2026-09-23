"""Read-only, UI-only snapshot of the visible WeChat window for compatibility testing.

This module does not read the WeChat database or process memory. It deliberately
does not infer a real @ mention from OCR text alone.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys


def _wechat_pids() -> set[int]:
    command = (
        "Get-Process Weixin,WeChat -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty Id"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if not result.stdout.strip():
        raise RuntimeError("未找到正在运行的微信客户端")
    return {int(line.strip()) for line in result.stdout.splitlines() if line.strip()}


def _visible_window_rect(pids: set[int]) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    rectangles: list[tuple[int, int, int, int]] = []

    def visit(hwnd: int, _: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value not in pids or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            box = (rect.left, rect.top, rect.right, rect.bottom)
            if (box[2] - box[0]) >= 400 and (box[3] - box[1]) >= 300:
                rectangles.append(box)
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    if not rectangles:
        raise RuntimeError("微信窗口未显示；请先恢复窗口")
    return max(rectangles, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))


def capture(output_directory: str | Path = "data/diagnostics") -> tuple[Path, Path]:
    if sys.platform != "win32":
        raise RuntimeError("仅支持 Windows")
    try:
        from PIL import ImageGrab
        import numpy as np
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError("请先安装免费依赖：pip install pillow rapidocr onnxruntime") from exc

    box = _visible_window_rect(_wechat_pids())
    image = ImageGrab.grab(bbox=box, all_screens=True)
    result = RapidOCR()(np.asarray(image))
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    screenshot = output / f"wechat-{timestamp}.png"
    records = output / f"wechat-{timestamp}.json"
    image.save(screenshot)
    boxes = result.boxes if result.boxes is not None else []
    texts = result.txts if result.txts is not None else []
    scores = result.scores if result.scores is not None else []
    blocks = [
        {"box": box.tolist(), "text": text, "score": float(score)}
        for box, text, score in zip(boxes, texts, scores)
    ]
    records.write_text(
        json.dumps({"window_rect": box, "blocks": blocks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return screenshot, records
