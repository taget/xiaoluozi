from tests.fakes import FakeLlm, FakeMemory, FakeModel, SpyAgent
from xiaoluozi.history import History
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.errors import MemoryError, ModelError, ModelNotConfigured, ReplyError
from xiaoluozi.loop import Loop, Trace
from xiaoluozi.registry import Registry
from xiaoluozi.router import INTENT_UNKNOWN, LAYA_MAX_TOKENS, Router, laya_request_tokens


def _route_answer(agent="chat", intent="decide"):
    return {
        "agent_id": {"type": "choice", "choice": agent},
        "intent": {"type": "choice", "choice": intent},
    }


def _loop(model, memory, llm=None, *, model_configured=True, history=None, decision_limit=10):
    llm = llm or FakeLlm("带伞。")
    registry = Registry([ChatAgent(llm)])
    return Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=memory,
        model_configured=model_configured,
        history=history,
        decision_limit=decision_limit,
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
    assert "这次没有找到专职代理" not in llm.calls[0]["system"]
    turn = memory.turns[0]
    assert turn.user_message == "今天要不要出门"
    assert turn.agent_id == "chat"
    assert turn.reason == ChatAgent.description
    assert turn.reply == "带伞。"
    assert turn.cognition == "在拿主意"
    logged = capsys.readouterr().err
    assert "回路开始 今天要不要出门" in logged
    assert "决策依赖\n今天要不要出门" in logged
    assert logged.index("决策依赖") < logged.index("路由决定")
    assert "上下文记忆 agent_id=chat\n上次说要出门" in logged
    assert "回路意图 在拿主意" in logged
    assert "回路回复 agent_id=chat 带伞。" in logged
    assert f"选用 chat。依据：{ChatAgent.description}" in logged
    assert f"回路写入 turn_id={turn.turn_id} saved=true" in logged


def test_missing_specialist_gives_laya_to_chat():
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "none"},
                "intent": {"type": "choice", "choice": "ask"},
            }
        ]
    )
    llm = FakeLlm("我先回答能说的部分。")
    result = _loop(model, FakeMemory(), llm).handle("帮我看看这个冷门问题")

    system = llm.calls[0]["system"]
    assert "这次没有找到专职代理" in system
    assert '"choice": "none"' in system
    assert result.text == "我先回答能说的部分。\n\n选用 chat。依据：没有合适的代理，已回退到 chat。"
    assert "choice" not in result.text


def test_a_later_chat_turn_drops_the_fallback_note():
    model = FakeModel(
        [
            {"agent_id": {"type": "choice", "choice": "none"}},
            {"agent_id": {"type": "choice", "choice": "chat"}},
        ]
    )
    llm = FakeLlm("在的。")
    loop = _loop(model, FakeMemory(), llm)

    loop.handle("随便说说")
    loop.handle("在吗")

    assert "这次没有找到专职代理" in llm.calls[0]["system"]
    assert "这次没有找到专职代理" not in llm.calls[1]["system"]


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
    assert memory.agent_ids == ["notes"]


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
    streamed = list(_loop(FakeModel([_route_answer()]), FakeMemory(memories=[memory_text]), FakeLlm("带伞。")).stream("今天要不要出门"))
    context_line = next(line for item in streamed if isinstance(item, Trace) and item.title == "代理入参" for line in item.lines if line.startswith("上下文："))
    laya_lines = "\n".join(line for item in streamed if isinstance(item, Trace) and item.title == "laya 入参" for line in item.lines)
    assert "共 20000 字" in context_line
    assert memory_text not in context_line
    assert ChatAgent.description not in laya_lines


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
    streamed = [item for item in loop.stream("嗯") if isinstance(item, Trace)]
    assert streamed[0].title == "laya"
    assert "没有再问" in streamed[0].lines[0]
    assert len(model.calls) == 1


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
    assert "查询北京库存" not in model.calls[1]["state"]


def test_revise_context_is_what_laya_and_the_agent_see():
    class Revising(Loop):
        def _revise_context(self, message, context):
            return "只留这一句。"

    model = FakeModel([_route_answer()])
    llm = FakeLlm("带伞。")
    memory = FakeMemory(memories=["上次说要出门"])
    base = _loop(model, memory, llm)
    loop = Revising(
        registry=base.registry,
        router=base.router,
        model=base.model,
        memory=base.memory,
        history=History(None),
    )
    loop.history.append(
        channel="web",
        agent_id="chat",
        user_message="昨天出门了",
        reply="带了伞。",
        shown="带了伞。",
        note=None,
    )

    loop.handle("今天呢")

    assert "只留这一句。" not in model.calls[0]["state"]
    assert "用户问题：今天呢" in model.calls[0]["state"]
    assert "上次说要出门" not in model.calls[0]["state"]
    assert "当前上下文：\n只留这一句。" in llm.calls[0]["message"]


