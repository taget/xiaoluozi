import json
import queue
import re
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from knot import ChatRequest, Client

from xiaoluozi.agents.support import install
from xiaoluozi.errors import ReplyError
from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.knot")

MIGRATE_URL = "http://knot.woa.com/apigw/api/v1/agents/agui/687fb0de01614c5b84ba495919c5ff02"
VSTATION_URL = "http://knot.woa.com/apigw/api/v1/agents/agui/dcfd1be40f2d430a98f689b9e96bd6c8"
_AGUI = "/agents/agui/"
_LOCAL_IDS = frozenset({"chat", "qa", "cvm", "kb", "wxwork", "perf-gap"})
_AGENT_KEY = re.compile(r"^KNOT_AGENT_([A-Z0-9]+(?:_[A-Z0-9]+)*)$")
_AGENT_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_NOT_CONFIGURED = "Knot 还没配好。在 .env 里设置 KNOT_API_TOKEN 后再试。"
_BAD_URL = "Knot 地址不对。需要指向 agents/agui 下的智能体。"
_FAILED = "Knot 调用失败。"
_EMPTY = "Knot 没有返回内容。"


@dataclass(frozen=True)
class KnotSpec:
    """One Knot agent. A new one is an id, a Chinese description, and an agui URL."""

    id: str
    description: str
    url: str
    consultable: bool = False


BUILTIN_KNOT_SPECS = (
    KnotSpec(
        "migrate",
        "处理 CVM 迁移。迁移方案、问卷、落地评估、从其他云迁到腾讯云这类句子用这个。",
        MIGRATE_URL,
        consultable=True,
    ),
    KnotSpec(
        "vstation",
        "处理 vstation 排障。vstation 报错、实例创建失败、销毁失败、热迁移失败这类句子用这个。查库存和配额不用这个。",
        VSTATION_URL,
        consultable=True,
    ),
)


class KnotAgent:
    """Send the turn to one Knot agui endpoint. Does not call the local chat model."""

    spec: KnotSpec | None = None
    id = ""
    description = ""
    skill_ids = ()
    service_ids = ("Knot",)
    env_keys = ("KNOT_API_TOKEN",)

    def __init__(self, llm, skills=(), env=None, opener=None, spec=None):
        install(self, llm, skills, env)
        self.spec = spec or self.__class__.spec
        if self.spec is None:
            raise ValueError("Knot 代理还没有端点。")
        self.id = self.spec.id
        self.description = self.spec.description
        self.consultable = bool(self.spec.consultable)
        self._opener = opener or open_knot
        self._clients: dict[str, object] = {}
        self._conversations: dict[str, object] = {}
        self._lock = threading.RLock()

    def handle(self, message: str, *, context: str = "", intent: str = "", conversation_id: str = "default") -> str:
        return "".join(self.stream(message, context=context, intent=intent, conversation_id=conversation_id))

    def stream(self, message: str, *, context: str = "", intent: str = "", conversation_id: str = "default"):
        events = queue.Queue()

        def run():
            try:
                self._talk(message, events.put, conversation_id)
            except BaseException as exc:
                events.put(exc)
            else:
                events.put(None)

        threading.Thread(target=run, name=f"knot-{self.id}", daemon=True).start()
        while True:
            item = events.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients = {}
            self._conversations = {}
        for client in clients:
            closer = getattr(client, "close", None)
            if callable(closer):
                closer()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return None

    def _talk(self, message: str, emit, conversation_id: str = "default") -> None:
        with self._lock:
            conversation = self._conversation_for(conversation_id)
            writer = _SseWriter(emit)
            try:
                conversation.chat(ChatRequest(message=message), writer)
            except ReplyError:
                raise
            except Exception as exc:
                logger.info("Knot 调用失败 agent_id=%s %s", self.id, exc.__class__.__name__)
                raise ReplyError(_FAILED) from exc
            writer.finish()
            if not writer.saw_text:
                raise ReplyError(_EMPTY)

    def _conversation_for(self, conversation_id: str = "default"):
        key = (conversation_id or "default").strip() or "default"
        with self._lock:
            cached = self._conversations.get(key)
            if cached is not None:
                return cached
            token = _token(self._env)
            api_url = resolve_knot_url(self.spec, self._env)
            logger.info("Knot 请求 agent_id=%s conversation=%s %s", self.id, key, api_url)
            try:
                client, agent_id = self._opener(token, api_url)
            except ValueError as exc:
                raise ReplyError(_BAD_URL) from exc
            self._clients[key] = client
            conversation = client.new_conversation(agent_id)
            self._conversations[key] = conversation
            return conversation


