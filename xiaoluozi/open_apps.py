"""Local applications an agent may offer to open. The list lives in open_apps.toml."""

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


@dataclass(frozen=True)
class OpenApp:
    id: str
    name: str
    app: str
    url: str = ""


def open_apps_path() -> Path:
    return Path(__file__).resolve().with_name("open_apps.toml")


def load_open_apps(path: Path | None = None) -> tuple[OpenApp, ...]:
    """Read the allowlist. A bad file fails here, before any application is opened."""
    file = path or open_apps_path()
    if not file.is_file():
        raise ValueError("没有找到可打开的应用名单 open_apps.toml。")
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("open_apps.toml 读不了。") from exc
    rows = data.get("app") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("open_apps.toml 里没有应用名单。")
    loaded: list[OpenApp] = []
    seen: set[str] = set()
    for row in rows:
        app = _app(row)
        if app.id in seen:
            raise ValueError(f"应用 {app.id} 重复了。")
        seen.add(app.id)
        loaded.append(app)
    return tuple(loaded)


def find_open_app(key: str, apps: tuple[OpenApp, ...] | None = None) -> OpenApp | None:
    """Match an id, display name, or macOS app name from the allowlist."""
    text = (key or "").strip().casefold()
    if not text:
        return None
    for app in apps if apps is not None else load_open_apps():
        if text in {app.id.casefold(), app.name.casefold(), app.app.casefold()}:
            return app
    return None


def launch_app(app: OpenApp, *, run=None) -> None:
    """Open one allowlisted macOS app. Callers only use this after the user clicks."""
    if app.url:
        return
    runner = run or subprocess.run
    completed = runner(["open", "-a", app.app], check=False)
    if getattr(completed, "returncode", 0) != 0:
        raise OSError("open")


def _app(row) -> OpenApp:
    if not isinstance(row, dict):
        raise ValueError("open_apps.toml 里有一条应用读不了。")
    app_id = _text(row.get("id"))
    name = _text(row.get("name"))
    app_name = _text(row.get("app"))
    url = _text(row.get("url"))
    if _ID.fullmatch(app_id) is None:
        raise ValueError(f"应用 id {app_id or '空'} 不合法。")
    if not name or not app_name:
        raise ValueError(f"应用 {app_id} 还没有名称。")
    if url and not re.fullmatch(r"[a-z][a-z0-9+.-]*:", url.split("/", 1)[0]):
        raise ValueError(f"应用 {app_id} 的地址不合法。")
    return OpenApp(app_id, name, app_name, url)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""
