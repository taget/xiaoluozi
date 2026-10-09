"""Agent Skills on disk. Metadata is read when the catalog is built; the body is loaded when an agent names the skill."""

import re
from dataclasses import dataclass
from pathlib import Path

from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.skills")

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FOLDED = {">", ">-", ">+"}
_LITERAL = {"|", "|-", "|+"}


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    allowed_tools: tuple[str, ...] = ()


def skills_root() -> Path:
    return Path(__file__).resolve().parent


class SkillCatalog:
    """Read `skill-name/SKILL.md` under the skills directory."""

    def __init__(self, root: Path | None = None):
        self._root = root if root is not None else skills_root()
        self._descriptions: dict[str, str] = {}
        if not self._root.is_dir():
            return
        for path in sorted(self._root.iterdir()):
            if not path.is_dir() or path.name.startswith(".") or path.name == "__pycache__":
                continue
            skill_file = path / "SKILL.md"
            if not skill_file.is_file():
                continue
            name, description, _body, _tools = _read(skill_file, path.name)
            self._descriptions[name] = description

    def load(self, names: tuple[str, ...]) -> tuple[Skill, ...]:
        loaded = []
        for name in names:
            if name not in self._descriptions:
                raise ValueError(f"未知 skill {name}。")
            skill_name, description, body, allowed_tools = _read(self._root / name / "SKILL.md", name)
            text = body.strip()
            if not text:
                raise ValueError(f"skill {name} 的说明是空的。")
            logger.info("skill 加载 %s", name)
            loaded.append(Skill(skill_name, description, text, allowed_tools))
        return tuple(loaded)


def require_skills(expected: tuple[str, ...], skills) -> tuple[Skill, ...]:
    names = tuple(getattr(skill, "name", "") for skill in skills)
    if names != tuple(expected):
        needed = "、".join(expected) or "（无）"
        got = "、".join(name for name in names if name) or "（无）"
        if got == "（无）":
            raise ValueError(f"技能没有按声明加载：需要 {needed}，得到（无）。")
        raise ValueError(f"技能没有按声明加载：需要 {needed}，得到 {got}。")
    return tuple(skills)


def system_with_skills(system: str, skills: tuple[Skill, ...]) -> str:
    if not skills:
        return system
    return system + "\n\n" + "\n\n".join(skill.body.strip() for skill in skills)


def _read(path: Path, directory: str) -> tuple[str, str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"skill {directory} 的 SKILL.md 没有 frontmatter。")
    end = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError(f"skill {directory} 的 SKILL.md 没有 frontmatter。")
    fields = _fields(lines[1:end], directory)
    body = "\n".join(lines[end + 1 :])
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    _check_name(name, directory)
    if "description" not in fields or not description:
        raise ValueError(f"skill {directory} 缺少 description。")
    if len(description) > 1024:
        raise ValueError(f"skill {directory} 的 description 过长。")
    return name, description, body, _tool_names(fields.get("allowed-tools", ""))


def _check_name(name: str, directory: str) -> None:
    if len(name) > 64 or _NAME.fullmatch(name) is None:
        raise ValueError(f"skill {directory} 的 name 不合法。")
    if name != directory:
        raise ValueError(f"skill 目录名 {directory} 和 name {name} 不一致。")


def _fields(lines: list[str], directory: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[0] in " \t":
            index += 1
            continue
        key, sep, raw = line.partition(":")
        if not sep or not key.strip():
            raise ValueError(f"skill {directory} 的 frontmatter 读不了。")
        key = key.strip()
        raw = raw.strip()
        index += 1
        if raw in _FOLDED or raw in _LITERAL:
            block, index = _block(lines, index)
            value = _join_block(raw, block)
        elif raw == "":
            block, index = _block(lines, index)
            value = " ".join(part for part in block if part).strip()
        else:
            value = _unquote(raw)
        if key in {"name", "description", "allowed-tools"}:
            fields[key] = value
    return fields


def _block(lines: list[str], index: int) -> tuple[list[str], int]:
    block = []
    while index < len(lines):
        line = lines[index]
        if line.strip() and line[0] not in " \t":
            break
        block.append(line.strip())
        index += 1
    return block, index


def _join_block(marker: str, block: list[str]) -> str:
    if marker in _LITERAL:
        return "\n".join(block).strip()
    paragraphs = []
    current = []
    for line in block:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n".join(paragraphs).strip()


def _tool_names(raw: str) -> tuple[str, ...]:
    names = []
    for part in raw.replace(",", " ").split():
        name = part.strip().lstrip("-").strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
