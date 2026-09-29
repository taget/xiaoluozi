import json

from xiaoluozi.registry import Registry

FALLBACK_ID = "chat"


class RoutingDecision:
    def __init__(self, agent_id: str, reason: str):
        self.agent_id = agent_id
        self.reason = reason


class Router:
    """Ask laya which agent should take the sentence. Do not run the agent."""

    def __init__(self, model, registry: Registry):
        self._model = model
        self._registry = registry

    def route(self, message: str) -> RoutingDecision:
        listing = "\n".join(
            f"- {agent_id}: {description}" for agent_id, description in self._registry.listing()
        )
        system = (
            "你是路由器。根据用户的一句话，从下列代理里选一个。\n"
            "只输出 JSON，不要输出其它文字："
            '{"agent_id": "...", "reason": "..."}\n\n'
            "代理：\n"
            f"{listing}"
        )
        raw = self._model.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ]
        )
        return parse_route(raw, self._registry.ids())


def parse_route(raw: str, known_ids: set[str]) -> RoutingDecision:
    try:
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, AttributeError):
        return RoutingDecision(FALLBACK_ID, "路由结果不是合法 JSON，已回退到 chat。")
    if not isinstance(data, dict):
        return RoutingDecision(FALLBACK_ID, "路由结果不是合法 JSON，已回退到 chat。")
    agent_id = data.get("agent_id")
    reason = data.get("reason")
    if (
        not isinstance(agent_id, str)
        or not isinstance(reason, str)
        or not agent_id.strip()
        or not reason.strip()
    ):
        return RoutingDecision(FALLBACK_ID, "路由结果不是合法 JSON，已回退到 chat。")
    agent_id = agent_id.strip()
    reason = reason.strip()
    if agent_id not in known_ids:
        return RoutingDecision(FALLBACK_ID, f"未知代理 {agent_id}，已回退到 chat。")
    return RoutingDecision(agent_id, reason)