def test_decision_queue_keeps_items_until_it_is_full():
    model = FakeModel([_route_answer(), _route_answer(intent="ask"), _route_answer()])
    memory = FakeMemory()
    loop = _loop(model, memory, decision_limit=2)

    loop.handle("今天出门吗")
    assert loop.refresh_decisions("chat") is False
    assert memory.decision_batches == []
    assert loop.decision_at("chat", 0).message == "今天出门吗"
    assert loop.decision_at("chat", 0).agent_id == "chat"
    assert loop.decision_at("chat", 0).intent == "在拿主意"

    loop.handle("明天呢")

    assert memory.decision_batches[0][0].message == "今天出门吗"
    assert memory.decision_batches[0][1].intent == "在提问"
    try:
        loop.decision_at("chat", 0)
    except IndexError as exc:
        assert "没有第 0 条" in str(exc)
    else:
        raise AssertionError("a flushed queue must be empty")

    loop.handle("后天呢")
    assert loop.decision_at("chat", 0).message == "后天呢"
    assert len(memory.decision_batches) == 1


def test_full_decision_queue_stays_when_memory_rejects_it():
    class Rejecting(FakeMemory):
        def retain_decisions(self, decisions):
            raise MemoryError("队列没写上")

    loop = _loop(FakeModel([_route_answer()]), Rejecting(), decision_limit=1)

    result = loop.handle("今天出门吗")

    assert result.saved is True
    assert loop.decision_at("chat", 0).message == "今天出门吗"
    assert loop.refresh_decisions("chat") is False


def test_each_agent_keeps_its_own_decision_queue():
    model = FakeModel([_route_answer("chat"), _route_answer("qa"), _route_answer("chat")])
    memory = FakeMemory()
    chat = SpyAgent("chat", "日常对话。")
    qa = SpyAgent("qa", "回答问题。")
    registry = Registry([chat, qa])
    loop = Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=memory,
        decision_limit=2,
    )

    loop.handle("今天出门吗")
    loop.handle("为什么要带伞")

    assert loop.decision_at("chat", 0).message == "今天出门吗"
    assert loop.decision_at("qa", 0).message == "为什么要带伞"
    assert memory.decision_batches == []

    loop.handle("明天呢")

    assert [item.agent_id for item in memory.decision_batches[0]] == ["chat", "chat"]
    assert loop.decision_at("qa", 0).message == "为什么要带伞"
    try:
        loop.decision_at("chat", 0)
    except IndexError as exc:
        assert "chat" in str(exc)
    else:
        raise AssertionError("only the full agent queue is cleared")


def test_repeated_decision_stays_out_of_the_queue():
    model = FakeModel([_route_answer(), _route_answer()])
    loop = _loop(model, FakeMemory())

    loop.handle("今天出门吗")
    loop.handle("明天呢")

    assert loop.decision_at("chat", 0).message == "今天出门吗"
    try:
        loop.decision_at("chat", 1)
    except IndexError:
        pass
    else:
        raise AssertionError("the same decision must not be queued twice")


def test_failed_route_reuses_the_latest_decision_without_enqueue():
    model = FakeModel([_route_answer(), ModelError("连不上模型服务。")])
    llm = FakeLlm("带伞。")
    loop = _loop(model, FakeMemory(), llm)

    loop.handle("今天出门吗")
    result = loop.handle("明天呢")

    assert result.text.startswith("带伞。")
    assert "选用 chat。" in result.text
    assert loop.decision_at("chat", 0).message == "今天出门吗"
    try:
        loop.decision_at("chat", 1)
    except IndexError:
        pass
    else:
        raise AssertionError("a reused decision must not be queued")
    assert "明天呢" in llm.calls[1]["message"]


def test_stream_yields_pieces_and_handle_joins_the_same_reply():
    model = FakeModel([_route_answer()])
    llm = FakeLlm("带伞。", pieces=["带", "伞。"])
    memory = FakeMemory()
    loop = _loop(model, memory, llm)

    streamed = list(loop.stream("今天要不要出门"))
    traces = [item for item in streamed if isinstance(item, Trace)]
    text = [item for item in streamed if isinstance(item, str)]

    assert [item.title for item in traces] == ["laya 入参", "laya 返回", "选用代理", "代理入参", "代理出参"]
    assert text == ["带", "伞。"]
    assert streamed[-1].text == f"带伞。\n\n选用 chat。依据：{ChatAgent.description}"
    assert streamed[-1].saved is True
    joined = _loop(FakeModel([_route_answer()]), FakeMemory(), FakeLlm("带伞。", pieces=["带", "伞。"])).handle(
        "今天要不要出门"
    )
    assert joined.text == streamed[-1].text


