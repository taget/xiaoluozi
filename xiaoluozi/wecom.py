"""Call the official wecom-cli. Arguments stay in argv, never a shell."""

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from xiaoluozi.connectors import load_connector
from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.wecom")

CATEGORIES = (
    "contact",
    "calendar",
    "meeting",
    "todo",
    "email",
    "disk",
    "media",
    "message",
    "doc-manage",
    "doc",
    "sheet",
    "smartsheet",
    "smartpage",
    "pptx",
    "identity",
)
_TIMEOUT = 60
_LIMIT = 12000
_ARGS_LIMIT = 32000
_TOKEN = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")

_TIMEOUT_TEXT = "企业微信 CLI 超时。"
_FAILED = "企业微信 CLI 没有完成。"


class _Reject(Exception):
    pass


def gate(*, run=None, which=None) -> str:
    """Empty when the CLI can be used. Otherwise the sentence to show the user, not the model."""
    connector = load_connector("wecom")
    binary = _binary(which, connector.version_argv[0])
    if not binary:
        return _missing(connector)
    return _preflight(binary, run or _run, connector)


def is_gate(text: str) -> bool:
    return text.startswith("企业微信还没授权。") or text.startswith("企业微信 CLI 还没装好。")


def run_wecom(arguments: str, *, run=None, which=None) -> str:
    """Run one official CLI action. Business calls check version and auth first."""
    payload, error = _payload(arguments)
    if error:
        return error
    connector = load_connector("wecom")
    binary = _binary(which, connector.version_argv[0])
    if not binary:
        return _missing(connector)
    runner = run or _run
    try:
        argv, preflight = _plan(binary, payload, connector)
    except _Reject as exc:
        return str(exc)
    if preflight:
        problem = _preflight(binary, runner, connector)
        if problem:
            return problem
    _log(argv)
    return _finish(_call(runner, argv))


def _payload(arguments: str) -> tuple[dict | None, str]:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return None, "参数不是 JSON。"
    if not isinstance(payload, dict):
        return None, "参数要是 JSON 对象。"
    return payload, ""


def _binary(which, name: str) -> str:
    finder = which or shutil.which
    found = finder(name)
    return found.strip() if isinstance(found, str) else ""


def _using(binary: str, argv: tuple[str, ...]) -> list[str]:
    return [binary, *argv[1:]]


def _missing(connector) -> str:
    return f"企业微信 CLI 还没装好。先执行 {connector.init_command}。"


_UNAUTHORIZED = (
    "企业微信还没授权。在终端执行 wecom-cli auth init，用企业微信扫码。"
    "扫码不便时执行 wecom-cli auth init --manual，填长连接机器人的 Bot ID 和 Secret。"
    "然后执行 wecom-cli auth show，看到 authorized 再继续。"
    "这不是自建应用，不要 corp_id、agent_id 或应用密钥。"
)


def _plan(binary: str, payload: dict, connector) -> tuple[list[str], bool]:
    action = payload.get("action")
    if action is not None:
        if not isinstance(action, str):
            raise _Reject("没有这个操作。")
        if action == "version":
            return _using(binary, connector.version_argv), False
        if action == "auth":
            return _using(binary, connector.status_argv), False
        raise _Reject("没有这个操作。")
    if payload.get("help") is True:
        category = payload.get("category")
        if category in (None, ""):
            return [binary, "--help"], False
        _category(category)
        return [binary, category, "--help"], True
    if "category" not in payload:
        raise _Reject("要写企业微信品类。")
    category = _category(payload.get("category"))
    if "command" not in payload:
        raise _Reject("要写子命令。")
    tokens = _tokens(payload.get("command"))
    argv = [binary, category, *tokens]
    if "args" in payload and payload.get("args") is not None:
        args = payload.get("args")
        if not isinstance(args, dict):
            raise _Reject("命令参数要是 JSON 对象。")
        encoded = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > _ARGS_LIMIT:
            raise _Reject("企业微信命令参数太长。")
        argv.extend(["--json", encoded])
    return argv, True


