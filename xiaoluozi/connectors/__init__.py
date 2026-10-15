"""Connectors an agent can opt into.

A connector is a WorkBuddy-style Skill + CLI definition: `connectors/<id>/cli.json`
names the install, version, and status commands. The process runs those commands.
"""

import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ARG = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*|--?[A-Za-z0-9][A-Za-z0-9._-]*)$")
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class Connector:
    id: str
    skill: str
    init_command: str
    version_argv: tuple[str, ...]
    min_version: tuple[int, int, int]
    status_argv: tuple[str, ...]
    status_match: re.Pattern[str]

    def authorized(self, text: str) -> bool:
        return self.status_match.search(text or "") is not None


def connectors_root() -> Path:
    return Path(__file__).resolve().parent


def load_connector(connector_id: str) -> Connector:
    if _ID.fullmatch(connector_id or "") is None:
        raise ValueError(f"连接器 {connector_id} 的 id 不合法。")
    path = connectors_root() / connector_id / "cli.json"
    if not path.is_file():
        raise ValueError(f"未知连接器 {connector_id}。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"连接器 {connector_id} 的 cli.json 读不了。") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"连接器 {connector_id} 的 cli.json 读不了。")
    declared = payload.get("id")
    if declared != connector_id:
        raise ValueError(f"连接器目录名 {connector_id} 和 id {declared} 不一致。")
    skill = payload.get("skill")
    if not isinstance(skill, str) or skill != connector_id:
        raise ValueError(f"连接器 {connector_id} 的 skill 要和 id 一致。")
    status_match = _status_match(connector_id, payload.get("statusMatch"))
    return Connector(
        id=connector_id,
        skill=skill,
        init_command=_text_command(connector_id, payload.get("init"), "init"),
        version_argv=_argv_command(connector_id, _nested(payload, "versionCheck", "command"), "versionCheck"),
        min_version=_min_version(connector_id, _nested(payload, "versionCheck", "minVersion")),
        status_argv=_argv_command(connector_id, payload.get("status"), "status"),
        status_match=status_match,
    )


def load_connectors(ids: tuple[str, ...]) -> tuple[Connector, ...]:
    return tuple(load_connector(connector_id) for connector_id in ids)


def require_connectors(ids, skills) -> tuple[Connector, ...]:
    """The agent named these connectors, and each one's skill is already loaded."""
    names = {getattr(skill, "name", "") for skill in skills}
    loaded = []
    for connector in load_connectors(tuple(ids)):
        if connector.skill not in names:
            raise ValueError(f"连接器 {connector.id} 没有装到这个代理上。")
        loaded.append(connector)
    return tuple(loaded)


def _platform() -> str:
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _nested(payload: dict, key: str, child: str):
    block = payload.get(key)
    if not isinstance(block, dict):
        return None
    return block.get(child)


def _platform_command(connector_id: str, value, field: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"连接器 {connector_id} 的 cli.json 缺少 {field}。")
    command = value.get(_platform())
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"连接器 {connector_id} 的 cli.json 缺少 {field}。")
    return command.strip()


def _text_command(connector_id: str, value, field: str) -> str:
    return _platform_command(connector_id, value, field)


def _argv_command(connector_id: str, value, field: str) -> tuple[str, ...]:
    command = _platform_command(connector_id, value, field)
    try:
        parts = tuple(shlex.split(command))
    except ValueError as exc:
        raise ValueError(f"连接器 {connector_id} 的 {field} 命令不合法。") from exc
    if not parts or any(_ARG.fullmatch(part) is None for part in parts):
        raise ValueError(f"连接器 {connector_id} 的 {field} 命令不合法。")
    return parts


def _min_version(connector_id: str, value) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ValueError(f"连接器 {connector_id} 的 cli.json 缺少 minVersion。")
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"连接器 {connector_id} 的 minVersion 不合法。")
    return tuple(int(part) for part in match.groups())


def _status_match(connector_id: str, value) -> re.Pattern[str]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"连接器 {connector_id} 的 cli.json 缺少 statusMatch。")
    try:
        pattern = re.compile(value)
    except re.error as exc:
        raise ValueError(f"连接器 {connector_id} 的 statusMatch 不合法。") from exc
    if pattern.search("unauthorized"):
        raise ValueError(f"连接器 {connector_id} 的状态匹配会把未授权当成已授权。")
    return pattern
