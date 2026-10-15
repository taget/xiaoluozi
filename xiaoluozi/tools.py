"""Tools a skill is allowed to run, and the model round that executes them.

Bash and Vault run only when a skill names them. Vault only reads the knowledge checkout. A text reply ends the round.
"""

import json
import os
import subprocess

import httpx

from xiaoluozi.config import DEFAULT_TOOL_MAX_ROUNDS
from xiaoluozi.open_apps import find_open_app, load_open_apps
from xiaoluozi.errors import ModelError
from xiaoluozi.log import get_logger
from xiaoluozi.vault import run_vault
from xiaoluozi.wecom import CATEGORIES, is_gate, run_wecom

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


DELEGATE_SPEC = {
    "type": "function",
    "function": {
        "name": "Delegate",
        "description": "请一个只读代理完成子任务。拿到结果后先判断是否相关，再决定继续委派或给出最终答复。",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "目标代理 id。"},
                "task": {"type": "string", "description": "要完成的子任务。"},
                "hypothesis": {"type": "string", "description": "这次要核对的假设。"},
                "evidence": {"type": "string", "description": "已经拿到的证据。没有就留空。"},
            },
            "required": ["agent", "task", "hypothesis"],
        },
    },
}


def finish_answer(
    create,
    messages: list,
    tools=None,
    env=None,
    max_rounds: int = DEFAULT_TOOL_MAX_ROUNDS,
    delegate=None,
) -> str:
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
            if function["name"] == "Delegate":
                result = "这一轮不能委派。" if delegate is None else delegate(function.get("arguments") or "")
                if not isinstance(result, str):
                    result = str(result)
            else:
                result = run_tool(function["name"], function["arguments"], env=env)
            if function["name"] == "Wecom" and is_gate(result):
                return result
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


VAULT_SPEC = {
    "type": "function",
    "function": {
        "name": "Vault",
        "description": "在个人知识库里检索或阅读笔记。只能读，不能改文件，也不能提交。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "read", "map"],
                    "description": "search 按词检索，read 读一篇笔记，map 看知识地图。",
                },
                "query": {"type": "string", "description": "search 时的关键词。"},
                "path": {"type": "string", "description": "read 时相对知识库根目录的路径。"},
            },
            "required": ["action"],
        },
    },
}


def tool_specs(skills) -> list[dict]:
    names = []
    for skill in skills:
        for name in getattr(skill, "allowed_tools", ()):
            if name not in names:
                names.append(name)
    specs = []
    if "Bash" in names:
        specs.append(BASH_SPEC)
    if "Vault" in names:
        specs.append(VAULT_SPEC)
    if "Search" in names:
        specs.append(SEARCH_SPEC)
    if "Open" in names:
        specs.append(open_spec())
    if "Wecom" in names:
        specs.append(WECOM_SPEC)
    return specs


def run_tool(name: str, arguments: str, env=None) -> str:
    if name == "Delegate":
        return "这一轮不能委派。"
    if name == "Open":
        logger.info("回路工具 Open")
        result = open_entry(_open_app_id(arguments))
        logger.info("回路工具结果 %s", result[:200])
        return result
    if name == "Wecom":
        logger.info("回路工具 Wecom")
        result = run_wecom(arguments)
        logger.info("回路工具结果 %s", result[:200])
        return result
    if name == "Search":
        logger.info("回路工具 Search")
        result = search_public(_search_query(arguments))
        logger.info("回路工具结果 %s", result[:200])
        return result
    if name == "Vault":
        logger.info("回路工具 Vault")
        result = run_vault(arguments, env)
        logger.info("回路工具结果 %s", result[:200])
        return result
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


SEARCH_SPEC = {
    "type": "function",
    "function": {
        "name": "Search",
        "description": "检索公开资料。用来核对事实、近况和名词。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词，短一些。"},
            },
            "required": ["query"],
        },
    },
}
_SEARCH_URL = "https://api.duckduckgo.com/"
_SEARCH_LIMIT = 4000


