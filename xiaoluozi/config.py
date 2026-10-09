import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_BASE_URL = "http://v2.open.venus.oa.com/llmproxy"
DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_LAYA_MODEL = "laya"
DEFAULT_AGENT = "chat"
DEFAULT_ENABLED_AGENTS = "chat,qa,cvm"
DEFAULT_WEIXIN_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_TOOL_MAX_ROUNDS = 8


def env_path() -> Path:
    """Project-root .env. The package lives one directory below that root."""
    return Path(__file__).resolve().parent.parent / ".env"


def _read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[len("export ") :].strip()
        key, sep, raw = text.partition("=")
        if not sep:
            continue
        key = key.strip()
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        values[key] = raw
    return values


def _pick(values: dict[str, str], name: str, default: str = "") -> str:
    return values.get(name, "").strip() or default


def _flag(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(raw: str, default: int, name: str) -> int:
    text = raw.strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"{name} 必须是正整数。") from None
    if value < 1:
        raise ValueError(f"{name} 必须是正整数。")
    return value


def _account_id(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", raw.strip())
    return cleaned or "default"


def account_path(root: Path) -> Path:
    return root / "data" / "weixin" / "account.json"


def _read_account(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    values = {}
    for key in ("token", "baseUrl", "userId"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            values[key] = value.strip()
    return values


def _apply_weixin_account(settings: "Settings", values: dict[str, str], root: Path) -> "Settings":
    if not settings.weixin_enabled or settings.weixin_token:
        return settings
    account = _read_account(account_path(root))
    token = account.get("token", "")
    if not token:
        return settings
    base_url = settings.weixin_base_url
    if "WEIXIN_BASE_URL" not in values and account.get("baseUrl"):
        base_url = account["baseUrl"]
    return replace(settings, weixin_token=token, weixin_base_url=base_url)


def _agent_ids(raw: str) -> tuple[str, ...]:
    ids: list[str] = []
    for part in raw.split(","):
        agent_id = part.strip()
        if agent_id and agent_id not in ids:
            ids.append(agent_id)
    return tuple(ids)


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    hindsight_base_url: str
    hindsight_bank_id: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    laya_model: str
    enabled_agents: tuple[str, ...]
    default_agent: str
    weixin_enabled: bool
    weixin_base_url: str
    weixin_token: str
    weixin_account_id: str
    max_tool_rounds: int = DEFAULT_TOOL_MAX_ROUNDS
    dotenv: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """Read configuration from the project .env file."""
        env_file = path if path is not None else env_path()
        values = _read_env(env_file)
        settings = cls(
            api_key=_pick(values, "TYPESAFE_API_KEY"),
            base_url=_pick(values, "TYPESAFE_BASE_URL", DEFAULT_BASE_URL),
            model=_pick(values, "TYPESAFE_DEFAULT_MODEL", DEFAULT_MODEL),
            hindsight_base_url=_pick(values, "HINDSIGHT_BASE_URL"),
            hindsight_bank_id=_pick(values, "HINDSIGHT_BANK_ID"),
            llm_api_key=_pick(values, "LLM_API_KEY"),
            llm_base_url=_pick(values, "LLM_BASE_URL"),
            llm_model=_pick(values, "LLM_MODEL_NAME"),
            laya_model=_pick(values, "LAYA_MODEL", DEFAULT_LAYA_MODEL),
            enabled_agents=_agent_ids(_pick(values, "ENABLED_AGENTS", DEFAULT_ENABLED_AGENTS)),
            default_agent=_pick(values, "DEFAULT_AGENT", DEFAULT_AGENT),
            weixin_enabled=_flag(_pick(values, "WEIXIN_ENABLED")),
            weixin_base_url=_pick(values, "WEIXIN_BASE_URL", DEFAULT_WEIXIN_BASE_URL),
            weixin_token=_pick(values, "WEIXIN_BOT_TOKEN"),
            weixin_account_id=_account_id(_pick(values, "WEIXIN_ACCOUNT_ID", "default")),
            max_tool_rounds=_positive_int(
                _pick(values, "TOOL_MAX_ROUNDS"),
                DEFAULT_TOOL_MAX_ROUNDS,
                "TOOL_MAX_ROUNDS",
            ),
            dotenv=dict(values),
        )
        return _apply_weixin_account(settings, values, env_file.parent)

    @property
    def model_configured(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def memory_configured(self) -> bool:
        return bool(self.hindsight_base_url.strip() and self.hindsight_bank_id.strip())

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.strip() and self.llm_base_url.strip() and self.llm_model.strip())

    @property
    def weixin_configured(self) -> bool:
        return self.weixin_enabled and bool(self.weixin_token.strip() and self.weixin_base_url.strip())

    def pick(self, keys: tuple[str, ...]) -> dict[str, str]:
        """Values an agent named in env_keys. Missing keys are empty strings."""
        return {key: self.dotenv.get(key, "") for key in keys}
