import json

from xiaoluozi.agents.cvm import CvmAgent
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.errors import ModelError
from xiaoluozi.loop import Loop
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router
from xiaoluozi.skills import SkillCatalog
from xiaoluozi.config import DEFAULT_TOOL_MAX_ROUNDS, Settings
from xiaoluozi.tools import finish_answer, run_tool
from tests.fakes import FakeMemory, FakeModel


class _Function:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.type = "function"
        self.function = _Function(name, arguments)


class _Message:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message):
        self.message = message


class _Response:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _Script:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, messages, tools):
        self.calls.append({"messages": messages, "tools": tools})
        if not self.script:
            raise AssertionError("unexpected model call")
        return self.script.pop(0)


class _Llm:
    def __init__(self, script):
        self.script = _Script(script)

    def answer(self, system, message, tools=None, env=None, remember=True):
        return finish_answer(
            self.script,
            [{"role": "system", "content": system}, {"role": "user", "content": message}],
            tools,
            env,
        )


def _bash_call(command, call_id="call-1"):
    return _Response(_Message(tool_calls=[_ToolCall(call_id, "Bash", json.dumps({"command": command}))]))


def _route_answer():
    return {
        "agent_id": {"type": "choice", "choice": "cvm"},
        "intent": {"type": "choice", "choice": "ask"},
    }


def test_bash_receives_dotenv_secrets_and_the_log_hides_them(capsys):
    result = run_tool(
        "Bash",
        json.dumps({"command": "printf '%s|%s' \"$YUNXIAO_SECRET_ID\" \"$YUNXIAO_API_URL\""}),
        env={
            "YUNXIAO_SECRET_ID": "sid-test-value",
            "YUNXIAO_SECRET_KEY": "",
            "YUNXIAO_API_URL": "http://yunxiao.test",
        },
    )
    blank = run_tool(
        "Bash",
        json.dumps({"command": "printf '%s' \"${YUNXIAO_TEST_BLANK-unset}\""}),
        env={"YUNXIAO_TEST_BLANK": "   "},
    )

    assert result == "sid-test-value|http://yunxiao.test"
    assert blank == "unset"
    logged = capsys.readouterr().err
    assert "sid-test-value" not in logged
    assert "[redacted]" in logged


def test_a_new_agent_only_receives_the_env_keys_it_names(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("EXTRA_TOKEN=extra-secret\nLLM_API_KEY=llm-secret\n", encoding="utf-8")

    class Extra:
        env_keys = ("EXTRA_TOKEN",)

    picked = Settings.load(env_file).pick(Extra.env_keys)
    result = run_tool("Bash", json.dumps({"command": "printf '%s' \"$EXTRA_TOKEN\""}), env=picked)

    assert list(picked) == ["EXTRA_TOKEN"]
    assert result == "extra-secret"


def test_yunxiao_ops_allows_bash():
    skill = SkillCatalog().load(("yunxiao-ops",))[0]
    assert skill.allowed_tools == ("Bash",)


def test_tool_call_runs_and_the_result_returns_to_the_model():
    script = _Script(
        [
            _bash_call("echo 落子"),
            _Response(_Message("水位正常。")),
        ]
    )

    assert finish_answer(script, [{"role": "user", "content": "看看库存"}], [{"type": "function"}]) == "水位正常。"

    assert len(script.calls) == 2
    assert script.calls[0]["tools"][0]["type"] == "function"
    follow = script.calls[1]["messages"]
    assert follow[1]["role"] == "assistant"
    assert follow[1]["tool_calls"][0]["function"]["name"] == "Bash"
    assert follow[2]["role"] == "tool"
    assert follow[2]["content"] == "落子"


def test_text_reply_does_not_run_a_tool():
    script = _Script([_Response(_Message("水位正常。"))])

    assert finish_answer(script, [{"role": "user", "content": "看看库存"}], [{"type": "function"}]) == "水位正常。"
    assert len(script.calls) == 1


def test_tool_rounds_stop_when_the_model_never_answers():
    script = _Script([_bash_call("echo 落子") for _ in range(DEFAULT_TOOL_MAX_ROUNDS + 1)])
    try:
        finish_answer(script, [{"role": "user", "content": "看看库存"}], [{"type": "function"}])
    except ModelError as exc:
        assert str(exc) == "工具调用没有在 8 次内结束。"
    else:
        raise AssertionError("unending tool calls must not become a reply")
    assert len(script.calls) == DEFAULT_TOOL_MAX_ROUNDS


def test_tool_round_limit_follows_the_configured_count():
    script = _Script([_bash_call("echo 落子") for _ in range(3)])
    try:
        finish_answer(script, [{"role": "user", "content": "看看库存"}], [{"type": "function"}], max_rounds=2)
    except ModelError as exc:
        assert str(exc) == "工具调用没有在 2 次内结束。"
    else:
        raise AssertionError("the configured round limit must stop the turn")
    assert len(script.calls) == 2


def test_loop_keeps_the_reply_after_the_tool_runs():
    llm = _Llm(
        [
            _bash_call("echo 落子"),
            _Response(_Message("水位正常。")),
        ]
    )
    agent = CvmAgent(llm, SkillCatalog().load(CvmAgent.skill_ids))
    registry = Registry([ChatAgent(llm), agent])
    memory = FakeMemory()
    result = Loop(
        registry=registry,
        router=Router(FakeModel([_route_answer()]), registry, selectable=["chat", "cvm"]),
        model=FakeModel([_route_answer()]),
        memory=memory,
    ).handle("看看广州库存")

    assert result.text.startswith("水位正常。\n\n选用 cvm。")
    assert memory.turns[0].reply == "水位正常。"
    assert llm.script.calls[1]["messages"][3]["content"] == "落子"
