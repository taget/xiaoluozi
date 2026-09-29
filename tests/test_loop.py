import json

from tests.fakes import FakeMemory, FakeModel
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.errors import MemoryError, ModelError, ModelNotConfigured, ReplyError
from xiaoluozi.loop import COGNITION_FAILED, Loop
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router


def _prompt_text(messages):
    return "\n".join(message["content"] for message in messages)


def _loop(model, memory, *, model_configured=True):
    registry = Registry([ChatAgent(model)])
    return Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=memory,
        model_configured=model_configured,
    )


def test_loop_order_is_route_then_reply_then_cognition_then_retain():
    model = FakeModel(
        [
            json.dumps({"agent_id": "chat", "reason": "日常对话"}, ensure_ascii=False),
            "带伞比较好。",
            "用户决定出门要带伞。",
        ]
    )
    memory = FakeMemory()
    result = _loop(model, memory).handle("今天要不要出门")

    assert result.text == "带伞比较好。"
    assert result.saved is True
    assert result.note is None
    assert len(model.calls) == 3
    route_prompt = _prompt_text(model.calls[0])
    reply_prompt = _prompt_text(model.calls[1])
    cognition_prompt = _prompt_text(model.calls[2])
    assert "chat" in route_prompt
    assert "agent_id" in route_prompt
    assert "今天要不要出门" in reply_prompt
    assert "带伞比较好。" in cognition_prompt
    assert "带伞比较好。" not in route_prompt
    assert len(memory.turns) == 1
    turn = memory.turns[0]
    assert turn.user_message == "今天要不要出门"
    assert turn.agent_id == "chat"
    assert turn.reason == "日常对话"
    assert turn.reply == "带伞比较好。"
    assert turn.cognition == "用户决定出门要带伞。"
    assert turn.turn_id


def test_cognition_failure_still_returns_the_reply_and_retains_a_failure_note():
    model = FakeModel(
        [
            json.dumps({"agent_id": "chat", "reason": "日常对话"}, ensure_ascii=False),
            "带伞比较好。",
            ModelError("认知服务超时"),
        ]
    )
    memory = FakeMemory()
    result = _loop(model, memory).handle("今天要不要出门")

    assert result.text == "带伞比较好。"
    assert result.saved is True
    assert memory.turns[0].reply == "带伞比较好。"
    assert memory.turns[0].cognition == COGNITION_FAILED
    assert memory.turns[0].user_message == "今天要不要出门"
    assert memory.turns[0].agent_id == "chat"


def test_retain_failure_still_returns_the_reply():
    model = FakeModel(
        [
            json.dumps({"agent_id": "chat", "reason": "日常对话"}, ensure_ascii=False),
            "带伞比较好。",
            "用户决定出门要带伞。",
        ]
    )
    memory = FakeMemory(error=MemoryError("Hindsight 连不上"))
    result = _loop(model, memory).handle("今天要不要出门")

    assert result.text == "带伞比较好。"
    assert result.saved is False
    assert result.note
    assert memory.attempts == 1
    assert memory.turns == []


def test_reply_failure_is_not_retained():
    model = FakeModel(
        [
            json.dumps({"agent_id": "chat", "reason": "日常对话"}, ensure_ascii=False),
            ModelError("模型调用失败"),
            "不该抽出认知",
        ]
    )
    memory = FakeMemory()

    try:
        _loop(model, memory).handle("今天要不要出门")
    except ReplyError as exc:
        assert "模型调用失败" in str(exc)
    else:
        raise AssertionError("reply failure must surface")

    assert memory.attempts == 0
    assert len(model.calls) == 2


def test_route_call_failure_is_not_retained():
    model = FakeModel([ModelError("连不上模型服务。")])
    memory = FakeMemory()

    try:
        _loop(model, memory).handle("你好")
    except ModelError as exc:
        assert "连不上模型服务" in str(exc)
    else:
        raise AssertionError("route failure must surface")

    assert memory.attempts == 0
    assert len(model.calls) == 1


def test_missing_model_does_not_invent_a_reply():
    model = FakeModel(["不该被调用"])
    memory = FakeMemory()

    try:
        _loop(model, memory, model_configured=False).handle("你好")
    except ModelNotConfigured:
        pass
    else:
        raise AssertionError("missing model must not succeed")

    assert model.calls == []
    assert memory.attempts == 0
