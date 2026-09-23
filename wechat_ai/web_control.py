"""Local-only control panel for the WeChat assistant."""
from __future__ import annotations

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import webbrowser
from urllib.error import URLError
from urllib.request import urlopen

from .config import Config


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
PID_PATH = ROOT / "data" / "bot.pid"
STATIC = ROOT / "web"
BOT_ERROR_LOG = ROOT / "data" / "bot.stderr.log"


def _powershell_env() -> dict[str, str]:
    # Windows PowerShell's Start-Process rejects an inherited PATH/Path pair.
    # Keep one canonical spelling when the control page launches PowerShell.
    environment = dict(os.environ)
    path_keys = [key for key in environment if key.casefold() == "path"]
    if path_keys:
        path_value = environment[path_keys[-1]]
        for key in path_keys:
            del environment[key]
        environment["Path"] = path_value
    return environment


def _process():
    if not PID_PATH.exists():
        return None
    try:
        import psutil
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
        process = psutil.Process(pid)
        command = process.cmdline()
        expected = ROOT / ".venv" / "Scripts" / "python.exe"
        if (not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
                or Path(process.exe()).resolve() != expected.resolve()
                or "-m" not in command or "wechat_ai" not in command
                or "run" not in command):
            return None
        return process
    except Exception:
        return None


def _save_config(config: Config) -> None:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raw.update({
        "api_base_url": config.api_base_url,
        "model": config.model,
        "api_key_env": config.api_key_env,
        "auto_send_enabled": config.auto_send_enabled,
        "focus_send_enabled": config.focus_send_enabled,
    })
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


def _local_model_status(config: Config) -> str:
    if not config.is_local_model:
        return "已设置密钥环境变量" if os.environ.get(config.api_key_env) else f"缺少环境变量 {config.api_key_env}"
    try:
        with urlopen("http://127.0.0.1:11434/api/version", timeout=1) as response:
            return "Ollama 已运行" if response.status == 200 else "Ollama 未就绪"
    except (OSError, URLError):
        return "Ollama 未运行，启动助手时会尝试启动"


def _bot_start_error() -> str:
    try:
        lines = BOT_ERROR_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines[-30:]):
            if "__main__.py: error:" in line:
                return line.split("error:", 1)[1].strip()
    except OSError:
        pass
    return "请查看 data/bot.stderr.log"


def _require_visible_wechat(groups: tuple[str, ...]) -> None:
    if not _wechat_window_visible():
        raise ValueError("微信已缩到托盘或未打开；请恢复微信窗口并打开 " + "、".join(groups) + " 群。窗口可以放在其他程序后面。")


def _wechat_window_visible() -> bool:
    if sys.platform != "win32":
        return False
    from .ui_diagnostics import _visible_window_rect, _wechat_pids

    try:
        _visible_window_rect(_wechat_pids())
        return True
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return False


def _target_group_readable(groups: tuple[str, ...]) -> bool:
    """Require the group messages and session preview used to verify real @."""
    try:
        from .uia_preview import read_group
        return all(bool(read_group(group).session_preview) for group in groups)
    except Exception:
        return False


