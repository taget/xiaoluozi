from tests.fakes import FakeModel, SpyAgent
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router


def _registry():
    chat = SpyAgent("chat", "日常对话。没有更合适的专职代理时，用这个兜底。")
    notes = SpyAgent("notes", "把一句话记成备忘。")
    return Registry([chat, notes]), chat, notes


def test_valid_choice_selects_that_agent_and_does_not_run_it(capsys):
    registry, chat, notes = _registry()
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "notes", "confidence": 1}}])
    decision = Router(model, registry).route("帮我记一下买牛奶")

    assert decision.agent_id == "notes"
    assert decision.reason == "把一句话记成备忘。"
    assert chat.handled == []
    assert notes.handled == []
    question = model.calls[0]["questions"]["agent_id"]
    state = model.calls[0]["state"]
    assert "用户问题：帮我记一下买牛奶" in state
    assert "当前上下文：" in state
    assert "没有可用的上下文。" in state
    assert "- notes：把一句话记成备忘。" in state
    assert "- chat：" in state
    assert question["type"] == "choice"
    assert question["criteria"]["notes"] == "把一句话记成备忘。"
    assert question["criteria"]["none"] == "没有合适的代理。"
    assert "chat" in question["criteria"]
    logged = capsys.readouterr().err
    assert "路由决定 agent_id=notes" in logged
    assert "reason=把一句话记成备忘。" in logged


def test_malformed_route_falls_back_to_chat():
    registry, chat, notes = _registry()
    model = FakeModel(["我选 notes，因为要记东西"])
    decision = Router(model, registry).route("帮我记一下")

    assert decision.agent_id == "chat"
    assert "回退" in decision.reason
    assert chat.handled == []
    assert notes.handled == []


def test_one_enabled_agent_still_asks_laya_for_the_intent():
    chat = SpyAgent("chat", "日常对话。没有更合适的专职代理时，用这个兜底。")
    registry = Registry([chat])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "chat"},
                "intent": {"type": "choice", "choice": "greet"},
            }
        ]
    )
    decision = Router(model, registry).route("hello")

    assert decision.agent_id == "chat"
    assert decision.intent == "在寒暄"
    assert chat.handled == []
    assert model.calls[0]["questions"]["intent"]["criteria"]["greet"] == "在寒暄"
    assert "none" in model.calls[0]["questions"]["agent_id"]["criteria"]


def test_laya_state_includes_the_recalled_context():
    registry, _chat, _notes = _registry()
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "notes"}}])
    Router(model, registry).route("帮我记一下买牛奶", "用户出门要带伞")

    assert "用户出门要带伞" in model.calls[0]["state"]
    assert "没有可用的上下文。" not in model.calls[0]["state"]


def test_none_choice_uses_the_default_agent_and_keeps_the_intent():
    registry, chat, notes = _registry()
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "none"},
                "intent": {"type": "choice", "choice": "ask"},
            }
        ]
    )
    decision = Router(model, registry).route("随便说说")

    assert decision.agent_id == "chat"
    assert decision.intent == "在提问"
    assert "回退" in decision.reason
    assert chat.handled == []
    assert notes.handled == []


def test_unknown_agent_id_falls_back_to_chat():
    registry, chat, notes = _registry()
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "ghost"}}])
    decision = Router(model, registry).route("你好")

    assert decision.agent_id == "chat"
    assert "回退" in decision.reason
    assert "ghost" in decision.reason
    assert chat.handled == []
    assert notes.handled == []
