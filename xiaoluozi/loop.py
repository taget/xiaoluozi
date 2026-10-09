import threading
import uuid
from dataclasses import dataclass

from xiaoluozi.errors import ModelNotConfigured, ReplyError
from xiaoluozi.log import get_logger
from xiaoluozi.memory import TurnRecord
from xiaoluozi.router import INTENT_UNKNOWN, RoutingDecision

logger = get_logger("xiaoluozi.loop")

UNSAVED_NOTE = "这一轮没有存进记忆。"
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


class Loop:
    """Sole orchestrator: recall, laya decides agent and intent, the agent calls the LLM, then retain."""

    def __init__(self, registry, router, model, memory, *, model_configured: bool = True, history=None):
        self.registry = registry
        self.router = router
        self.model = model
        self.memory = memory
        self.model_configured = model_configured
        self.history = history
        self._lock = threading.Lock()

    def handle(self, message: str, *, channel: str = "web") -> Reply:
        with self._lock:
            return self._handle(message, channel)

    def _handle(self, message: str, channel: str) -> Reply:
        text = message.strip()
        logger.info("回路开始 %s", text)
        if not text:
            logger.info("回路拒绝 先写一句话。")
            raise ReplyError("先写一句话。")
        if not self.model_configured:
            logger.info("回路拒绝 模型还没配好。")
            raise ModelNotConfigured("模型还没配好。在 .env 里设置 TYPESAFE_API_KEY 后再试。")

        dialogue, recalled = self._context_parts(text)
        context = "\n\n".join(part for part in (dialogue, recalled) if part)
        try:
            decision = self._route(text)
        except Exception as exc:
            detail = str(exc).strip() or "模型调用失败。"
            logger.info("回路拒绝 %s", detail)
            raise
        logger.info("回路意图 %s", decision.intent)
        try:
            # 模型如果返回技能允许的工具调用，代理会先执行，把结果交回模型，直到有文字回复。
            reply = self.registry.get(decision.agent_id).handle(text, context=context, intent=decision.intent)
        except Exception as exc:
            detail = str(exc).strip() or "模型调用失败。"
            logger.info("回路拒绝 %s", detail)
            raise ReplyError(detail) from exc
        if not isinstance(reply, str) or not reply.strip():
            logger.info("回路拒绝 模型没有返回内容。")
            raise ReplyError("模型没有返回内容。")
        reply = reply.strip()
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
        try:
            self.memory.retain_turn(turn)
        except Exception as exc:
            logger.info("回路写入 turn_id=%s saved=false %s", turn.turn_id, exc)
            self._remember(turn, shown, UNSAVED_NOTE)
            return Reply(text=shown, saved=False, note=UNSAVED_NOTE)
        logger.info("回路写入 turn_id=%s saved=true", turn.turn_id)
        self._remember(turn, shown, None)
        return Reply(text=shown, saved=True, note=None)

    def _remember(self, turn: TurnRecord, shown: str, note: str | None) -> None:
        if self.history is None:
            return
        try:
            self.history.append(
                channel=turn.channel,
                user_message=turn.user_message,
                reply=turn.reply,
                shown=shown,
                note=note,
                turn_id=turn.turn_id,
                agent_id=turn.agent_id,
            )
        except Exception as exc:
            logger.info("回路历史没有写入 %s", exc)

    def _route(self, text: str) -> RoutingDecision:
        previous = self._previous_agent()
        if _is_ack(text) and previous:
            reason = f"这句话没有新的业务内容，沿用上次的 {previous}。"
            logger.info("回路沿用 agent_id=%s %s", previous, reason)
            return RoutingDecision(previous, reason, INTENT_UNKNOWN)
        return self.router.route(text, self._routing_input())

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

    def _routing_input(self) -> str:
        """The one previous user input laya sees. The agent still gets the full context."""
        if self.history is None:
            return ""
        last = self.history.latest()
        if last is None:
            return ""
        return last.user_message.strip()

    def _context_parts(self, message: str) -> tuple[str, str]:
        dialogue = ""
        if self.history is not None:
            dialogue = self.history.context().strip()
        return dialogue, self._recall(message)


    def _recall(self, message: str) -> str:
        recall = getattr(self.memory, "recall", None)
        if recall is None:
            return ""
        try:
            memories = recall(message)
        except Exception as exc:
            logger.info("回路上下文失败 %s", exc)
            return ""
        if not isinstance(memories, list):
            return ""
        lines = [item.strip() for item in memories if isinstance(item, str) and item.strip()]
        logger.info("回路上下文 %s 条\n%s", len(lines), "\n".join(lines))
        return "\n".join(lines)


def _is_ack(text: str) -> bool:
    cleaned = text.strip().lower().strip("。！？!?.,，、…~～ ")
    return cleaned in _ACKS
