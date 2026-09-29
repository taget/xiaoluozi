import json

import httpx

from xiaoluozi.errors import MemoryError
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


def test_hindsight_retain_posts_four_tagged_items_sharing_turn_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"success": True, "bank_id": "bank-1", "items_count": 4, "async": False},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    HindsightMemory("http://hindsight.local", "bank-1", client=client).retain_turn(_turn())

    assert seen["url"] == "http://hindsight.local/v1/default/banks/bank-1/memories"
    body = seen["body"]
    assert body["async"] is False
    items = body["items"]
    assert len(items) == 4
    assert [item["metadata"]["kind"] for item in items] == [
        "user",
        "routing",
        "assistant",
        "cognition",
    ]
    assert {item["metadata"]["turn_id"] for item in items} == {"turn-1"}
    for item in items:
        assert "turn_id:turn-1" in item["tags"]
        assert item["document_id"] == "turn-1"
    assert items[0]["content"] == "今天要不要出门"
    assert "chat" in items[1]["content"]
    assert "日常对话" in items[1]["content"]
    assert items[2]["content"] == "带伞比较好。"
    assert items[3]["content"] == "用户决定出门要带伞。"


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
