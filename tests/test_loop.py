from tests.fakes import FakeLlm, FakeMemory, FakeModel, SpyAgent
from xiaoluozi.history import History
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.errors import MemoryError, ModelError, ModelNotConfigured, ReplyError
from xiaoluozi.loop import Loop
from xiaoluozi.registry import Registry
from xiaoluozi.router import INTENT_UNKNOWN, LAYA_MAX_TOKENS, Router, laya_request_tokens


def _route_answer(agent="chat", intent="decide"):
    return {
        "agent_id": {"type": "choice", "choice": agent},
        "intent": {"type": "choice", "choice": intent},
    }


def _loop(model, memory, llm=None, *, model_configured=True, history=None):
    llm = llm or FakeLlm("带伞。")
    registry = Registry([ChatAgent(llm)])
    return Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=memory,
        model_configured=model_configured,
        history=history,
    )


def test_loop_asks_laya_then_passes_context_and_intent_to_the_agent(capsys):
    model = FakeModel([_route_answer()])
    llm = FakeLlm("带伞。")
    memory = FakeMemory(memories=["上次说要出门"])
    result = _loop(model, memory, llm).handle("今天要不要出门")

    assert result.text == f"带伞。\n\n选用 chat。依据：{ChatAgent.description}"
    assert result.saved is True
    assert result.note is None
    assert len(model.calls) == 1
    state = model.calls[0]["state"]
    assert "用户问题：今天要不要出门" in state
    assert "没有可用的上下文。" in state
    assert "上次说要出门" not in state
    assert "- chat：" in state
    assert model.calls[0]["questions"]["agent_id"]["type"] == "choice"
    assert model.calls[0]["questions"]["intent"]["criteria"]["decide"] == "在拿主意"
    assert "上次说要出门" in llm.calls[0]["message"]
    assert "用户意图：在拿主意" in llm.calls[0]["message"]
    assert "用户问题：今天要不要出门" in llm.calls[0]["message"]
    turn = memory.turns[0]
    assert turn.user_message == "今天要不要出门"
    assert turn.agent_id == "chat"
    assert turn.reason == ChatAgent.description
    assert turn.reply == "带伞。"
    assert turn.cognition == "在拿主意"
    logged = capsys.readouterr().err
    assert "回路开始 今天要不要出门" in logged
    assert "回路意图 在拿主意" in logged
    assert "回路回复 agent_id=chat 带伞。" in logged
    assert f"选用 chat。依据：{ChatAgent.description}" in logged
    assert f"回路写入 turn_id={turn.turn_id} saved=true" in logged


def test_missing_intent_still_returns_the_reply():
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "chat"}}])
    llm = FakeLlm("带伞。")
    memory = FakeMemory()
    result = _loop(model, memory, llm).handle("今天要不要出门")

    assert result.text.startswith("带伞。\n\n选用 chat。依据：")
    assert result.saved is True
    assert memory.turns[0].reply == "带伞。"
    assert memory.turns[0].cognition == INTENT_UNKNOWN
    assert "用户意图：没有识别出意图。" in llm.calls[0]["message"]


def test_retain_failure_still_returns_the_reply():
    model = FakeModel([_route_answer()])
    memory = FakeMemory(error=MemoryError("Hindsight 连不上"))
    result = _loop(model, memory).handle("今天要不要出门")

    assert result.text.startswith("带伞。\n\n选用 chat。依据：")
    assert result.saved is False
    assert result.note
    assert memory.attempts == 1
    assert memory.turns == []


def test_reply_failure_is_not_retained():
    model = FakeModel([_route_answer()])
    memory = FakeMemory()

    try:
        _loop(model, memory, FakeLlm(error=ModelError("模型调用失败"))).handle("今天要不要出门")
    except ReplyError as exc:
        assert "模型调用失败" in str(exc)
    else:
        raise AssertionError("reply failure must surface")

    assert memory.attempts == 0
    assert len(model.calls) == 1


def test_route_call_failure_is_not_retained():
    model = FakeModel([ModelError("连不上模型服务。")])
    memory = FakeMemory()
    registry = Registry(
        [
            ChatAgent(FakeLlm()),
            SpyAgent("notes", "把一句话记成备忘。"),
        ]
    )
    loop = Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=memory,
    )

    try:
        loop.handle("你好")
    except ModelError as exc:
        assert "连不上模型服务" in str(exc)
    else:
        raise AssertionError("route failure must surface")

    assert memory.attempts == 0
    assert len(model.calls) == 1
    assert len(model.calls[0]["questions"]["agent_id"]["criteria"]) >= 2
    assert "intent" in model.calls[0]["questions"]


