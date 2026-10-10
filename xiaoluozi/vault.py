"""Read-only search of the local checkout of the personal knowledge vault.

The checkout is the git working tree of https://github.com/taget/obsidian.
This module never writes, commits, or pulls.
"""

import json
import subprocess
from pathlib import Path

MAP_PATH = "superme/00-索引/MOC.md"
SEARCH_LIMIT = 8
READ_LIMIT = 12000
FILE_LIMIT = 512_000

NOT_CONFIGURED = (
    "知识库路径还没配。在 .env 里设置 OBSIDIAN_VAULT_PATH，"
    "指向 https://github.com/taget/obsidian 的本地检出。"
)


def run_vault(arguments: str, env=None) -> str:
    payload, error = _payload(arguments)
    if error:
        return error
    action = payload.get("action") or ""
    if not isinstance(action, str) or not action.strip():
        return "没有这个动作。"
    action = action.strip()
    root, error = _root(env)
    if error:
        return error
    if action == "map":
        return _map(root)
    if action == "search":
        query = payload.get("query") or ""
        if not isinstance(query, str) or not query.strip():
            return "检索词是空的。"
        return _search(root, query.strip())
    if action == "read":
        path = payload.get("path") or ""
        if not isinstance(path, str) or not path.strip():
            return "笔记路径是空的。"
        return _read(root, path.strip())
    return "没有这个动作。"


def _payload(arguments: str) -> tuple[dict, str]:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}, "工具参数读不了。"
    if not isinstance(payload, dict):
        return {}, "工具参数读不了。"
    return payload, ""


def _root(env) -> tuple[Path | None, str]:
    raw = ""
    if isinstance(env, dict):
        value = env.get("OBSIDIAN_VAULT_PATH") or ""
        if isinstance(value, str):
            raw = value.strip()
    if not raw:
        return None, NOT_CONFIGURED
    path = Path(raw)
    if not path.exists():
        return None, "知识库目录不存在。"
    if not path.is_dir():
        return None, "知识库路径不是目录。"
    return path, ""


def _map(root: Path) -> str:
    path, error = _resolve(root, MAP_PATH)
    if error:
        return error
    if not path.is_file():
        return "知识地图不在 superme/00-索引/MOC.md。"
    return _header(root) + _clip(path)


def _search(root: Path, query: str) -> str:
    hits = []
    more = False
    for path in _notes(root):
        try:
            if path.stat().st_size > FILE_LIMIT:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root.resolve()).as_posix()
        if not _matches(text, relative, query):
            continue
        if len(hits) >= SEARCH_LIMIT:
            more = True
            break
        hits.append((relative, _snippet(text, query)))
    header = _header(root)
    if not hits:
        return header + "没有找到相关笔记。"
    lines = [header + f"找到 {len(hits)} 篇："]
    for relative, snippet in hits:
        lines.append(f"- {relative}")
        if snippet:
            lines.append(f"  {snippet}")
    if more:
        lines.append("还有更多，换个更具体的词再搜。")
    return "\n".join(lines)


def _read(root: Path, raw: str) -> str:
    path, error = _resolve(root, raw)
    if error:
        return error
    if not path.is_file():
        return "没有这篇笔记。"
    try:
        if path.stat().st_size > FILE_LIMIT:
            return "这篇笔记太长。"
    except OSError:
        return "没有这篇笔记。"
    relative = path.relative_to(root.resolve()).as_posix()
    return f"{_header(root)}{relative}\n\n{_clip(path)}"


def _notes(root: Path) -> list[Path]:
    root_resolved = root.resolve()
    found = []
    for path in root_resolved.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(root_resolved)
        except (OSError, ValueError):
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        found.append(path.resolve())
    found.sort(key=lambda item: item.as_posix())
    return found


def _matches(text: str, relative: str, query: str) -> bool:
    haystack = f"{relative}\n{text}".lower()
    parts = [part for part in query.lower().split() if part]
    return bool(parts) and all(part in haystack for part in parts)


def _snippet(text: str, query: str) -> str:
    folded = " ".join(text.split())
    if not folded:
        return ""
    needle = next((part for part in query.lower().split() if part), "")
    index = folded.lower().find(needle) if needle else -1
    if index < 0:
        return folded[:180]
    start = max(0, index - 40)
    end = min(len(folded), index + 140)
    piece = folded[start:end]
    if start:
        piece = "…" + piece
    if end < len(folded):
        piece += "…"
    return piece


def _clip(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= READ_LIMIT:
        return text
    return text[:READ_LIMIT] + "\n\n（后面截断了。）"


def _resolve(root: Path, raw: str) -> tuple[Path | None, str]:
    text = raw.strip()
    if not text or text.startswith("~") or "\x00" in text:
        return None, "路径不在知识库里。"
    candidate = Path(text)
    if candidate.is_absolute():
        return None, "路径不在知识库里。"
    root_resolved = root.resolve()
    try:
        target = (root_resolved / candidate).resolve()
    except OSError:
        return None, "路径不在知识库里。"
    if target != root_resolved and root_resolved not in target.parents:
        return None, "路径不在知识库里。"
    try:
        relative = target.relative_to(root_resolved)
    except ValueError:
        return None, "路径不在知识库里。"
    if any(part.startswith(".") for part in relative.parts):
        return None, "路径不在知识库里。"
    return target, ""


def _header(root: Path) -> str:
    revision = _revision(root)
    if not revision:
        return ""
    return f"本地检出 {revision}。\n"


def _revision(root: Path) -> str:
    if not (root / ".git").exists():
        return ""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    revision = completed.stdout.strip()
    if completed.returncode != 0 or not revision or any(char.isspace() for char in revision):
        return ""
    return revision
