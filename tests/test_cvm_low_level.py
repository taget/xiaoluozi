import json

import httpx
import pytest

from tests.fakes import FakeLlm
from xiaoluozi.agents.cvm_low_level import CvmLowLevelAgent
from xiaoluozi.errors import ReplyError
from xiaoluozi.knot_mcp import KNOWLEDGE_UUID, SEARCH_DOMAIN, KnotMcp, format_knowledge, search_keywords

_CHUNK = json.dumps(
    [{"chunk_title": "子机自动拉起", "chunk_content": "先检查 shutdown 文件。"}],
    ensure_ascii=False,
)


def _handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert request.headers["X-knot-api-token"] == "token-test"
    assert request.headers["X-knot-knowledge-uuids"] == KNOWLEDGE_UUID
    method = body["method"]
    if method == "initialize":
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}},
            headers={"mcp-session-id": "session-1"},
        )
    if method == "notifications/initialized":
        assert request.headers["Mcp-Session-Id"] == "session-1"
        return httpx.Response(202)
    assert method == "tools/call"
    arguments = body["params"]["arguments"]
    assert arguments["knowledge_uuid"] == KNOWLEDGE_UUID
    assert arguments["search_domain"] == SEARCH_DOMAIN
    assert arguments["query"] == "子机为什么会被自动拉起？"
    assert arguments["keyword"] == "子机为什么会被自动拉起"
    text = json.dumps(
        {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": _CHUNK}]}},
        ensure_ascii=False,
    )
    return httpx.Response(200, content=text.encode(), headers={"content-type": "application/json"})


def test_mcp_search_sends_the_knowledge_uuid_and_formats_the_chunk():
    found = KnotMcp("token-test", transport=httpx.MockTransport(_handler)).search(
        "子机为什么会被自动拉起？",
        search_keywords("子机为什么会被自动拉起？"),
    )

    assert found == "【子机自动拉起】\n先检查 shutdown 文件。"


def test_an_empty_chunk_list_is_not_material():
    assert format_knowledge("[]") == ""
    assert search_keywords("子机，自动拉起。") == "子机;自动拉起"


def test_a_missing_token_does_not_search():
    def search(message):
        raise AssertionError(message)

    agent = CvmLowLevelAgent(FakeLlm(), env={"KNOT_API_TOKEN": "  "}, search=search)

    with pytest.raises(ReplyError, match="KNOT_API_TOKEN"):
        agent.handle("子机为什么会被自动拉起？")


def test_retrieved_excerpts_are_given_to_the_model_after_the_question():
    llm = FakeLlm("先看 shutdown 文件。")

    def search(message):
        assert message == "子机为什么会被自动拉起？"
        return "【子机自动拉起】\n先检查 shutdown 文件。"

    agent = CvmLowLevelAgent(
        llm,
        env={"KNOT_API_TOKEN": "token-test"},
        search=search,
    )

    assert agent.handle("子机为什么会被自动拉起？", context="上次问过拉起", intent="在提问") == "先看 shutdown 文件。"
    call = llm.calls[0]
    assert call["system"] == agent.system
    assert call["remember"] is False
    assert call["recall_query"] == "子机为什么会被自动拉起？"
    question_at = call["message"].index("用户问题：子机为什么会被自动拉起？")
    material_at = call["message"].index("知识库检索结果：")
    assert question_at < material_at
    assert "先检查 shutdown 文件。" in call["message"][material_at:]
    assert "上次问过拉起" in call["message"]


def test_no_match_is_returned_without_calling_the_model():
    llm = FakeLlm("不该出现。")
    agent = CvmLowLevelAgent(llm, env={"KNOT_API_TOKEN": "token-test"}, search=lambda message: "")

    assert agent.handle("完全无关的一句话") == "知识库里没有查到相关记录。"
    assert llm.calls == []
