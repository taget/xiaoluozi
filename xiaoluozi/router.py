import json

from xiaoluozi.log import get_logger
from xiaoluozi.registry import Registry

logger = get_logger("xiaoluozi.router")
FALLBACK_ID = "chat"
NONE_ID = "none"
INTENT_UNKNOWN = "没有识别出意图。"
INTENTS = {
    "ask": "在提问",
    "decide": "在拿主意",
    "tell": "在说一件事",
    "greet": "在寒暄",
}


class RoutingDecision:
    def __init__(self, agent_id: str, reason: str, intent: str = INTENT_UNKNOWN):
        self.agent_id = agent_id
        self.reason = reason
        self.intent = intent


class Router:
    """Ask laya which enabled agent should take the sentence. Do not run the agent."""

    def __init__(self, model, registry: Registry, *, default_agent: str = FALLBACK_ID, selectable=None):
        self._model = model
        self._registry = registry
        self._default_agent = default_agent or FALLBACK_ID
        self._selectable = selectable

    def route(self, message: str, context: str = "") -> RoutingDecision:
        agents = self._agents()
        if not agents:
            return _decide(self._default_agent, "没有其他代理可选。", "没有可启用的代理。")
        criteria = {agent_id: description for agent_id, description in agents}
        criteria[NONE_ID] = "没有合适的代理。"
        answers = self._model.decide(
            routing_state(message, context, agents),
            {
                "agent_id": {
                    "type": "choice",
                    "instructions": "从后端代理里选一个处理这句话。没有合适的就选 none。",
                    "criteria": criteria,
                },
                "intent": {
                    "type": "choice",
                    "instructions": "用户这句话的意图是什么？",
                    "criteria": dict(INTENTS),
                },
            },
        )
        return decision_from_answers(answers, criteria, self._default_agent)

    def _agents(self) -> list[tuple[str, str]]:
        listing = self._registry.listing()
        if self._selectable is None:
            return listing
        by_id = dict(listing)
        return [(agent_id, by_id[agent_id]) for agent_id in self._selectable if agent_id in by_id]


def routing_state(message: str, context: str, agents: list[tuple[str, str]]) -> str:
    """What laya reads: the question, the current context, and the configured agents."""
    context_text = context.strip() or "没有可用的上下文。"
    lines = "\n".join(f"- {agent_id}：{description}" for agent_id, description in agents)
    return f"用户问题：{message}\n\n当前上下文：\n{context_text}\n\n后端代理：\n{lines}"


def decision_from_answers(answers, criteria: dict[str, str], default_agent: str = FALLBACK_ID) -> RoutingDecision:
    raw = answers if isinstance(answers, str) else json.dumps(answers, ensure_ascii=False)
    intent = _intent_label(answers)
    choice = _choice(answers)
    if choice is None or choice == NONE_ID:
        return _decide(default_agent, f"没有合适的代理，已回退到 {default_agent}。", raw, intent)
    if choice not in criteria:
        return _decide(default_agent, f"未知代理 {choice}，已回退到 {default_agent}。", raw, intent)
    return _decide(choice, criteria[choice], raw, intent)


def _choice(answers):
    if not isinstance(answers, dict):
        return None
    item = answers.get("agent_id")
    if not isinstance(item, dict):
        return None
    choice = item.get("choice")
    if not isinstance(choice, str) or not choice.strip():
        return None
    return choice.strip()


def _intent_label(answers) -> str:
    if not isinstance(answers, dict):
        return INTENT_UNKNOWN
    item = answers.get("intent")
    if not isinstance(item, dict):
        return INTENT_UNKNOWN
    choice = item.get("choice")
    if not isinstance(choice, str):
        return INTENT_UNKNOWN
    return INTENTS.get(choice.strip(), INTENT_UNKNOWN)


def _decide(agent_id: str, reason: str, raw: str, intent: str = INTENT_UNKNOWN) -> RoutingDecision:
    logger.info("路由决定 agent_id=%s intent=%s reason=%s raw=%s", agent_id, intent, reason, raw)
    return RoutingDecision(agent_id, reason, intent)
