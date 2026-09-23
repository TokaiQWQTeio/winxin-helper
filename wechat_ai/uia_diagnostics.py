"""Inspect Windows UI Automation controls exposed by the WeChat desktop app.

This only queries accessibility controls; it does not read process memory or the
WeChat database. The resulting JSON may contain visible chat text.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys

from .ui_diagnostics import _wechat_pids


def capture(output_directory: str | Path = "data/diagnostics") -> tuple[Path, int]:
    if sys.platform != "win32":
        raise RuntimeError("仅支持 Windows")
    try:
        import uiautomation as uia
    except ImportError as exc:
        raise RuntimeError("请先安装免费依赖：pip install uiautomation") from exc
    pids = _wechat_pids()
    uia.SetGlobalSearchTimeout(1)
    root = uia.GetRootControl()
    found: list[dict] = []
    count = 0

    def walk(control, depth: int) -> dict:
        nonlocal count
        count += 1
        node: dict = {"depth": depth}
        for property_name in ("Name", "ClassName", "ControlTypeName", "ProcessId", "AutomationId"):
            try:
                node[property_name] = getattr(control, property_name)
            except Exception:
                node[property_name] = None
        try:
            node["RuntimeId"] = list(control.GetRuntimeId())
        except Exception:
            node["RuntimeId"] = None
        try:
            rect = control.BoundingRectangle
            node["BoundingRectangle"] = [rect.left, rect.top, rect.right, rect.bottom]
        except Exception:
            node["BoundingRectangle"] = None
        if depth < 30 and count < 1200:
            children = []
            try:
                for child in control.GetChildren():
                    if count >= 1200:
                        break
                    children.append(walk(child, depth + 1))
            except Exception as exc:
                node["children_error"] = type(exc).__name__
            node["children"] = children
        return node

    for child in root.GetChildren():
        try:
            if child.ProcessId in pids:
                found.append(walk(child, 0))
        except Exception:
            continue
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"uia-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, count