def test_chosen_agent_receives_the_context_and_intent():
    model = FakeModel([_route_answer("notes", "tell")])
    memory = FakeMemory(memories=["用户出门要带伞"])
    notes = SpyAgent("notes", "把一句话记成备忘。")
    registry = Registry([ChatAgent(FakeLlm()), notes])
    result = Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=memory,
    ).handle("帮我记一下")

    assert result.text == "spy-reply\n\n选用 notes。依据：把一句话记成备忘。"
    assert notes.requests == [
        {"message": "帮我记一下", "context": "用户出门要带伞", "intent": "在说一件事"}
    ]
    assert "用户问题：帮我记一下" in model.calls[0]["state"]
    assert "没有可用的上下文。" in model.calls[0]["state"]
    assert "用户出门要带伞" not in model.calls[0]["state"]
    assert memory.queries == ["帮我记一下"]


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


def test_long_recall_is_shortened_for_laya_and_kept_for_the_agent():
    memory_text = "甲" * 20000
    model = FakeModel([_route_answer()])
    llm = FakeLlm("带伞。")
    result = _loop(model, FakeMemory(memories=[memory_text]), llm).handle("今天要不要出门")

    state = model.calls[0]["state"]
    assert laya_request_tokens(state, model.calls[0]["questions"]) <= LAYA_MAX_TOKENS
    assert memory_text not in state
    assert memory_text in llm.calls[0]["message"]
    assert "今天要不要出门" in state
    assert result.saved is True


def test_ack_reuses_the_previous_agent_and_does_not_ask_laya():
    history = History(None)
    model = FakeModel([_route_answer("cvm", "ask"), _route_answer("chat")])
    cvm = SpyAgent("cvm", "处理 CVM。")
    registry = Registry([ChatAgent(FakeLlm("带伞。")), cvm])
    loop = Loop(
        registry=registry,
        router=Router(model, registry, selectable=["chat", "cvm"]),
        model=model,
        memory=FakeMemory(),
        history=history,
    )

    loop.handle("查询北京库存")
    result = loop.handle("好的。")

    assert len(model.calls) == 1
    assert "选用 cvm" in result.text
    assert "沿用上次的 cvm" in result.text
    assert cvm.requests[-1]["message"] == "好的。"
    assert history.latest().agent_id == "cvm"


def test_ack_with_business_words_still_asks_laya():
    history = History(None)
    model = FakeModel([_route_answer("cvm"), _route_answer("qa", "ask")])
    registry = Registry([ChatAgent(FakeLlm("带伞。")), SpyAgent("cvm", "处理 CVM。"), SpyAgent("qa", "回答问题。")])
    loop = Loop(
        registry=registry,
        router=Router(model, registry, selectable=["chat", "cvm", "qa"]),
        model=model,
        memory=FakeMemory(),
        history=history,
    )

    loop.handle("查询北京库存")
    loop.handle("确认库存")

    assert len(model.calls) == 2
    assert "用户问题：确认库存" in model.calls[1]["state"]
    assert "查询北京库存" in model.calls[1]["state"]


def test_web_and_weixin_share_the_same_recent_dialogue():
    history = History(None)
    model = FakeModel([_route_answer(), _route_answer(intent="ask")])
    llm = FakeLlm("带伞。")
    memory = FakeMemory(memories=["上次说要出门"])
    loop = _loop(model, memory, llm, history=history)

    loop.handle("今天要不要出门", channel="web")
    loop.handle("明天呢", channel="weixin")

    state = model.calls[1]["state"]
    assert "用户问题：明天呢" in state
    assert "今天要不要出门" in state
    assert "带伞" not in state
    assert "上次说要出门" not in state
    assert "明天呢" in llm.calls[1]["message"]
    assert "网页 / 用户：今天要不要出门" in llm.calls[1]["message"]
    assert "上次说要出门" in llm.calls[1]["message"]
    turns = history.turns()
    assert [turn.channel for turn in turns] == ["web", "weixin"]
    assert turns[1].user_message == "明天呢"
    assert memory.turns[1].channel == "weixin"