def _category(value) -> str:
    if not isinstance(value, str) or value not in CATEGORIES:
        listed = "、".join(CATEGORIES)
        raise _Reject(f"没有这个企业微信品类。可选：{listed}。")
    return value


def _tokens(command) -> list[str]:
    if isinstance(command, str):
        parts = command.split()
    elif isinstance(command, list):
        parts = []
        for item in command:
            if not isinstance(item, str):
                raise _Reject("命令不合法。")
            parts.append(item)
    else:
        raise _Reject("命令不合法。")
    if not parts or any(_TOKEN.fullmatch(part) is None for part in parts):
        raise _Reject("命令不合法。")
    return parts


def _preflight(binary: str, runner, connector) -> str:
    version = _call(runner, _using(binary, connector.version_argv))
    if version.error == "timeout":
        return _TIMEOUT_TEXT
    if version.error == "missing":
        return _missing(connector)
    if version.returncode != 0:
        return _body(version) or _FAILED
    parsed = _parse_version(version.stdout)
    if parsed is None:
        return "看不出企业微信 CLI 的版本。"
    if parsed < connector.min_version:
        shown = ".".join(str(part) for part in parsed)
        need = ".".join(str(part) for part in connector.min_version)
        return f"企业微信 CLI 版本是 {shown}，需要不低于 {need}。先执行 {connector.init_command}。"
    auth = _call(runner, _using(binary, connector.status_argv))
    if auth.error == "timeout":
        return _TIMEOUT_TEXT
    if auth.error == "missing":
        return _missing(connector)
    if auth.returncode == 0 and connector.authorized(auth.stdout or ""):
        return ""
    if re.search(r"\bunauthorized\b", auth.stdout or ""):
        return _UNAUTHORIZED
    body = _body(auth)
    if body:
        return f"企业微信授权状态看不清。\n{body}"
    return "企业微信授权状态看不清。"


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text or "")
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


class _Call:
    def __init__(self, returncode=1, stdout="", stderr="", error=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.error = error


def _call(runner, argv: list[str]) -> _Call:
    try:
        completed = runner(argv, _TIMEOUT)
    except subprocess.TimeoutExpired:
        return _Call(error="timeout")
    except (FileNotFoundError, OSError):
        return _Call(error="missing")
    return _Call(
        returncode=getattr(completed, "returncode", 1),
        stdout=getattr(completed, "stdout", "") or "",
        stderr=getattr(completed, "stderr", "") or "",
    )


def _finish(result: _Call) -> str:
    if result.error == "timeout":
        return _TIMEOUT_TEXT
    if result.error == "missing":
        return _missing(load_connector("wecom"))
    body = _body(result)
    if result.returncode != 0:
        return body or _FAILED
    return body


def _body(result: _Call) -> str:
    text = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if text and err:
        body = f"{text}\n{err}"
    else:
        body = text or err
    if len(body) <= _LIMIT:
        return body
    return body[:_LIMIT] + "\n…已截断。"


def _log(argv: list[str]) -> None:
    shown = []
    hide_next = False
    for part in argv[1:]:
        if hide_next:
            shown.append("[redacted]")
            hide_next = False
            continue
        shown.append(part)
        hide_next = part == "--json"
    logger.info("企业微信 CLI %s", " ".join(shown))


def _workdir() -> str:
    """临时目录。命令按相对路径读文件时，不会读到项目里的 .env。"""
    path = Path(tempfile.gettempdir()) / "xiaoluozi-wecom"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _run(argv: list[str], timeout: int):
    """wecom-cli 的 node 入口会再拉起真正的二进制。超时要结束整组进程。"""
    process = subprocess.Popen(
        argv,
        cwd=_workdir(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop(process)
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _stop(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass
