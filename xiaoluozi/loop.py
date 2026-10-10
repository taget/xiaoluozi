import threading
import uuid
from dataclasses import dataclass

from xiaoluozi.errors import ModelNotConfigured, ReplyError
from xiaoluozi.log import get_logger
from xiaoluozi.memory import TurnRecord
from xiaoluozi.router import INTENT_UNKNOWN, RoutingDecision

logger = get_logger("xiaoluozi.loop")

UNSAVED_NOTE = "这一轮没有存进记忆。"
DEFAULT_DECISION_LIMIT = 10
_ACKS = {
    "好的",
    "好",
    "是的",
    "是",
    "对",
    "对的",
    "确认",
    "嗯",
    "嗯嗯",
    "行",
    "可以",
    "ok",
    "okay",
    "收到",
    "明白",
    "知道了",
    "没问题",
}


@dataclass(frozen=True)
class Reply:
    """What handle returns. text is the only sentence the page shows as the answer."""

    text: str
    saved: bool
    note: str | None = None


@dataclass(frozen=True)
class DecisionBasis:
    """Latest user input handed to laya. It is not an agent's memory."""

    message: str


@dataclass(frozen=True)
class QueuedDecision:
    """One routing result kept on that agent's queue until the queue is full."""

    message: str
    agent_id: str
    reason: str
    intent: str


