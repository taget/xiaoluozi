import json

import pytest

from tests.fakes import FakeLlm
from xiaoluozi.agents.knot import (
    VSTATION_URL,
    KnotAgent,
    knot_specs,
    resolve_knot_url,
    split_knot_endpoint,
)
from xiaoluozi.config import Settings
from xiaoluozi.model import ClosedLlm
from xiaoluozi.wiring import _registry

_VSTATION_ID = "dcfd1be40f2d430a98f689b9e96bd6c8"
_DISK_URL = "http://knot.woa.com/apigw/api/v1/agents/agui/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _sse(text: str) -> bytes:
    payload = json.dumps(
        {"type": "TEXT_MESSAGE_CONTENT", "rawEvent": {"content": text}},
        ensure_ascii=False,
    )
    return f"data: {payload}\ndata: [DONE]\n".encode()


class _Conversation:
    def __init__(self):
        self.requests = []

    def chat(self, req, writer):
        self.requests.append(req)
        writer.write(_sse("先看创建失败。"))


class _Client:
    def __init__(self):
        self.agent_ids = []
        self.conversation = _Conversation()

    def new_conversation(self, agent_id):
        self.agent_ids.append(agent_id)
        return self.conversation


def test_vstation_uses_its_own_endpoint():
    base, agent_id = split_knot_endpoint(VSTATION_URL)
    assert agent_id == _VSTATION_ID
    assert base == "http://knot.woa.com/apigw/api/v1/agents/agui"

    seen = {}
    client = _Client()

    def opener(token, api_url):
        seen["token"] = token
        seen["api_url"] = api_url
        return client, agent_id

    spec = next(item for item in knot_specs({}) if item.id == "vstation")
    agent = KnotAgent(FakeLlm(), env={"KNOT_API_TOKEN": "token-test"}, opener=opener, spec=spec)

    assert agent.handle("vstation 创建实例失败了") == "先看创建失败。"
    assert seen == {"token": "token-test", "api_url": VSTATION_URL}
    assert client.agent_ids == [_VSTATION_ID]
    assert agent._llm.calls == []


def test_an_endpoint_in_env_adds_a_knot_agent():
    env = {
        "KNOT_AGENT_DISK": _DISK_URL,
        "KNOT_AGENT_DISK_DESCRIPTION": "处理磁盘排障。",
    }

    specs = {spec.id: spec for spec in knot_specs(env)}

    assert specs["disk"].url == _DISK_URL
    assert specs["disk"].description == "处理磁盘排障。"
    assert specs["vstation"].url == VSTATION_URL
    assert "migrate" in specs


def test_a_new_knot_agent_needs_a_chinese_description():
    with pytest.raises(ValueError, match="KNOT_AGENT_DISK_DESCRIPTION"):
        knot_specs({"KNOT_AGENT_DISK": _DISK_URL})


def test_a_knot_agent_cannot_reuse_a_local_id():
    with pytest.raises(ValueError, match="chat"):
        knot_specs(
            {
                "KNOT_AGENT_CHAT": _DISK_URL,
                "KNOT_AGENT_CHAT_DESCRIPTION": "不该覆盖日常对话。",
            }
        )


def test_env_url_overrides_the_builtin_endpoint():
    spec = next(item for item in knot_specs({}) if item.id == "vstation")
    custom = "http://knot.example/apigw/api/v1/agents/agui/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    assert resolve_knot_url(spec, {"KNOT_AGENT_VSTATION": custom}) == custom
    assert resolve_knot_url(spec, {}) == VSTATION_URL


def test_registry_enables_a_knot_agent_declared_only_by_endpoint():
    settings = Settings(
        api_key="",
        base_url="http://example.test/llmproxy",
        model="laya",
        hindsight_base_url="",
        hindsight_bank_id="",
        llm_api_key="",
        llm_base_url="",
        llm_model="",
        laya_model="laya",
        enabled_agents=("chat", "disk"),
        default_agent="chat",
        weixin_enabled=False,
        weixin_base_url="https://ilinkai.weixin.qq.com",
        weixin_token="",
        weixin_account_id="default",
        dotenv={
            "KNOT_AGENT_DISK": _DISK_URL,
            "KNOT_AGENT_DISK_DESCRIPTION": "处理磁盘排障。",
        },
    )

    registry, selectable = _registry(settings, ClosedLlm())

    assert selectable == ["chat", "disk"]
    assert registry.get("disk").description == "处理磁盘排障。"
    assert registry.get("disk").spec.url == _DISK_URL
