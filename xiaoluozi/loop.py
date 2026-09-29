import uuid
from dataclasses import dataclass

from xiaoluozi.errors import ModelNotConfigured, ReplyError
from xiaoluozi.memory import TurnRecord

COGNITION_FAILED = "认知提取失败。"
UNSAVED_NOTE = "这一轮没有存进记忆。"

_COGNITION_SYSTEM = (
    "阅读这一轮对话，只抽出一条短认知：一个结论、一个偏好，或一个决定。"
    "只输出这一句话，不要解释，不要复述整段回复。"
)


@dataclass(frozen=True)
class Reply:
    """What handle returns. text is the only sentence the page shows as the answer."""

    text: str
    saved: bool
    note: str | None = None


class Loop:
    """Sole orchestrator: route, then reply, then cognition, then retain."""

    def __init__(self, registry, router, model, memory, *, model_configured: bool = True):
        self.registry = registry
        self.router = router
        self.model = model
        self.memory = memory
        self.model_configured = model_configured

    def handle(self, message: str) -> Reply:
        text = message.strip()
        if not text:
            raise ReplyError("先写一句话。")
        if not self.model_configured:
            raise ModelNotConfigured("模型还没配好。设置 TYPESAFE_API_KEY 后再试。")

        decision = self.router.route(text)
        try:
            reply = self.registry.get(decision.agent_id).handle(text)
        except Exception as exc:
            detail = str(exc).strip() or "模型调用失败。"
            raise ReplyError(detail) from exc
        if not isinstance(reply, str) or not reply.strip():
            raise ReplyError("模型没有返回内容。")
        reply = reply.strip()

        cognition = self._cognize(text, reply)
        turn = TurnRecord(
            turn_id=uuid.uuid4().hex,
            user_message=text,
            agent_id=decision.agent_id,
            reason=decision.reason,
            reply=reply,
            cognition=cognition,
        )
        try:
            self.memory.retain_turn(turn)
        except Exception:
            return Reply(text=reply, saved=False, note=UNSAVED_NOTE)
        return Reply(text=reply, saved=True, note=None)

    def _cognize(self, message: str, reply: str) -> str:
        try:
            raw = self.model.complete(
                [
                    {"role": "system", "content": _COGNITION_SYSTEM},
                    {"role": "user", "content": f"用户说：{message}\n回复：{reply}"},
                ]
            )
        except Exception:
            return COGNITION_FAILED
        if not isinstance(raw, str) or not raw.strip():
            return COGNITION_FAILED
        return raw.strip()
