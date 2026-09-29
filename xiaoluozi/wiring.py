from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.config import Settings
from xiaoluozi.loop import Loop
from xiaoluozi.memory import HindsightMemory
from xiaoluozi.model import ClosedModel, OpenAICompatibleClient
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router


def build_loop(settings: Settings | None = None) -> Loop:
    settings = settings or Settings.from_env()
    if settings.model_configured:
        model = OpenAICompatibleClient(settings.api_key, settings.base_url, settings.model)
    else:
        model = ClosedModel()
    registry = Registry([ChatAgent(model)])
    return Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=HindsightMemory(settings.hindsight_base_url, settings.hindsight_bank_id),
        model_configured=settings.model_configured,
    )