def knot_env_key(agent_id: str) -> str:
    """`.env` key for one agent's agui URL. `vstation` becomes `KNOT_AGENT_VSTATION`."""
    return "KNOT_AGENT_" + agent_id.upper().replace("-", "_")


def resolve_knot_url(spec: KnotSpec, env: dict | None) -> str:
    """URL for this turn. `KNOT_AGENT_<ID>` wins. `KNOT_API_URL` still selects migrate."""
    values = env or {}
    chosen = (values.get(knot_env_key(spec.id)) or "").strip()
    if not chosen and spec.id == "migrate":
        chosen = (values.get("KNOT_API_URL") or "").strip()
    return chosen or spec.url


def knot_specs(env: dict | None = None) -> tuple[KnotSpec, ...]:
    """Built-in Knot agents, plus any agent declared only by an endpoint in `.env`."""
    values = env or {}
    specs = list(BUILTIN_KNOT_SPECS)
    known = {spec.id for spec in specs}
    for key, raw in values.items():
        if not isinstance(key, str) or key.endswith("_DESCRIPTION"):
            continue
        match = _AGENT_KEY.fullmatch(key)
        if match is None:
            continue
        agent_id = match.group(1).lower().replace("_", "-")
        if agent_id in known:
            continue
        if agent_id in _LOCAL_IDS:
            raise ValueError(f"Knot 代理 {agent_id} 与已有代理重名。")
        if _AGENT_ID.fullmatch(agent_id) is None:
            raise ValueError(f"Knot 代理 id {agent_id} 不合法。")
        url = (raw or "").strip()
        description = (values.get(f"{key}_DESCRIPTION") or "").strip()
        if not url:
            raise ValueError(f"Knot 代理 {agent_id} 还没有地址。在 .env 里设置 {key}。")
        if not description:
            raise ValueError(f"Knot 代理 {agent_id} 还没有中文说明。在 .env 里设置 {key}_DESCRIPTION。")
        try:
            split_knot_endpoint(url)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        specs.append(KnotSpec(agent_id, description, url))
        known.add(agent_id)
    return tuple(specs)


def open_knot(token: str, api_url: str):
    """Knot client for one agui endpoint. The scheme in the URL is kept."""
    base, agent_id = split_knot_endpoint(api_url)
    host = urlsplit(base).hostname or "knot.woa.com"
    return Client(host, token, timeout=300, _base_url=base), agent_id


def split_knot_endpoint(url: str) -> tuple[str, str]:
    """Split an agui URL into the SDK base and the agent id."""
    parsed = urlsplit((url or "").strip())
    path = parsed.path.rstrip("/")
    index = path.find(_AGUI)
    agent_id = path[index + len(_AGUI) :] if index >= 0 else ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not agent_id or "/" in agent_id:
        raise ValueError(_BAD_URL)
    base_path = path[: index + len("/agents/agui")]
    base = urlunsplit((parsed.scheme, parsed.netloc, base_path, "", "")).rstrip("/")
    return base, agent_id


def _token(env: dict) -> str:
    token = (env.get("KNOT_API_TOKEN") or "").strip()
    if not token:
        logger.info("Knot 请求被拒绝 未配置")
        raise ReplyError(_NOT_CONFIGURED)
    return token


class _SseWriter:
    """Collect TEXT_MESSAGE_CONTENT pieces from the raw SSE bytes Knot writes."""

    def __init__(self, emit):
        self._emit = emit
        self._pending = b""
        self.saw_text = False

    def write(self, data: bytes) -> int:
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._pending += data
        while b"\n" in self._pending:
            line, self._pending = self._pending.split(b"\n", 1)
            self._take(line)
        return len(data)

    def flush(self) -> None:
        return None

    def finish(self) -> None:
        if self._pending:
            self._take(self._pending)
            self._pending = b""

    def _take(self, line: bytes) -> None:
        text = line.decode("utf-8", errors="replace").strip()
        if not text.startswith("data:"):
            return
        data = text[len("data:") :].strip()
        if not data or data == "[DONE]":
            return
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict) or msg.get("type") != "TEXT_MESSAGE_CONTENT":
            return
        raw = msg.get("rawEvent")
        content = raw.get("content") if isinstance(raw, dict) else ""
        if not isinstance(content, str) or not content:
            return
        self.saw_text = True
        self._emit(content)