def test_decision_queue_limit_must_be_positive():
    try:
        _loop(FakeModel([]), FakeMemory(), decision_limit=0)
    except ValueError as exc:
        assert "至少是 1" in str(exc)
    else:
        raise AssertionError("a zero-length queue must be refused")


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
    assert "今天要不要出门" not in state
    assert "带伞" not in state
    assert "上次说要出门" not in state
    assert "明天呢" in llm.calls[1]["message"]
    assert "最近对话（chat）" in llm.calls[1]["message"]
    assert "网页 / 用户：今天要不要出门" in llm.calls[1]["message"]
    assert "上次说要出门" in llm.calls[1]["message"]
    assert memory.agent_ids == ["chat", "chat"]
    turns = history.turns()
    assert [turn.channel for turn in turns] == ["web", "weixin"]
    assert turns[1].user_message == "明天呢"
    assert memory.turns[1].channel == "weixin"


class _Voice:
    def __init__(self, agent_id, description, text):
        self.id = agent_id
        self.description = description
        self.text = text
        self.consultable = True
        self.seen = []
        self.contexts = []

    def handle(self, message, *, context="", intent=""):
        self.seen.append(message)
        self.contexts.append(context)
        return self.text

    def stream(self, message, *, context="", intent=""):
        yield self.handle(message, context=context, intent=intent)


def test_consultants_are_combined_into_one_reply_and_keep_their_own_text():
    llm = FakeLlm("合成后的回答。")
    kb = _Voice("kb", "笔记。", "笔记里有 shutdown。")
    qa = _Voice("qa", "问答。", "先看 shutdown。")
    registry = Registry([ChatAgent(llm), kb, qa])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "kb", "confidence": 0.9},
                "intent": {"type": "choice", "choice": "ask"},
                "consultant_1": {"type": "choice", "choice": "qa"},
                "consultant_2": {"type": "choice", "choice": "none"},
            }
        ]
    )
    history = History(None)
    result = Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=FakeMemory(),
        history=history,
    ).handle("子机为什么拉起")

    assert result.text == "合成后的回答。\n\n选用 kb。依据：笔记。\n参考了 qa。"
    assert history.latest().parts == (("kb", "笔记里有 shutdown。"), ("qa", "先看 shutdown。"))
    assert "笔记里有 shutdown" in llm.calls[-1]["message"]
    assert "先看 shutdown" in llm.calls[-1]["message"]
    assert kb.seen == ["子机为什么拉起"]


def test_a_late_consultant_is_dropped_and_the_finished_answer_is_kept():
    import time

    class _Slow(_Voice):
        def stream(self, message, *, context="", intent=""):
            time.sleep(1)
            yield "晚了"

    llm = FakeLlm("不该合成。")
    kb = _Voice("kb", "笔记。", "笔记里有。")
    qa = _Slow("qa", "问答。", "晚了")
    registry = Registry([ChatAgent(llm), kb, qa])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "kb", "confidence": 1},
                "consultant_1": {"type": "choice", "choice": "qa"},
            }
        ]
    )
    result = Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=FakeMemory(),
        history=History(None),
        agent_timeout=0.4,
        round_timeout=0.4,
    ).handle("查一下")

    assert result.text.startswith("笔记里有。")
    assert "晚了" not in result.text
    assert llm.calls == []


def test_the_same_agent_keeps_context_inside_one_conversation():
    model = FakeModel([_route_answer(), _route_answer(), _route_answer()])
    llm = FakeLlm("好。")
    loop = _loop(model, FakeMemory(), llm, history=History(None))

    loop.handle("第一句", conversation="web-a")
    loop.handle("第二句", conversation="web-b")
    loop.handle("第三句", conversation="web-a")

    assert "第一句" not in llm.calls[1]["message"]
    assert "第一句" in llm.calls[2]["message"]
    assert "第二句" not in llm.calls[2]["message"]


def test_a_partial_consultant_is_not_treated_as_finished():
    import time

    class _Partial(_Voice):
        def stream(self, message, *, context="", intent=""):
            yield "半截"
            time.sleep(0.45)
            yield "后半"

    llm = FakeLlm("不该合成。")
    kb = _Voice("kb", "笔记。", "笔记里有。")
    qa = _Partial("qa", "问答。", "后半")
    registry = Registry([ChatAgent(llm), kb, qa])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "kb", "confidence": 1},
                "consultant_1": {"type": "choice", "choice": "qa"},
            }
        ]
    )
    result = Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=FakeMemory(),
        history=History(None),
        agent_timeout=0.2,
        round_timeout=2,
    ).handle("查一下")

    assert result.text.startswith("笔记里有。")
    assert "半截" not in result.text
    assert "后半" not in result.text
    assert llm.calls == []


