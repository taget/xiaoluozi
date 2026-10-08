import json
import uuid
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from xiaoluozi.errors import MemoryError
from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.memory")


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    user_message: str
    agent_id: str
    reason: str
    reply: str
    cognition: str
    channel: str = "web"


class HindsightMemory:
    """Write one turn to an already-deployed Hindsight bank.

    POST {base}/v1/default/banks/{bank_id}/memories
    Recall feeds the laya routing state. Retain writes one turn.
    Model-call injection stays on wrap_openai.
    """

    def __init__(self, base_url: str, bank_id: str, client: httpx.Client | None = None):
        self._base_url = (base_url or "").strip().rstrip("/")
        self._bank_id = (bank_id or "").strip()
        self._client = client
        if self._client is None and self._base_url and self._bank_id:
            self._client = httpx.Client(timeout=20.0)

    def recall(self, query: str, agent_id: str = "") -> list[str]:
        text = query.strip()
        agent = agent_id.strip()
        if not text or not self._base_url or not self._bank_id or self._client is None:
            return []
        url = f"{self._bank_url()}/memories/recall"
        payload = {"query": text, "budget": "mid"}
        if agent:
            payload["tags"] = [f"agent:{agent}"]
            payload["tags_match"] = "all_strict"
        logger.info("记忆请求 POST %s\n%s", url, json.dumps(payload, ensure_ascii=False))
        try:
            response = self._client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.info("记忆请求失败 %s %s", url, exc)
            return []
        logger.info("记忆响应 %s %s\n%s", response.status_code, url, response.text)
        if response.status_code >= 400:
            return []
        try:
            results = response.json().get("results")
        except Exception:
            return []
        if not isinstance(results, list):
            return []
        memories = []
        for item in results:
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                memories.append(item["text"].strip())
        return memories

    def retain_turn(self, turn: TurnRecord) -> None:
        if not self._base_url or not self._bank_id:
            logger.info("记忆请求被拒绝 未配置 turn_id=%s", turn.turn_id)
            raise MemoryError("记忆服务未配置。")
        self._retain(_payload(turn))

    def retain_decisions(self, decisions) -> None:
        """Write one document for a full decision queue. One id, so later items do not erase earlier ones."""
        items = list(decisions)
        if not items:
            return
        if not self._base_url or not self._bank_id:
            logger.info("记忆请求被拒绝 未配置 决策队列")
            raise MemoryError("记忆服务未配置。")
        document_id = uuid.uuid4().hex
        agent_id = items[0].agent_id
        lines = [f"决策队列 {agent_id}："]
        for index, item in enumerate(items, start=1):
            lines.append(
                f"{index}. 用户: {item.message} 路由: agent_id={item.agent_id} "
                f"reason={item.reason} 认知: {item.intent}"
            )
        self._retain(
            {
                "async": False,
                "items": [
                    {
                        "content": "\n".join(lines),
                        "context": f"xiaoluozi 决策队列 {agent_id}",
                        "document_id": document_id,
                        "tags": [f"turn_id:{document_id}", "kind:decision-queue", f"agent:{agent_id}"],
                        "metadata": {
                            "turn_id": document_id,
                            "agent_id": agent_id,
                            "kind": "decision-queue",
                        },
                    }
                ],
            }
        )

    def _bank_url(self) -> str:
        return f"{self._base_url}/v1/default/banks/{quote(self._bank_id, safe='')}"

    def _retain(self, payload: dict) -> None:
        if not self._base_url or not self._bank_id or self._client is None:
            raise MemoryError("记忆服务未配置。")
        url = f"{self._bank_url()}/memories"
        logger.info("记忆请求 POST %s\n%s", url, json.dumps(payload, ensure_ascii=False))
        try:
            response = self._client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.info("记忆请求失败 %s %s", url, exc)
            raise MemoryError("记忆没有写入。") from exc
        logger.info("记忆响应 %s %s\n%s", response.status_code, url, response.text)
        if response.status_code >= 400:
            raise MemoryError("记忆没有写入。")
        try:
            body = response.json()
        except Exception as exc:
            raise MemoryError("记忆没有写入。") from exc
        if not isinstance(body, dict) or body.get("success") is not True:
            raise MemoryError("记忆没有写入。")


def _payload(turn: TurnRecord) -> dict:
    """One conversation document per turn.

    Hindsight upserts by document_id, so splitting a turn into several items
    that share an id would delete the earlier ones. The transcript keeps the
    user text, the routing decision, and the model reply together.
    """
    content = "\n".join(
        [
            f"通道: { '微信' if turn.channel == 'weixin' else '网页' }",
            f"用户: {turn.user_message}",
            f"路由: agent_id={turn.agent_id} reason={turn.reason}",
            f"回复: {turn.reply}",
            f"认知: {turn.cognition}",
        ]
    )
    return {
        "async": False,
        "items": [
            {
                "content": content,
                "context": "xiaoluozi 一轮对话",
                "document_id": turn.turn_id,
                "tags": [
                    f"turn_id:{turn.turn_id}",
                    "kind:turn",
                    f"channel:{turn.channel}",
                    f"agent:{turn.agent_id}",
                ],
                "metadata": {
                    "turn_id": turn.turn_id,
                    "agent_id": turn.agent_id,
                    "kind": "turn",
                },
            }
        ],
    }
