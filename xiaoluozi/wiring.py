import threading
from typing import Any

from hindsight_litellm import wrap_openai
from openai import OpenAI

from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.agents.cvm import CvmAgent
from xiaoluozi.agents.qa import QaAgent
from xiaoluozi.config import Settings
from xiaoluozi.history import History
from xiaoluozi.loop import Loop
from xiaoluozi.memory import HindsightMemory
from xiaoluozi.model import ClosedLlm, ClosedModel, JevClient, LlmClient, LoggingOpenAI, chat_base_url
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router
from xiaoluozi.skills import SkillCatalog


def build_loop(settings: Settings | None = None, history: History | None = None) -> Loop:
    settings = settings or Settings.load()
    memory = HindsightMemory(settings.hindsight_base_url, settings.hindsight_bank_id)
    if settings.model_configured:
        laya = JevClient(settings.api_key, settings.base_url, settings.laya_model)
    else:
        laya = ClosedModel()
    llm = _llm(settings)
    registry, selectable = _registry(settings, llm)
    return Loop(
        registry=registry,
        router=Router(laya, registry, default_agent=settings.default_agent, selectable=selectable),
        model=laya,
        memory=memory,
        model_configured=settings.model_configured,
        history=history,
    )


def _make(agent_cls, llm, skills: SkillCatalog, settings: Settings):
    return agent_cls(
        llm,
        skills.load(agent_cls.skill_ids),
        env=settings.pick(getattr(agent_cls, "env_keys", ())),
    )


def _registry(settings: Settings, llm):
    skills = SkillCatalog()
    catalog = {
        "chat": _make(ChatAgent, llm, skills, settings),
        "qa": _make(QaAgent, llm, skills, settings),
        "cvm": _make(CvmAgent, llm, skills, settings),
    }
    if settings.default_agent not in catalog:
        raise ValueError(f"未知的默认代理 {settings.default_agent}。")
    unknown = [agent_id for agent_id in settings.enabled_agents if agent_id not in catalog]
    if unknown:
        raise ValueError(f"未知代理 {'、'.join(unknown)}。")
    order = []
    for agent_id in list(settings.enabled_agents) + [settings.default_agent]:
        if agent_id not in order:
            order.append(agent_id)
    return Registry([catalog[agent_id] for agent_id in order]), list(settings.enabled_agents)


def _llm(settings: Settings):
    if not settings.llm_configured:
        return ClosedLlm()
    client = LoggingOpenAI(
        OpenAI(
            api_key=settings.llm_api_key,
            base_url=chat_base_url(settings.llm_base_url),
            timeout=60.0,
        ),
        settings.llm_api_key,
    )
    if settings.memory_configured:
        client = _ThreadLocalOpenAI(client, settings.hindsight_base_url, settings.hindsight_bank_id)
    return LlmClient(client, settings.llm_model, settings.llm_api_key, settings.max_tool_rounds)


class _ThreadLocalOpenAI:
    """每个调用线程一份 wrap_openai。

    包装器里的 Hindsight 客户端会把 aiohttp 会话绑在第一次使用它的事件循环上。
    网页请求跑在线程池里，微信长轮询是另一条线程。共用一份包装器时，换线程召回会报
    Timeout context manager should be used inside a task。
    """

    def __init__(self, inner: LoggingOpenAI, api_url: str, bank_id: str) -> None:
        self._inner = inner
        self._wrap_cfg = (api_url, bank_id)
        self._local = threading.local()

    def _wrapped(self) -> Any:
        client = getattr(self._local, "client", None)
        if client is None:
            api_url, bank_id = self._wrap_cfg
            client = wrap_openai(
                self._inner,
                hindsight_api_url=api_url,
                bank_id=bank_id,
                verbose=True,
            )
            self._local.client = client
        return client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped(), name)
