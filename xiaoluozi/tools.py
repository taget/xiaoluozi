"""Tools a skill is allowed to run, and the model round that executes them.

Only Bash is executed, and only when a skill names it. A text reply ends the round.
"""

import json
import os
import subprocess

from xiaoluozi.config import DEFAULT_TOOL_MAX_ROUNDS
from xiaoluozi.errors import ModelError
from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.tools")

BASH_TIMEOUT = 90
BASH_OUTPUT_LIMIT = 12000

BASH_SPEC = {
    "type": "function",
    "function": {
        "name": "Bash",
        "description": "执行一条 shell 命令，用来完成 skill 要求的检查和 yunxiao 调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令。"},
            },
            "required": ["command"],
        },
    },
}


def finish_answer(create, messages: list, tools=None, env=None, max_rounds: int = DEFAULT_TOOL_MAX_ROUNDS) -> str:
    """Call the model. Run each allowed tool call, then call again, until the reply is text."""
    specs = list(tools or [])
    for _round in range(max_rounds):
        response = create(messages, specs)
        assistant = assistant_message(response)
        calls = assistant.get("tool_calls") or []
        if not calls:
            text = (assistant.get("content") or "").strip()
            if not text:
                raise ModelError("模型返回里没有回复内容。")
            return text
        messages.append(assistant)
        for call in calls:
            function = call["function"]
            result = run_tool(function["name"], function["arguments"], env=env)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    raise ModelError(f"工具调用没有在 {max_rounds} 次内结束。")


def assistant_message(response) -> dict:
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    content = getattr(message, "content", None)
    if content is not None and not isinstance(content, str):
        content = ""
    payload = {"role": "assistant", "content": content}
    calls = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or []):
        call_id, name, arguments = _tool_call_parts(call)
        calls.append(
            {
                "id": call_id or f"call-{index + 1}",
                "type": "function",
                "function": {"name": name, "arguments": arguments or "{}"},
            }
        )
    if calls:
        payload["tool_calls"] = calls
    return payload


def _tool_call_parts(call) -> tuple[str, str, str]:
    if isinstance(call, dict):
        function = call.get("function") or {}
        return call.get("id") or "", function.get("name") or "", function.get("arguments") or ""
    function = getattr(call, "function", None)
    return (
        getattr(call, "id", "") or "",
        getattr(function, "name", "") or "",
        getattr(function, "arguments", "") or "",
    )


def tool_specs(skills) -> list[dict]:
    names = []
    for skill in skills:
        for name in getattr(skill, "allowed_tools", ()):
            if name not in names:
                names.append(name)
    if "Bash" not in names:
        return []
    return [BASH_SPEC]


def run_tool(name: str, arguments: str, env=None) -> str:
    if name != "Bash":
        return f"没有这个工具 {name}。"
    command, error = _command(arguments)
    if error:
        return error
    logger.info("回路工具 Bash %s", _redact(command, env))
    try:
        completed = subprocess.run(
            ["/bin/bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=BASH_TIMEOUT,
            env=_bash_env(env),
        )
    except subprocess.TimeoutExpired:
        logger.info("回路工具结果 命令超时。")
        return "命令超时。"
    except OSError as exc:
        logger.info("回路工具结果 命令没有跑起来。%s", exc)
        return "命令没有跑起来。"
    text = f"{completed.stdout or ''}{completed.stderr or ''}".strip() or "命令没有输出。"
    if completed.returncode != 0:
        text = f"{text}\n退出码 {completed.returncode}"
    if len(text) > BASH_OUTPUT_LIMIT:
        text = text[:BASH_OUTPUT_LIMIT] + "\n输出被截断。"
    logger.info("回路工具结果 %s", _redact(text, env))
    return text


def _bash_env(env) -> dict[str, str]:
    merged = os.environ.copy()
    for key, value in (env or {}).items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    return merged


def _redact(text: str, env) -> str:
    for value in (env or {}).values():
        if isinstance(value, str) and value and value in text:
            text = text.replace(value, "[redacted]")
    return text


def _command(arguments: str) -> tuple[str, str]:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return "", "工具参数读不了。"
    if not isinstance(payload, dict):
        return "", "工具参数读不了。"
    command = payload.get("command") or payload.get("cmd") or ""
    if not isinstance(command, str) or not command.strip():
        return "", "命令是空的。"
    return command.strip(), ""
