import threading
import uuid
from dataclasses import dataclass

from xiaoluozi.errors import ModelNotConfigured, ReplyError
from xiaoluozi.log import get_logger
from xiaoluozi.memory import TurnRecord

logger = get_logger("xiaoluozi.loop")

UNSAVED_NOTE = "这一轮没有存进记忆。"


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

        context = self._context(text)
        try:
            decision = self.router.route(text, context)
        except Exception as exc:
            detail = str(exc).strip() or "模型调用失败。"
            logger.info("回路拒绝 %s", detail)
            raise
        logger.info("回路意图 %s", decision.intent)
        try:
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
            )
        except Exception as exc:
            logger.info("回路历史没有写入 %s", exc)

    def _context(self, message: str) -> str:
        parts = []
        if self.history is not None:
            recent = self.history.context().strip()
            if recent:
                parts.append(recent)
        recalled = self._recall(message)
        if recalled:
            parts.append(recalled)
        return "\n\n".join(parts)

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