class Loop:
    """Sole orchestrator: recall, laya decides agent and intent, the agent calls the LLM, then retain."""

    def __init__(
        self,
        registry,
        router,
        model,
        memory,
        *,
        model_configured: bool = True,
        history=None,
        decision_limit: int = DEFAULT_DECISION_LIMIT,
    ):
        if decision_limit < 1:
            raise ValueError("决策队列长度至少是 1。")
        self.registry = registry
        self.router = router
        self.model = model
        self.memory = memory
        self.model_configured = model_configured
        self.history = history
        self.decision_limit = decision_limit
        self._decisions: dict[str, list[QueuedDecision]] = {}
        self._recent: list[QueuedDecision] = []
        self._lock = threading.RLock()

    def handle(self, message: str, *, channel: str = "web") -> Reply:
        with self._lock:
            return self._collect(self._generate(message, channel))

    def stream(self, message: str, *, channel: str = "web"):
        """Yield model text as it arrives, then the finished Reply. WeChat keeps using handle."""
        with self._lock:
            yield from self._generate(message, channel)

    def _collect(self, events) -> Reply:
        reply = None
        for item in events:
            if isinstance(item, Reply):
                reply = item
        if reply is None:
            raise ReplyError("模型没有返回内容。")
        return reply

    def _generate(self, message: str, channel: str):
        text = message.strip()
        logger.info("回路开始 %s", text)
        if not text:
            logger.info("回路拒绝 先写一句话。")
            raise ReplyError("先写一句话。")
        if not self.model_configured:
            logger.info("回路拒绝 模型还没配好。")
            raise ModelNotConfigured("模型还没配好。在 .env 里设置 TYPESAFE_API_KEY 后再试。")

        basis = DecisionBasis(message=text)
        logger.info("+++++ 调用 laya +++++")
        logger.info("决策依赖\n%s", basis.message)
        logger.info("------------- 以下为模型调用 -----------")
        try:
            decision = self._route(basis.message)
        except Exception as exc:
            latest = self._latest_decision()
            if latest is None:
                detail = str(exc).strip() or "模型调用失败。"
                logger.info("回路拒绝 %s", detail)
                raise
            decision = RoutingDecision(latest.agent_id, latest.reason, latest.intent)
            logger.info("决策失败，沿用最新一条 agent_id=%s，不入队。", decision.agent_id)
        else:
            self._record_decision(text, decision)
        logger.info(">>>>>> 回路意图 %s", decision.intent)
        context = self._revise_context(text, self._context(text, decision.agent_id))
        logger.info("上下文记忆 agent_id=%s\n%s", decision.agent_id, context.strip() or "没有可用的上下文。")
        pieces = []
        try:
            # 模型如果返回技能允许的工具调用，代理会先执行，把结果交回模型，直到有文字回复。
            for piece in self._agent_text(decision.agent_id, text, context, decision.intent):
                if not isinstance(piece, str) or not piece:
                    continue
                pieces.append(piece)
                yield piece
        except Exception as exc:
            detail = str(exc).strip() or "模型调用失败。"
            logger.info("回路拒绝 %s", detail)
            raise ReplyError(detail) from exc
        reply = "".join(pieces).strip()
        if not reply:
            logger.info("回路拒绝 模型没有返回内容。")
            raise ReplyError("模型没有返回内容。")
        shown = f"{reply}\n\n选用 {decision.agent_id}。依据：{decision.reason}"
        logger.info("回路回复 agent_id=%s %s", decision.agent_id, shown)

        turn = TurnRecord(
            turn_id=uuid.uuid4().hex,
            user_message=text,
            agent_id=decision.agent_id,
            reason=decision.reason,
            reply=reply,
            cognition=decision.intent,
            channel=channel,
        )
        if not self._remembers(decision.agent_id):
            note = self._memory_note(decision.agent_id)
            logger.info("回路不写入记忆 agent_id=%s", decision.agent_id)
            self._remember(turn, shown, note)
            yield Reply(text=shown, saved=False, note=note)
            return
        try:
            self.memory.retain_turn(turn)
        except Exception as exc:
            logger.info("回路写入 turn_id=%s saved=false %s", turn.turn_id, exc)
            self._remember(turn, shown, UNSAVED_NOTE)
            yield Reply(text=shown, saved=False, note=UNSAVED_NOTE)
            return
        logger.info("回路写入 turn_id=%s saved=true", turn.turn_id)
        self._remember(turn, shown, None)
        yield Reply(text=shown, saved=True, note=None)

    def _agent_text(self, agent_id: str, text: str, context: str, intent: str):
        agent = self.registry.get(agent_id)
        source = getattr(agent, "stream", None)
        if source is None:
            whole = agent.handle(text, context=context, intent=intent)
            if isinstance(whole, str) and whole:
                yield whole
            return
        yield from source(text, context=context, intent=intent)

    def append_decision(self, message: str, decision) -> None:
        """Put one routing decision on that agent's queue. A full queue is saved, then cleared."""
        with self._lock:
            agent_id = decision.agent_id
            queue = self._queue(agent_id)
            if len(queue) >= self.decision_limit:
                self._refresh_decisions(agent_id)
            queue = self._queue(agent_id)
            if len(queue) >= self.decision_limit:
                logger.info("决策队列已满 agent_id=%s，这一条没有进入队列。", agent_id)
                return
            item = QueuedDecision(
                message=message,
                agent_id=agent_id,
                reason=decision.reason,
                intent=decision.intent,
            )
            queue.append(item)
            self._recent.append(item)
            logger.info(
                "决策进入队列 %s/%s agent_id=%s",
                len(queue),
                self.decision_limit,
                agent_id,
            )
            if len(queue) >= self.decision_limit:
                self._refresh_decisions(agent_id)

    def _record_decision(self, message: str, decision) -> None:
        latest = self._latest_decision()
        if latest is not None and _same_decision(decision, latest):
            logger.info("决策与最新一条一致 agent_id=%s，不入队。", decision.agent_id)
            return
        self.append_decision(message, decision)

    def _latest_decision(self) -> QueuedDecision | None:
        if not self._recent:
            return None
        return self._recent[-1]

    def decision_at(self, agent_id: str, index: int) -> QueuedDecision:
        """Return one agent's decision at this position. The first one is 0."""
        with self._lock:
            try:
                return self._decisions.get(agent_id, [])[index]
            except IndexError as exc:
                raise IndexError(f"决策队列 {agent_id} 没有第 {index} 条。") from exc

    def refresh_decisions(self, agent_id: str) -> bool:
        """Save this agent's queue once it is full, then clear it. A short queue stays."""
        with self._lock:
            return self._refresh_decisions(agent_id)

    def _queue(self, agent_id: str) -> list[QueuedDecision]:
        return self._decisions.setdefault(agent_id, [])

    def _refresh_decisions(self, agent_id: str) -> bool:
        queue = self._decisions.get(agent_id, [])
        if len(queue) < self.decision_limit:
            logger.info(
                "决策队列未满 agent_id=%s %s/%s，不写入记忆。",
                agent_id,
                len(queue),
                self.decision_limit,
            )
            return False
        pending = list(queue)
        save = getattr(self.memory, "retain_decisions", None)
        if save is None:
            logger.info("决策队列没有记忆端口 agent_id=%s，未写入。", agent_id)
            return False
        try:
            save(pending)
        except Exception as exc:
            logger.info("决策队列写入失败 agent_id=%s %s", agent_id, exc)
            return False
        self._decisions[agent_id] = []
        self._recent = [item for item in self._recent if item.agent_id != agent_id]
        logger.info("决策队列已写入记忆 agent_id=%s %s 条", agent_id, len(pending))
        return True

    def _remember(self, turn: TurnRecord, shown: str, note: str | None) -> None:
        if self.history is None:
            return
        try:
            self.history.append(
                channel=turn.channel,
                agent_id=turn.agent_id,
                user_message=turn.user_message,
                reply=turn.reply,
                shown=shown,
                note=note,
                turn_id=turn.turn_id,
            )
        except Exception as exc:
            logger.info("回路历史没有写入 %s", exc)

    def _route(self, text: str) -> RoutingDecision:
        previous = self._previous_agent()
        if _is_ack(text) and previous:
            reason = f"这句话没有新的业务内容，沿用上次的 {previous}。"
            logger.info("回路沿用 agent_id=%s %s", previous, reason)
            return RoutingDecision(previous, reason, INTENT_UNKNOWN)
        return self.router.route(text)

    def _previous_agent(self) -> str:
        if self.history is None:
            return ""
        last = self.history.latest()
        if last is None:
            return ""
        agent_id = last.agent_id.strip()
        if agent_id not in self.registry.ids():
            return ""
        return agent_id

    def _revise_context(self, message: str, context: str) -> str:
        """Reserved. Edit this agent's gathered memory before the agent sees it."""
        return context

    def _context(self, message: str, agent_id: str) -> str:
        parts = []
        if self.history is not None:
            recent = self.history.context(agent_id).strip()
            if recent:
                parts.append(recent)
        if self._remembers(agent_id):
            recalled = self._recall(message, agent_id)
            if recalled:
                parts.append(recalled)
        else:
            logger.info("回路不召回记忆 agent_id=%s", agent_id)
        return "\n\n".join(parts)

    def _remembers(self, agent_id: str) -> bool:
        return getattr(self.registry.get(agent_id), "remembers", True)

    def _memory_note(self, agent_id: str) -> str:
        return getattr(self.registry.get(agent_id), "memory_note", None) or "这一轮不写入记忆。"

    def _recall(self, message: str, agent_id: str) -> str:
        recall = getattr(self.memory, "recall", None)
        if recall is None:
            return ""
        try:
            memories = recall(message, agent_id)
        except TypeError:
            memories = recall(message)
        except Exception as exc:
            logger.info("回路上下文失败 agent_id=%s %s", agent_id, exc)
            return ""
        if not isinstance(memories, list):
            return ""
        lines = [item.strip() for item in memories if isinstance(item, str) and item.strip()]
        return "\n".join(lines)


def _is_ack(text: str) -> bool:
    cleaned = text.strip().lower().strip("。！？!?.,，、…~～ ")
    return cleaned in _ACKS


def _same_decision(decision, latest: QueuedDecision) -> bool:
    return (
        decision.agent_id == latest.agent_id
        and decision.reason == latest.reason
        and decision.intent == latest.intent
    )
