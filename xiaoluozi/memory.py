from dataclasses import dataclass
from urllib.parse import quote

import httpx

from xiaoluozi.errors import MemoryError


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    user_message: str
    agent_id: str
    reason: str
    reply: str
    cognition: str


class HindsightMemory:
    """Retain one turn through Hindsight's current memories API.

    POST {base}/v1/default/banks/{bank_id}/memories
    The loop only sees retain_turn; it does not see this request.
    """

    def __init__(self, base_url: str, bank_id: str, client: httpx.Client | None = None):
        self._base_url = (base_url or "").strip().rstrip("/")
        self._bank_id = (bank_id or "").strip()
        self._client = client
        if self._client is None and self._base_url and self._bank_id:
            self._client = httpx.Client(timeout=20.0)

    def retain_turn(self, turn: TurnRecord) -> None:
        if not self._base_url or not self._bank_id:
            raise MemoryError("记忆服务未配置。")
        url = f"{self._base_url}/v1/default/banks/{quote(self._bank_id, safe='')}/memories"
        try:
            response = self._client.post(url, json=_payload(turn))
        except httpx.HTTPError as exc:
            raise MemoryError("记忆没有写入。") from exc
        if response.status_code >= 400:
            raise MemoryError("记忆没有写入。")
        try:
            body = response.json()
        except Exception as exc:
            raise MemoryError("记忆没有写入。") from exc
        if not isinstance(body, dict) or body.get("success") is not True:
            raise MemoryError("记忆没有写入。")


def _payload(turn: TurnRecord) -> dict:
    kinds = (
        ("user", turn.user_message),
        ("routing", f"agent_id: {turn.agent_id}\nreason: {turn.reason}"),
        ("assistant", turn.reply),
        ("cognition", turn.cognition),
    )
    items = []
    for kind, content in kinds:
        items.append(
            {
                "content": content,
                "context": f"xiaoluozi {kind}",
                "document_id": turn.turn_id,
                "tags": [f"turn_id:{turn.turn_id}", f"kind:{kind}"],
                "metadata": {"turn_id": turn.turn_id, "kind": kind},
            }
        )
    return {"async": False, "items": items}