class Controller:
    def __init__(self):
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)

    def status(self) -> dict:
        with self.lock:
            config = Config.load(CONFIG_PATH)
            process = _process()
            visible = _wechat_window_visible()
            return {
                "running": process is not None,
                "wechat_window_visible": visible,
                "target_group_readable": bool(process and visible and _target_group_readable(config.groups)),
                "pid": process.pid if process else None,
                "bot_name": config.bot_name,
                "groups": list(config.groups),
                "api_base_url": config.api_base_url,
                "model": config.model,
                "api_key_env": config.api_key_env,
                "is_local_model": config.is_local_model,
                "model_status": _local_model_status(config),
                "focus_warning": "发送时微信可能短暂获得焦点；程序不移动鼠标。",
            }

    def save_model(self, payload: dict) -> dict:
        with self.lock:
            if _process():
                raise ValueError("请先停止助手，再切换模型")
            config = Config.load(CONFIG_PATH)
            provider = payload.get("provider")
            if provider == "local":
                updated = replace(config, api_base_url="http://127.0.0.1:11434/v1", model="deepseek-r1:8b")
            elif provider == "api":
                url = payload.get("api_base_url")
                model = payload.get("model")
                env = payload.get("api_key_env")
                if not all(isinstance(x, str) and 0 < len(x) <= 200 for x in (url, model, env)):
                    raise ValueError("请填写 API 地址、模型名称和密钥环境变量名")
                if not env.isidentifier():
                    raise ValueError("密钥环境变量名无效")
                updated = replace(config, api_base_url=url.strip().rstrip("/"), model=model.strip(), api_key_env=env.strip())
                if updated.is_local_model:
                    raise ValueError("自定义 API 请使用 HTTPS 地址")
            else:
                raise ValueError("未知模型类型")
            updated.validate()
            _save_config(replace(updated, auto_send_enabled=False, focus_send_enabled=False))
            return self.status()

    def start(self, payload: dict) -> dict:
        with self.lock:
            if payload.get("accept_focus") is not True:
                raise ValueError("请先确认微信可能短暂获得焦点")
            if _process():
                return self.status()
            config = Config.load(CONFIG_PATH)
            _require_visible_wechat(config.groups)
            if not _target_group_readable(config.groups):
                raise ValueError("请在微信主窗口打开 " + "、".join(config.groups) + " 群，并保持左侧会话列表可见；当前无法核实真正的 @")
            if not config.is_local_model and not os.environ.get(config.api_key_env):
                raise ValueError(f"缺少环境变量 {config.api_key_env}；请在启动控制页前设置")
            if config.is_local_model:
                script = ROOT / "scripts" / "start-local-model.ps1"
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                    env=_powershell_env(),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode:
                    raise RuntimeError("本地模型启动失败；请检查 Ollama 是否正常运行")
            _save_config(replace(config, auto_send_enabled=True, focus_send_enabled=True))
            script = ROOT / "scripts" / "start-bot.ps1"
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45,
                    env=_powershell_env(),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode or not _process():
                    raise RuntimeError("助手启动失败：" + _bot_start_error())
            except Exception:
                self.stop()
                raise
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            config = Config.load(CONFIG_PATH)
            process = _process()
            if process:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
                    process.wait(timeout=5)
                PID_PATH.unlink(missing_ok=True)
            _save_config(replace(config, auto_send_enabled=False, focus_send_enabled=False))
            return self.status()


class Handler(BaseHTTPRequestHandler):
    controller: Controller

    def _json(self, code: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _valid_host(self) -> bool:
        return self.headers.get("Host", "").split(":")[0] in {"127.0.0.1", "localhost"}

    def do_GET(self) -> None:
        if not self._valid_host():
            self.send_error(403)
            return
        if self.path == "/api/status":
            self._json(200, self.controller.status())
            return
        names = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
        if self.path not in names:
            self.send_error(404)
            return
        file, mime = names[self.path]
        body = (STATIC / file).read_bytes()
        if file == "index.html":
            body = body.replace(b"__CONTROL_TOKEN__", self.controller.token.encode("ascii"))
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._valid_host() or self.headers.get("X-Control-Token") != self.controller.token:
            self.send_error(403)
            return
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 4096:
                raise ValueError("请求内容过长")
            payload = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(payload, dict):
                raise ValueError("请求格式错误")
            if self.path == "/api/start":
                result = self.controller.start(payload)
            elif self.path == "/api/stop":
                result = self.controller.stop()
            elif self.path == "/api/model":
                result = self.controller.save_model(payload)
            else:
                self.send_error(404)
                return
            self._json(200, result)
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("控制页仅支持 Windows")
    Config.load(CONFIG_PATH)
    Handler.controller = Controller()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("控制页：http://127.0.0.1:8765", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open("http://127.0.0.1:8765")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
