from hindsight_litellm import wrap_openai
from openai import OpenAI

from xiaoluozi.agents.chat import ChatAgent
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


def _registry(settings: Settings, llm):
    skills = SkillCatalog()
    catalog = {
        "chat": ChatAgent(llm, skills.load(ChatAgent.skill_ids)),
        "qa": QaAgent(llm, skills.load(QaAgent.skill_ids)),
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
        client = wrap_openai(
            client,
            hindsight_api_url=settings.hindsight_base_url,
            bank_id=settings.hindsight_bank_id,
            verbose=True,
        )
    return LlmClient(client, settings.llm_model, settings.llm_api_key)
