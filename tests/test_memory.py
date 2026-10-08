import json

import httpx

from xiaoluozi.errors import MemoryError
from xiaoluozi.loop import QueuedDecision
from xiaoluozi.memory import HindsightMemory, TurnRecord


def _turn():
    return TurnRecord(
        turn_id="turn-1",
        user_message="今天要不要出门",
        agent_id="chat",
        reason="日常对话",
        reply="带伞比较好。",
        cognition="用户决定出门要带伞。",
    )


def test_hindsight_retain_posts_four_tagged_items_sharing_turn_id(capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"success": True, "bank_id": "bank-1", "items_count": 1, "async": False},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    HindsightMemory("http://hindsight.local", "bank-1", client=client).retain_turn(_turn())

    assert seen["url"] == "http://hindsight.local/v1/default/banks/bank-1/memories"
    body = seen["body"]
    assert body["async"] is False
    items = body["items"]
    assert len(items) == 1
    item = items[0]
    assert item["document_id"] == "turn-1"
    assert item["metadata"] == {"turn_id": "turn-1", "agent_id": "chat", "kind": "turn"}
    assert "turn_id:turn-1" in item["tags"]
    assert "用户: 今天要不要出门" in item["content"]
    assert "agent_id=chat" in item["content"]
    assert "reason=日常对话" in item["content"]
    assert "回复: 带伞比较好。" in item["content"]
    assert "认知: 用户决定出门要带伞。" in item["content"]
    logged = capsys.readouterr().err
    assert "记忆请求 POST http://hindsight.local/v1/default/banks/bank-1/memories" in logged
    assert "记忆响应 200" in logged
    assert "今天要不要出门" in logged


def test_hindsight_unset_does_not_call_the_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("unset Hindsight must not be called")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    memory = HindsightMemory("", "", client=client)
    try:
        memory.retain_turn(_turn())
    except MemoryError:
        pass
    else:
        raise AssertionError("unset Hindsight must fail the retain")


def test_a_full_decision_queue_is_one_memory_document():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"success": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    HindsightMemory("http://hindsight.local", "bank-1", client=client).retain_decisions(
        [
            QueuedDecision("今天出门吗", "chat", "日常对话", "在拿主意"),
            QueuedDecision("明天呢", "chat", "日常对话", "在提问"),
        ]
    )

    items = seen["body"]["items"]
    assert len(items) == 1
    assert items[0]["metadata"]["kind"] == "decision-queue"
    assert items[0]["metadata"]["agent_id"] == "chat"
    assert "agent:chat" in items[0]["tags"]
    assert "1. 用户: 今天出门吗" in items[0]["content"]
    assert "2. 用户: 明天呢" in items[0]["content"]
    assert items[0]["document_id"]