def test_failed_route_does_not_reuse_another_conversation():
    model = FakeModel([_route_answer(), ModelError("连不上模型服务。"), ModelError("连不上模型服务。")])
    llm = FakeLlm("带伞。")
    loop = _loop(model, FakeMemory(), llm, history=History(None))

    loop.handle("今天出门吗", conversation="web-a")
    try:
        loop.handle("明天呢", conversation="web-b")
    except ModelError as exc:
        assert "连不上" in str(exc)
    else:
        raise AssertionError("another conversation must not inherit the agent")

    result = loop.handle("后天呢", conversation="web-a")

    assert result.text.startswith("带伞。")
    assert "选用 chat。" in result.text
    assert loop.decision_at("chat", 0).message == "今天出门吗"
    try:
        loop.decision_at("chat", 1)
    except IndexError:
        pass
    else:
        raise AssertionError("a reused decision must not be queued")
    assert len(llm.calls) == 2


def test_team_mode_delegates_to_read_only_agents_and_keeps_their_context_narrow():
    import json

    class _Planner:
        def __init__(self):
            self.calls = []

        def answer(self, system, message, tools=None, env=None, remember=True, recall_query="", delegate=None):
            self.calls.append({"system": system, "message": message, "tools": list(tools or [])})
            names = [item["function"]["name"] for item in tools or []]
            assert "Delegate" in names
            self.refused = delegate(
                json.dumps({"agent": "wxwork", "task": "发一条", "hypothesis": "能发出去"})
            )
            self.self_call = delegate(
                json.dumps({"agent": "chat", "task": "自己再答", "hypothesis": "主代理能委派自己"})
            )
            self.child = delegate(
                json.dumps(
                    {
                        "agent": "kb",
                        "task": "查 shutdown",
                        "hypothesis": "笔记里有原因",
                        "evidence": "用户说子机拉起失败",
                    }
                )
            )
            for index in range(3):
                delegate(
                    json.dumps({"agent": "kb", "task": f"第{index}次", "hypothesis": "还要核对"})
                )
            self.blocked = delegate(
                json.dumps({"agent": "kb", "task": "超额", "hypothesis": "不该再查"})
            )
            return "笔记里的原因是 shutdown。"

    planner = _Planner()
    kb = _Voice("kb", "笔记。", "笔记里有 shutdown。")
    qa = _Voice("qa", "问答。", "不该并行。")
    wx = _Voice("wxwork", "企业微信。", "不该发。")
    wx.consultable = False
    wx.exclusive = True
    registry = Registry([ChatAgent(planner), kb, qa, wx])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "chat", "confidence": 1},
                "intent": {"type": "choice", "choice": "ask"},
                "consultant_1": {"type": "choice", "choice": "qa"},
            }
        ]
    )
    history = History(None)
    history.append(
        channel="web",
        agent_id="chat",
        user_message="上一句",
        reply="主代理的私有上下文",
        shown="主代理的私有上下文",
        note=None,
    )
    result = Loop(
        registry=registry,
        router=Router(model, registry),
        model=model,
        memory=FakeMemory(),
        history=history,
    ).handle("子机为什么拉起", mode="team")

    assert "consultant_1" not in model.calls[0]["questions"]
    assert "可调用：" in planner.calls[0]["system"]
    assert "主代理的私有上下文" in planner.calls[0]["message"]
    assert "不能自动调用" in planner.refused
    assert "不能委派给自己" in planner.self_call
    assert planner.blocked == "这一轮的委派已经用完。"
    assert wx.seen == []
    assert qa.seen == []
    assert len(kb.seen) == 4
    assert all("子任务：" in item and "不要调度其他代理" in item for item in kb.seen)
    assert all("主代理的私有上下文" not in item for item in kb.seen)
    assert all("主代理的私有上下文" not in item for item in kb.contexts)
    assert kb.seen[0].startswith("用户问题：子机为什么拉起")
    assert result.text.startswith("笔记里的原因是 shutdown。")
    assert "参考了 kb。" in result.text
    assert "wxwork" not in result.text.split("参考了", 1)[-1]
    parts = history.latest().parts
    assert ("kb", "笔记里有 shutdown。") in parts
    assert parts[-1][0] == "chat"