def search_public(query: str, *, get=None) -> str:
    """Look up a short query. Tests pass get; otherwise this calls DuckDuckGo."""
    text = (query or "").strip()
    if not text:
        return "检索词是空的。"
    getter = get or _search_get
    try:
        payload = getter(text)
    except Exception as exc:
        logger.info("检索失败 %s", exc.__class__.__name__)
        return "检索失败。"
    found = _format_search(payload if isinstance(payload, dict) else {})
    if len(found) > _SEARCH_LIMIT:
        return found[:_SEARCH_LIMIT].rstrip() + "\n输出被截断。"
    return found


def _search_query(arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    query = payload.get("query") or ""
    return query.strip() if isinstance(query, str) else ""


def _search_get(query: str) -> dict:
    response = httpx.get(
        _SEARCH_URL,
        params={"q": query, "format": "json", "no_redirect": "1", "no_html": "1", "skip_disambig": "1"},
        timeout=15,
        headers={"User-Agent": "xiaoluozi"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("search")
    return payload


def _format_search(payload: dict) -> str:
    lines = []
    heading = _text(payload.get("Heading"))
    abstract = _text(payload.get("AbstractText"))
    url = _text(payload.get("AbstractURL"))
    if heading:
        lines.append(heading)
    if abstract:
        lines.append(abstract)
    if url:
        lines.append(f"来源：{url}")
    related = _related(payload.get("RelatedTopics"))
    if related:
        if lines:
            lines.append("")
        lines.append("相关：")
        lines.extend(related)
    return "\n".join(lines).strip() or "没有查到公开结果。"


def _related(topics, limit: int = 5) -> list[str]:
    found = []
    for item in topics or []:
        if len(found) >= limit:
            break
        if not isinstance(item, dict):
            continue
        nested = item.get("Topics")
        if isinstance(nested, list):
            found.extend(_related(nested, limit - len(found)))
            continue
        text = _text(item.get("Text"))
        url = _text(item.get("FirstURL"))
        if not text:
            continue
        found.append(f"- {text}" + (f"\n  {url}" if url else ""))
    return found


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


WECOM_SPEC = {
    "type": "function",
    "function": {
        "name": "Wecom",
        "description": "调用本机官方 wecom-cli。不打开企业微信窗口。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["version", "auth"],
                    "description": "version 看版本；auth 只看授权状态。",
                },
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                    "description": "企业微信品类。",
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "子命令片段，例如 [\"users\", \"search\"]。不要带 -- 开头的参数。",
                },
                "args": {
                    "type": "object",
                    "description": "交给 --json 的参数对象。",
                },
                "help": {
                    "type": "boolean",
                    "description": "为 true 时只看该品类的帮助。",
                },
            },
        },
    },
}


def open_spec() -> dict:
    try:
        apps = load_open_apps()
    except ValueError:
        apps = ()
    listed = "、".join(app.id for app in apps) or "没有"
    return {
        "type": "function",
        "function": {
            "name": "Open",
            "description": f"准备一个打开本地应用的入口，不直接打开。可选 id：{listed}。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string", "description": "应用 id，必须在名单里。"},
                },
                "required": ["app"],
            },
        },
    }


def open_entry(app_id: str) -> str:
    """Return a clickable entry. This does not launch the application."""
    try:
        apps = load_open_apps()
    except ValueError as exc:
        return str(exc)
    app = find_open_app(app_id, apps)
    if app is None:
        names = "、".join(item.id for item in apps) or "没有"
        return f"不能打开这个应用。可选：{names}。"
    return f"可以给用户一个入口：[打开 {app.name}](app:{app.id})"


def _open_app_id(arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    app_id = payload.get("app") or payload.get("id") or ""
    return app_id.strip() if isinstance(app_id, str) else ""
