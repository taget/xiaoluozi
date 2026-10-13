import json
import threading
import time

import pytest

from tests.fakes import FakeLlm, FakeMemory, FakeModel
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.agents.migrate import (
    DEFAULT_KNOT_API_URL,
    MigrateAgent,
    open_knot,
    split_knot_endpoint,
)
from xiaoluozi.errors import ReplyError
from xiaoluozi.loop import Loop
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router

_AGENT_ID = "687fb0de01614c5b84ba495919c5ff02"
_BASE = "http://knot.woa.com/apigw/api/v1/agents/agui"


def _sse(*parts: str) -> bytes:
    lines = []
    for part in parts:
        payload = json.dumps(
            {"type": "TEXT_MESSAGE_CONTENT", "rawEvent": {"content": part}},
            ensure_ascii=False,
        )
        lines.append(f"data: {payload}")
    lines.append("data: [DONE]")
    return ("\n".join(lines) + "\n").encode()


class _Conversation:
    def __init__(self, body: bytes):
        self.body = body
        self.requests = []

    def chat(self, req, writer):
        self.requests.append(req)
        writer.write(self.body)


class _Client:
    def __init__(self, body: bytes):
        self.body = body
        self.agent_ids = []
        self.conversation = _Conversation(body)

    def new_conversation(self, agent_id):
        self.agent_ids.append(agent_id)
        return self.conversation


def _opener(client: _Client):
    seen = {}

    def open_client(token, api_url):
        seen["token"] = token
        seen["api_url"] = api_url
        return client, _AGENT_ID

    open_client.seen = seen
    return open_client


def test_endpoint_stays_on_http_and_keeps_the_agent_id():
    base, agent_id = split_knot_endpoint(DEFAULT_KNOT_API_URL)

    assert base == _BASE
    assert agent_id == _AGENT_ID

    client, opened = open_knot("token-test", DEFAULT_KNOT_API_URL)
    try:
        assert opened == _AGENT_ID
        assert client._base_url == _BASE
    finally:
        client.close()


def test_a_missing_token_does_not_open_a_client():
    def open_client(token, api_url):
        raise AssertionError("should not open")

    agent = MigrateAgent(
        FakeLlm(),
        env={"KNOT_API_TOKEN": "  ", "KNOT_API_URL": DEFAULT_KNOT_API_URL},
        opener=open_client,
    )

    with pytest.raises(ReplyError, match="KNOT_API_TOKEN"):
        agent.handle("帮我做一份迁移方案")


def test_a_bad_url_is_refused_before_any_request():
    agent = MigrateAgent(FakeLlm(), env={"KNOT_API_TOKEN": "token-test", "KNOT_API_URL": "https://knot.woa.com"})

    with pytest.raises(ReplyError, match="agents/agui"):
        agent.handle("帮我做一份迁移方案")


def test_sse_text_is_joined_and_the_conversation_is_reused():
    client = _Client(_sse("可以迁。", "先看问卷。"))
    opener = _opener(client)
    agent = MigrateAgent(
        FakeLlm(),
        env={"KNOT_API_TOKEN": "token-test", "KNOT_API_URL": DEFAULT_KNOT_API_URL},
        opener=opener,
    )

    assert agent.handle("帮我做一份迁移方案", context="上次问过广州", intent="在提问") == "可以迁。先看问卷。"
    assert "".join(agent.stream("再补一版落地评估")) == "可以迁。先看问卷。"

    assert opener.seen == {"token": "token-test", "api_url": DEFAULT_KNOT_API_URL}
    assert client.agent_ids == [_AGENT_ID]
    assert [req.message for req in client.conversation.requests] == [
        "帮我做一份迁移方案",
        "再补一版落地评估",
    ]
    assert client.conversation.requests[0].model is None
    assert agent._llm.calls == []


def test_an_empty_knot_reply_is_refused():
    agent = MigrateAgent(
        FakeLlm(),
        env={"KNOT_API_TOKEN": "token-test", "KNOT_API_URL": DEFAULT_KNOT_API_URL},
        opener=_opener(_Client(b"data: [DONE]\n")),
    )

    with pytest.raises(ReplyError, match="没有返回内容"):
        agent.handle("帮我做一份迁移方案")


def test_a_knot_failure_does_not_call_the_local_model():
    class _Broken:
        def new_conversation(self, agent_id):
            return self

        def chat(self, req, writer):
            raise RuntimeError("boom")

    def open_client(token, api_url):
        return _Broken(), _AGENT_ID

    llm = FakeLlm("不该出现。")
    agent = MigrateAgent(
        llm,
        env={"KNOT_API_TOKEN": "token-test", "KNOT_API_URL": DEFAULT_KNOT_API_URL},
        opener=open_client,
    )

    with pytest.raises(ReplyError, match="Knot 调用失败"):
        agent.handle("帮我做一份迁移方案")
    assert llm.calls == []


def test_laya_can_select_migrate_without_calling_the_local_model():
    client = _Client(_sse("方案已整理。"))
    model = FakeModel([{"agent_id": {"type": "choice", "choice": "migrate"}, "intent": {"type": "choice", "choice": "ask"}}])
    llm = FakeLlm("不该出现。")
    agent = MigrateAgent(
        llm,
        env={"KNOT_API_TOKEN": "token-test", "KNOT_API_URL": DEFAULT_KNOT_API_URL},
        opener=_opener(client),
    )
    registry = Registry([ChatAgent(FakeLlm()), agent])
    result = Loop(
        registry=registry,
        router=Router(model, registry, selectable=["chat", "migrate"]),
        model=model,
        memory=FakeMemory(),
    ).handle("使用 migrate，帮我做一份 CVM 迁移方案")

    assert result.text.startswith("方案已整理。\n\n选用 migrate。")
    assert llm.calls == []
    assert client.conversation.requests[0].message == "使用 migrate，帮我做一份 CVM 迁移方案"


def test_a_worker_interrupt_is_raised_on_the_caller():
    class _Broken:
        def new_conversation(self, agent_id):
            return self

        def chat(self, req, writer):
            raise KeyboardInterrupt

    agent = MigrateAgent(
        FakeLlm(),
        env={"KNOT_API_TOKEN": "token-test", "KNOT_API_URL": DEFAULT_KNOT_API_URL},
        opener=lambda token, api_url: (_Broken(), _AGENT_ID),
    )

    with pytest.raises(KeyboardInterrupt):
        agent.handle("帮我做一份迁移方案")


def test_two_handles_do_not_talk_at_the_same_time():
    state = {"active": 0, "max": 0}
    gate = threading.Lock()

    class _Conv:
        def chat(self, req, writer):
            with gate:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            try:
                time.sleep(0.05)
                writer.write(_sse(req.message))
            finally:
                with gate:
                    state["active"] -= 1

    class _Client:
        def new_conversation(self, agent_id):
            return _Conv()

    agent = MigrateAgent(
        FakeLlm(),
        env={"KNOT_API_TOKEN": "token-test", "KNOT_API_URL": DEFAULT_KNOT_API_URL},
        opener=lambda token, api_url: (_Client(), _AGENT_ID),
    )
    errors = []

    def run(text):
        try:
            assert agent.handle(text) == text
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(text,)) for text in ("第一句", "第二句")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    assert state["max"] == 1
    assert not any(thread.is_alive() for thread in threads)
