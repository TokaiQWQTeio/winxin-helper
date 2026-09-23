from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import importlib.util
import json
import logging
from pathlib import Path
import subprocess
import sys

from .config import Config
from .models import GroupMessage
from .service import Assistant
from .store import Store


class PreviewModel:
    def complete(self, system: str, user: str) -> str:
        return "[预览] 已收到问题。此命令不调用真实模型。"


class PreviewSender:
    def send(self, group: str, recipient: str, text: str) -> bool:
        print(json.dumps({"group": group, "at": recipient, "reply": text}, ensure_ascii=False))
        return True


def probe() -> int:
    if sys.platform != "win32":
        print("此程序的微信接入验证需要 Windows。")
        return 1
    command = (
        "Get-Process Weixin,WeChat -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 ProcessName,Path,ProductVersion | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, check=False, timeout=10,
    )
    data = json.loads(result.stdout) if result.stdout.strip() else None
    print(json.dumps({
        "wechat_process": data,
        "python": sys.version.split()[0],
        "pillow_installed": importlib.util.find_spec("PIL") is not None,
        "rapidocr_installed": importlib.util.find_spec("rapidocr") is not None,
        "true_mention_detection_certified": False,
        "send_tested_in_two_person_group": True,
        "auto_send_available": False,
    }, ensure_ascii=False, indent=2))
    print("测试群已验证固定消息发送；多人群识别和完整问答流程仍待验证，自动发送保持关闭。")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="个人微信群 AI 助手")
    parser.add_argument("--config", default="config.json", help="JSON 配置路径")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("probe", help="只读检查微信和接入状态")
    commands.add_parser("capture-ui", help="截取当前微信窗口并离线 OCR；可能包含聊天内容")
    commands.add_parser("probe-uia", help="读取微信可访问性控件树；可能包含聊天内容")
    commands.add_parser("watch-preview", help="只读预览测试群新消息；不会调用模型或发送消息")
    commands.add_parser("watch-model-preview", help="真正 @ 后生成并打印模型回复；绝不发送微信消息")
    commands.add_parser("run", help="实时监听白名单群并回复；必须通过配置启用")
    commands.add_parser("run-once", help="只处理下一条合格 @ 并退出；会向当前唯一白名单群发送一次")
    commands.add_parser("check-config", help="检查配置")
    commands.add_parser("test-model", help="离线测试已配置模型；不读取或发送微信消息")
    simulation = commands.add_parser("simulate", help="用 JSONL 离线演练消息处理；绝不发送微信消息")
    simulation.add_argument("events", type=Path)
    summary = commands.add_parser("clear-summary", help="清除某个群的长期摘要")
    summary.add_argument("group")
    commands.add_parser("maintenance", help="总结待处理消息后清理过期原文")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "probe":
        return probe()
    if args.command == "capture-ui":
        from .ui_diagnostics import capture
        try:
            screenshot, records = capture()
        except RuntimeError as exc:
            parser.error(str(exc))
        print(f"截图：{screenshot}\nOCR 结果：{records}")
        print("这些文件可能包含聊天内容，仅保存在本机 data/diagnostics，不会提交到 Git。")
        return 0
    if args.command == "probe-uia":
        from .uia_diagnostics import capture
        try:
            path, count = capture()
        except RuntimeError as exc:
            parser.error(str(exc))
        print(f"控件数：{count}；结果：{path}")
        print("结果可能包含可见聊天内容，仅保存在本机忽略目录。")
        return 0 if count else 2
    try:
        config = Config.load(args.config)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"配置错误：{exc}")
    if args.command == "check-config":
        print("配置有效；自动发送：" + ("已启用（实验性）" if config.auto_send_enabled else "关闭"))
        return 0
    if args.command == "test-model":
        from .llm import ChatModel, ModelError
        try:
            reply = ChatModel(config).complete("请用一句简短中文回答。", "你好，请介绍一下自己。")
        except ModelError as exc:
            parser.error(str(exc))
        print(reply)
        return 0
    if args.command == "watch-preview":
        from .uia_preview import watch
        try:
            watch(config.groups[0], config.bot_name)
        except KeyboardInterrupt:
            print("已停止只读监听")
        except RuntimeError as exc:
            parser.error(str(exc))
        return 0
    if args.command == "watch-model-preview":
        from .uia_model_preview import watch_model
        try:
            watch_model(config)
        except KeyboardInterrupt:
            print("已停止问答预览")
        except RuntimeError as exc:
            parser.error(str(exc))
        return 0
    if args.command in {"run", "run-once"}:
        from .uia_live import run
        try:
            run(config, one_shot=args.command == "run-once")
        except KeyboardInterrupt:
            print("已停止实时监听")
        except RuntimeError as exc:
            parser.error(str(exc))
        return 0
    if args.command == "simulate":
        # A preview is isolated from the production database and never calls the cloud API.
        preview = replace(config, auto_send_enabled=True)
        store = Store(":memory:")
        assistant = Assistant(preview, store, PreviewModel(), PreviewSender())
        try:
            for line_no, line in enumerate(args.events.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                raw = json.loads(line)
                event = GroupMessage(
                    group=raw["group"], sender=raw["sender"], text=raw["text"],
                    source_id=raw["source_id"],
                    received_at=datetime.fromisoformat(raw["received_at"]),
                    is_self=raw.get("is_self", False),
                    mention_verified=raw.get("mention_verified", False),
                )
                print(f"第 {line_no} 行：{assistant.ingest(event)}")
        finally:
            store.close()
        return 0
    store = Store(config.database_path)
    try:
        if args.command == "clear-summary":
            if args.group not in config.groups:
                parser.error("群不在白名单")
            store.clear_summary(args.group)
            print("已清除摘要：" + args.group)
        elif args.command == "maintenance":
            from .llm import ChatModel
            assistant = Assistant(config, store, ChatModel(config), PreviewSender())
            count = assistant.maintenance()
            print(f"已删除 {count} 条过期原文")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
