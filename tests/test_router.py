from tests.fakes import FakeModel, SpyAgent
from xiaoluozi.registry import Registry
from xiaoluozi.router import LAYA_MAX_TOKENS, Router, laya_request_tokens


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


def test_laya_receives_every_enabled_agent(capsys):
    registry = Registry(
        [
            SpyAgent("chat", "日常对话。"),
            SpyAgent("qa", "回答问题。"),
            SpyAgent("cvm", "处理 CVM 运营。"),
        ]
    )
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "cvm"},
                "intent": {"type": "choice", "choice": "ask"},
            }
        ]
    )
    Router(model, registry, selectable=["chat", "qa", "cvm"]).route("查询北京库存")

    criteria = model.calls[0]["questions"]["agent_id"]["criteria"]
    state = model.calls[0]["state"]
    for agent_id in ("chat", "qa", "cvm"):
        assert agent_id in criteria
        assert f"- {agent_id}：" in state
    assert "路由候选 chat、qa、cvm" in capsys.readouterr().err


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


def test_oversized_context_is_compressed_before_laya(capsys):
    registry, _chat, _notes = _registry()
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "notes"}}])
    history = "最近对话：\n" + "\n".join(
        f"网页 / 用户：旧{index}" + ("旧" * 3000) + f"\n网页 / 小落子：早{index}" for index in range(6)
    )
    history += "\n网页 / 用户：新对话唯一标记\n网页 / 小落子：留下这句。"
    recall = "相关记忆：\n" + ("记忆" * 20000)
    context = f"{history}\n\n{recall}"

    Router(model, registry).route("查询北京库存", context)

    state = model.calls[0]["state"]
    questions = model.calls[0]["questions"]
    assert laya_request_tokens(state, questions) <= LAYA_MAX_TOKENS
    assert "用户问题：查询北京库存" in state
    assert "新对话唯一标记" in state
    assert "- notes：" in state
    assert "记忆" * 20000 not in state
    assert "已省略" in state
    assert "路由上下文已压缩" in capsys.readouterr().err


def test_unknown_agent_id_falls_back_to_chat():
    registry, chat, notes = _registry()
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "ghost"}}])
    decision = Router(model, registry).route("你好")

    assert decision.agent_id == "chat"
    assert "回退" in decision.reason
    assert "ghost" in decision.reason
    assert chat.handled == []
    assert notes.handled == []
