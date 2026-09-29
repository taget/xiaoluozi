import json

from tests.fakes import FakeModel, SpyAgent
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router


def _registry():
    chat = SpyAgent("chat", "日常对话。没有更合适的专职代理时，用这个兜底。")
    notes = SpyAgent("notes", "把一句话记成备忘。")
    return Registry([chat, notes]), chat, notes


def _prompt_text(messages):
    return "\n".join(message["content"] for message in messages)


def test_valid_route_json_selects_that_agent_and_does_not_run_it():
    registry, chat, notes = _registry()
    model = FakeModel([json.dumps({"agent_id": "notes", "reason": "用户要记东西"}, ensure_ascii=False)])
    decision = Router(model, registry).route("帮我记一下买牛奶")

    assert decision.agent_id == "notes"
    assert decision.reason == "用户要记东西"
    assert chat.handled == []
    assert notes.handled == []
    prompt = _prompt_text(model.calls[0])
    assert "notes" in prompt
    assert "把一句话记成备忘。" in prompt
    assert "chat" in prompt


def test_malformed_route_json_falls_back_to_chat():
    registry, chat, notes = _registry()
    model = FakeModel(["我选 notes，因为要记东西"])
    decision = Router(model, registry).route("帮我记一下")

    assert decision.agent_id == "chat"
    assert "回退" in decision.reason
    assert chat.handled == []
    assert notes.handled == []


def test_unknown_agent_id_falls_back_to_chat():
    registry, chat, notes = _registry()
    model = FakeModel([json.dumps({"agent_id": "ghost", "reason": "猜的"}, ensure_ascii=False)])
    decision = Router(model, registry).route("你好")

    assert decision.agent_id == "chat"
    assert "回退" in decision.reason
    assert "ghost" in decision.reason
    assert chat.handled == []
    assert notes.handled == []
