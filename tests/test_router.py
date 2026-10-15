from tests.fakes import FakeModel, SpyAgent
from xiaoluozi.registry import Registry
from xiaoluozi.router import LAYA_MAX_TOKENS, Router, laya_request_tokens, mentioned_agent, named_agent


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
    assert decision.laya == ""
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
    assert "用户点名了已启用的代理 id 时，必须选那个代理。" in question["instructions"]
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
    assert '"choice": "none"' in decision.laya
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


def test_a_named_agent_outranks_laya(capsys):
    registry = Registry(
        [
            SpyAgent("chat", "日常对话。"),
            SpyAgent("qa", "回答问题。"),
            SpyAgent("kb", "检索知识库。"),
        ]
    )
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "chat"},
                "intent": {"type": "choice", "choice": "ask"},
            }
        ]
    )
    decision = Router(model, registry, selectable=["chat", "qa", "kb"]).route(
        "使用 kb agent，看看现在 kb 有哪些索引？"
    )

    assert decision.agent_id == "kb"
    assert decision.intent == "在提问"
    assert decision.reason == "用户点名了 kb。"
    assert decision.laya == ""
    assert "必须选 kb，优先级最高。" in model.calls[0]["state"]
    logged = capsys.readouterr().err
    assert "用户点名 agent_id=kb" in logged
    assert "路由决定 agent_id=kb" in logged


def test_an_underscored_name_is_not_shortened_to_cvm():
    assert named_agent("使用 cvm_low_level，看看子机拉起", ["cvm", "cvm_low_level"]) == "cvm_low_level"


def test_a_later_positive_cue_wins_over_an_earlier_one():
    registry = Registry([SpyAgent("chat", "日常对话。"), SpyAgent("kb", "检索知识库。")])
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "chat"}}])
    decision = Router(model, registry).route("不要用 chat，用 kb")

    assert decision.agent_id == "kb"
    assert decision.reason == "用户点名了 kb。"
    assert decision.laya == ""


def test_naming_two_agents_without_a_cue_keeps_laya_choice():
    registry = Registry([SpyAgent("chat", "日常对话。"), SpyAgent("kb", "检索知识库。")])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "chat"},
                "intent": {"type": "choice", "choice": "ask"},
            }
        ]
    )
    decision = Router(model, registry).route("chat 和 kb 有什么区别")

    assert decision.agent_id == "chat"
    assert decision.intent == "在提问"
    assert "点名" not in model.calls[0]["state"]


def test_unknown_agent_id_falls_back_to_chat():
    registry, chat, notes = _registry()
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "ghost"}}])
    decision = Router(model, registry).route("你好")

    assert decision.agent_id == "chat"
    assert "回退" in decision.reason
    assert "ghost" in decision.reason
    assert "ghost" in decision.laya
    assert chat.handled == []
    assert notes.handled == []


def test_an_at_mention_skips_laya():
    registry = Registry(
        [
            SpyAgent("chat", "日常对话。"),
            SpyAgent("wxwork", "企业微信。"),
            SpyAgent("cvm", "运营。"),
            SpyAgent("cvm_low_level", "底层。"),
        ]
    )
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "chat"}}])
    selectable = ["chat", "wxwork", "cvm", "cvm_low_level"]

    decision = Router(model, registry, selectable=selectable).route("@wxwork 查今天的日程")

    assert decision.agent_id == "wxwork"
    assert decision.reason == "用户用 @ 指定了 wxwork。"
    assert decision.intent == "没有识别出意图。"
    assert decision.laya == ""
    assert model.calls == []
    assert mentioned_agent("@cvm_low_level 看看拉起", ["cvm", "cvm_low_level"]) == "cvm_low_level"
    assert mentioned_agent("写给foo@chat", ["chat"]) == ""


def test_an_unknown_at_mention_still_asks_laya():
    registry = Registry([SpyAgent("chat", "日常对话。")])
    model = FakeModel(
        [{"agent_id": {"type": "choice", "choice": "chat"}, "intent": {"type": "choice", "choice": "greet"}}]
    )

    decision = Router(model, registry).route("@ghost 你好")

    assert decision.agent_id == "chat"
    assert model.calls
    assert "点名" not in model.calls[0]["state"]


def test_low_confidence_falls_back_and_does_not_call_consultants():
    kb = SpyAgent("kb", "笔记。")
    kb.consultable = True
    qa = SpyAgent("qa", "问答。")
    qa.consultable = True
    registry = Registry([SpyAgent("chat", "日常。"), kb, qa])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "kb", "confidence": 0.2},
                "consultant_1": {"type": "choice", "choice": "qa"},
            }
        ]
    )

    decision = Router(model, registry).route("这是什么")

    assert decision.agent_id == "chat"
    assert decision.consultants == ()
    assert decision.reason == "把握只有 0.2，已回退到 chat。"


def test_read_only_consultants_stay_and_a_side_effect_primary_runs_alone():
    kb = SpyAgent("kb", "笔记。")
    kb.consultable = True
    qa = SpyAgent("qa", "问答。")
    qa.consultable = True
    wxwork = SpyAgent("wxwork", "企业微信。")
    wxwork.exclusive = True
    registry = Registry([SpyAgent("chat", "日常。"), kb, qa, wxwork])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "kb", "confidence": 0.9},
                "consultant_1": {"type": "choice", "choice": "qa"},
                "consultant_2": {"type": "choice", "choice": "qa"},
            }
        ]
    )

    decision = Router(model, registry).route("笔记里怎么说")

    assert decision.agent_id == "kb"
    assert decision.consultants == ("qa",)
    criteria = model.calls[0]["questions"]["consultant_1"]["criteria"]
    assert "qa" in criteria
    assert "wxwork" not in criteria
    assert criteria["none"] == "不需要其他代理。"

    alone = Router(
        FakeModel(
            [
                {
                    "agent_id": {"type": "choice", "choice": "wxwork", "confidence": 0.9},
                    "consultant_1": {"type": "choice", "choice": "kb"},
                }
            ]
        ),
        registry,
    ).route("发一条消息")

    assert alone.agent_id == "wxwork"
    assert alone.consultants == ()


def test_team_routing_does_not_ask_for_consultants():
    kb = SpyAgent("kb", "笔记。")
    kb.consultable = True
    qa = SpyAgent("qa", "问答。")
    qa.consultable = True
    registry = Registry([SpyAgent("chat", "日常。"), kb, qa])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "kb", "confidence": 0.9},
                "consultant_1": {"type": "choice", "choice": "qa"},
            }
        ]
    )

    decision = Router(model, registry).route("笔记里怎么说", team=True)

    assert decision.agent_id == "kb"
    assert decision.consultants == ()
    assert "consultant_1" not in model.calls[0]["questions"]
