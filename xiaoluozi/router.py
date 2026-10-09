import json

from xiaoluozi.log import get_logger
from xiaoluozi.registry import Registry

logger = get_logger("xiaoluozi.router")
FALLBACK_ID = "chat"
NONE_ID = "none"
INTENT_UNKNOWN = "没有识别出意图。"
LAYA_MAX_TOKENS = 8192
_RECALL_HEAD = "相关记忆："
_EARLIER_OMITTED = "（更早的上下文已省略。）"
_REST_OMITTED = "（其余上下文已省略。）"
_QUESTION_OMITTED = "（问题已截断。）"
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
        logger.info("路由候选 %s", "、".join(agent_id for agent_id, _description in agents))
        questions = {
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
        }
        answers = self._model.decide(fit_laya_state(message, context, agents, questions), questions)
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


def estimate_tokens(text: str) -> int:
    """Upper bound. A non-ASCII character counts as two tokens, so a request stays under the cap."""
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def laya_request_tokens(state: str, questions: dict) -> int:
    payload = json.dumps({"state": state, "questions": questions}, ensure_ascii=False)
    return estimate_tokens(payload)


def fit_laya_state(message: str, context: str, agents: list[tuple[str, str]], questions: dict) -> str:
    """Shrink context until the laya request is within 8192 tokens. The question and agents stay."""
    full = routing_state(message, context, agents)
    if laya_request_tokens(full, questions) <= LAYA_MAX_TOKENS:
        return full
    fitted_message = _fit_message(message, agents, questions)
    fitted_context = _fit_context(context, _context_room(fitted_message, agents, questions))
    state = routing_state(fitted_message, fitted_context, agents)
    logger.info(
        "路由上下文已压缩 %s token -> %s token，上限 %s。",
        laya_request_tokens(full, questions),
        laya_request_tokens(state, questions),
        LAYA_MAX_TOKENS,
    )
    return state


def _context_room(message: str, agents: list[tuple[str, str]], questions: dict) -> int:
    placeholder = "没有可用的上下文。"
    used = laya_request_tokens(routing_state(message, "", agents), questions) - estimate_tokens(placeholder)
    return max(0, LAYA_MAX_TOKENS - used)


def _fit_message(message: str, agents: list[tuple[str, str]], questions: dict) -> str:
    if laya_request_tokens(routing_state(message, "", agents), questions) <= LAYA_MAX_TOKENS:
        return message
    best = ""
    lo, hi = 0, len(message)
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = message[:mid].rstrip()
        shown = f"{candidate}{_QUESTION_OMITTED}".strip() if candidate else ""
        if shown and laya_request_tokens(routing_state(shown, "", agents), questions) <= LAYA_MAX_TOKENS:
            best = shown
            lo = mid + 1
        else:
            hi = mid - 1
    return best or message[:1]


def _fit_context(context: str, room: int) -> str:
    text = context.strip()
    if room <= 0 or not text:
        return ""
    if estimate_tokens(text) <= room:
        return text
    history, recall = _split_context(text)
    if history and recall:
        fitted_history = _fit_history(history, room)
        remain = room - estimate_tokens(fitted_history) - estimate_tokens("\n\n")
        fitted_recall = _fit_prefix_block(recall, remain)
        return "\n\n".join(part for part in (fitted_history, fitted_recall) if part)
    if history:
        return _fit_history(history, room)
    return _fit_prefix_block(text, room)


def _split_context(context: str) -> tuple[str, str]:
    marker = f"\n\n{_RECALL_HEAD}\n"
    if context.startswith(f"{_RECALL_HEAD}\n"):
        return "", context
    if marker in context:
        history, recall = context.split(marker, 1)
        return history, f"{_RECALL_HEAD}\n{recall}"
    if context.startswith("最近对话："):
        return context, ""
    return "", context


def _fit_history(history: str, budget: int) -> str:
    if estimate_tokens(history) <= budget:
        return history
    lines = history.split("\n")
    header = lines[0]
    body = lines[1:]
    note_cost = estimate_tokens(f"{header}\n{_EARLIER_OMITTED}\n")
    if note_cost >= budget:
        return _prefix(history, budget)
    kept: list[str] = []
    used = note_cost
    for line in reversed(body):
        cost = estimate_tokens(line + "\n")
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    if not kept:
        room = budget - note_cost
        tail = _suffix(body[-1], room) if body else ""
        if not tail:
            return _prefix(history, budget)
        kept = [tail]
    return f"{header}\n{_EARLIER_OMITTED}\n" + "\n".join(kept)


def _fit_prefix_block(text: str, budget: int) -> str:
    if budget <= 0 or not text:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    note = f"\n{_REST_OMITTED}"
    body = _prefix(text, budget - estimate_tokens(note))
    if not body:
        return _prefix(text, budget)
    return body + note


def _prefix(text: str, budget: int) -> str:
    if budget <= 0 or not text:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    cut = text[:lo]
    newline = cut.rfind("\n")
    if newline > 0 and cut[:newline].strip():
        return cut[:newline].rstrip()
    return cut.rstrip()


def _suffix(text: str, budget: int) -> str:
    if budget <= 0 or not text:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if estimate_tokens(text[mid:]) <= budget:
            hi = mid
        else:
            lo = mid + 1
    cut = text[lo:]
    newline = cut.find("\n")
    if newline > 0 and cut[newline + 1 :].strip():
        return cut[newline + 1 :].lstrip()
    return cut.lstrip()


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
