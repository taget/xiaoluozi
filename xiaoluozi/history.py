import json
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.history")

CHANNEL_LABELS = {"web": "网页", "weixin": "微信"}
CONTEXT_TURNS = 8


def history_path(root: Path | None = None) -> Path:
    base = root if root is not None else Path(__file__).resolve().parent.parent
    return base / "data" / "history.json"


@dataclass(frozen=True)
class SharedTurn:
    turn_id: str
    channel: str
    agent_id: str
    user_message: str
    reply: str
    shown: str
    note: str | None


class History:
    """One transcript for every channel. Web and WeChat both read and append it."""

    def __init__(self, path: Path | None):
        self._path = path
        self._lock = threading.Lock()
        self._turns: list[SharedTurn] = []
        if path is not None and path.is_file():
            self._turns = _load(path)

    def append(
        self,
        *,
        channel: str,
        user_message: str,
        reply: str,
        shown: str,
        note: str | None,
        agent_id: str = "",
        turn_id: str | None = None,
    ) -> SharedTurn:
        turn = SharedTurn(
            turn_id=turn_id or uuid.uuid4().hex,
            channel=channel if channel in CHANNEL_LABELS else "web",
            agent_id=agent_id.strip() or "chat",
            user_message=user_message,
            reply=reply,
            shown=shown,
            note=note,
        )
        with self._lock:
            self._turns.append(turn)
            self._save_locked()
        logger.info("历史写入 channel=%s agent_id=%s turn_id=%s", turn.channel, turn.agent_id, turn.turn_id)
        return turn

    def turns(self) -> list[SharedTurn]:
        with self._lock:
            return list(self._turns)

    def latest(self) -> SharedTurn | None:
        turns = self.turns()
        if not turns:
            return None
        return turns[-1]

    def context(self, agent_id: str) -> str:
        recent = [turn for turn in self.turns() if turn.agent_id == agent_id][-CONTEXT_TURNS:]
        if not recent:
            return ""
        lines = [f"最近对话（{agent_id}）："]
        for turn in recent:
            label = CHANNEL_LABELS.get(turn.channel, turn.channel)
            lines.append(f"{label} / 用户：{turn.user_message}")
            lines.append(f"{label} / 小落子：{turn.reply}")
        return "\n".join(lines)

    def _save_locked(self) -> None:
        if self._path is None:
            return
        payload = [
            {
                "turn_id": turn.turn_id,
                "channel": turn.channel,
                "agent_id": turn.agent_id,
                "user_message": turn.user_message,
                "reply": turn.reply,
                "shown": turn.shown,
                "note": turn.note,
            }
            for turn in self._turns
        ]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load(path: Path) -> list[SharedTurn]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("历史读取失败 %s", exc)
        return []
    if not isinstance(data, list):
        return []
    turns = []
    for item in data:
        if not isinstance(item, dict):
            continue
        user_message = item.get("user_message")
        reply = item.get("reply")
        shown = item.get("shown") or reply
        if not isinstance(user_message, str) or not isinstance(reply, str) or not isinstance(shown, str):
            continue
        note = item.get("note")
        channel = item.get("channel")
        turn_id = item.get("turn_id")
        agent_id = item.get("agent_id")
        turns.append(
            SharedTurn(
                turn_id=turn_id if isinstance(turn_id, str) and turn_id else uuid.uuid4().hex,
                channel=channel if channel in CHANNEL_LABELS else "web",
                agent_id=agent_id.strip() if isinstance(agent_id, str) and agent_id.strip() else "chat",
                user_message=user_message,
                reply=reply,
                shown=shown,
                note=note if isinstance(note, str) and note else None,
            )
        )
    return turns
