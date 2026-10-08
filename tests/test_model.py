import json
import threading

import httpx
from hindsight_litellm import wrap_openai

from xiaoluozi.config import Settings
from xiaoluozi.errors import ModelError, ModelNotConfigured
from xiaoluozi.model import JevClient, SystemoneOpenAI
from xiaoluozi.wiring import build_loop


def test_jev_client_posts_systemone_and_returns_answers(capsys):
    seen = {}
    questions = {
        "is_urgent": {"type": "noul", "instructions": "Is this request urgent?"},
        "department": {
            "type": "choice",
            "instructions": "Which department should handle this request?",
            "criteria": {"billing": None, "support": None},
        },
    }
    state = "The customer says the invoice is wrong and asks for immediate help."

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"model": "jev-1.13.0", "answers": {"is_urgent": {"type": "noul", "noul": 0.99}}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = JevClient("secret-key", "http://v2.open.venus.oa.com/llmproxy", "jev-1.13.0", client=client)

    assert model.decide(state, questions) == {"is_urgent": {"type": "noul", "noul": 0.99}}
    assert seen["url"] == "http://v2.open.venus.oa.com/llmproxy/v1/systemone"
    assert seen["auth"] == "Bearer secret-key"
    assert seen["body"] == {"model": "jev-1.13.0", "state": state, "questions": questions}
    assert "messages" not in seen["body"]
    logged = capsys.readouterr().err
    assert "模型请求 POST http://v2.open.venus.oa.com/llmproxy/v1/systemone" in logged
    assert state in logged
    assert "模型响应 200" in logged
    assert "secret-key" not in logged


def test_systemone_base_url_is_not_extended():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"answers": {"is_urgent": {"type": "noul", "noul": 0.2}}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = JevClient(
        "secret-key",
        "https://v2.open.venus.woa.com/llmproxy/v1/systemone",
        "jev-1.13.0",
        client=client,
    )
    model.decide("你好", {"is_urgent": {"type": "noul", "instructions": "急吗？"}})

    assert seen["url"] == "https://v2.open.venus.woa.com/llmproxy/v1/systemone"


def test_blank_model_key_does_not_call_the_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank key must not call the model")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = JevClient("  ", "http://example.test", "jev-1.13.0", client=client)
    try:
        model.decide("你好", {"is_urgent": {"type": "noul", "instructions": "急吗？"}})
    except ModelNotConfigured:
        pass
    else:
        raise AssertionError("blank key must refuse")


def test_model_error_body_is_not_treated_as_a_reply(capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key secret-key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = JevClient("secret-key", "http://example.test/llmproxy", "jev-1.13.0", client=client)
    try:
        model.decide("你好", {"is_urgent": {"type": "noul", "instructions": "急吗？"}})
    except ModelError as exc:
        assert "401" in str(exc)
    else:
        raise AssertionError("HTTP failure must not become a reply")
    logged = capsys.readouterr().err
    assert "模型响应 401" in logged
    assert "secret-key" not in logged
    assert "[redacted]" in logged


def _wrapped_jev(handler, **wrap_kwargs):
    seen = {}

    def transport(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        seen["url"] = str(request.url)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(transport))
    model = JevClient("secret-key", "http://example.test/llmproxy", "jev-1.13.0", client=client)
    wrapped = wrap_openai(
        SystemoneOpenAI(model),
        hindsight_api_url="http://hindsight.local",
        bank_id="bank-1",
        **wrap_kwargs,
    )
    model.bind(wrapped)
    return model, wrapped, seen


def test_wrap_openai_puts_recalled_memory_into_the_systemone_state():
    model, wrapped, seen = _wrapped_jev(
        lambda request: httpx.Response(
            200, json={"answers": {"kind": {"type": "choice", "choice": "none"}}}
        ),
        store_conversations=False,
    )
    wrapped._recall_memories = lambda query, settings: "记得带伞"
    questions = {"kind": {"type": "choice", "criteria": {"none": "没有"}}}

    answers = model.decide("今天出门吗", questions)

    assert answers == {"kind": {"type": "choice", "choice": "none"}}
    assert seen["url"] == "http://example.test/llmproxy/v1/systemone"
    assert seen["body"]["state"] == "记得带伞\n\n今天出门吗"
    assert seen["body"]["questions"] == questions
    assert "messages" not in seen["body"]


def test_wrap_openai_stores_the_exchange_after_systemone():
    stored = {}
    model, wrapped, seen = _wrapped_jev(
        lambda request: httpx.Response(
            200, json={"answers": {"kind": {"type": "choice", "choice": "none"}}}
        ),
        inject_memories=False,
    )

    def capture(user_input, assistant_output, model_name, settings):
        stored["user"] = user_input
        stored["assistant"] = assistant_output
        stored["model"] = model_name

    wrapped._store_conversation = capture
    model.decide("今天出门吗", {"kind": {"type": "choice", "criteria": {"none": "没有"}}})

    assert seen["body"]["state"] == "今天出门吗"
    assert stored["user"] == "今天出门吗"
    assert stored["model"] == "jev-1.13.0"
    assert '"choice": "none"' in stored["assistant"]


def test_build_loop_wraps_openai_when_memory_is_configured():
    loop = build_loop(
        Settings(
            api_key="secret",
            base_url="http://example.test/llmproxy",
            model="jev-1.13.0",
            hindsight_base_url="http://hindsight.local",
            hindsight_bank_id="bank-1",
            llm_api_key="",
            llm_base_url="",
            llm_model="",
            laya_model="laya",
            enabled_agents=("chat", "qa"),
            default_agent="chat",
            weixin_enabled=False,
            weixin_base_url="https://ilinkai.weixin.qq.com",
            weixin_token="",
            weixin_account_id="default",
        )
    )

    assert loop.model._model == "laya"
    assert loop.model._wrapped is None
    assert loop.registry.get("chat")._llm is loop.registry.get("qa")._llm


def test_build_loop_wraps_the_qa_client():
    loop = build_loop(
        Settings(
            api_key="secret",
            base_url="http://example.test/llmproxy",
            model="jev-1.13.0",
            hindsight_base_url="http://hindsight.local",
            hindsight_bank_id="bank-1",
            llm_api_key="llm-secret",
            llm_base_url="https://example.test/v1/chat/completions",
            llm_model="demo-llm",
            laya_model="laya",
            enabled_agents=("qa",),
            default_agent="chat",
            weixin_enabled=False,
            weixin_base_url="https://ilinkai.weixin.qq.com",
            weixin_token="",
            weixin_account_id="default",
        )
    )
    llm = loop.registry.get("qa")._llm

    assert llm._model == "demo-llm"
    assert llm._client._api_url == "http://hindsight.local"
    assert str(llm._client._client._client.base_url).rstrip("/") == "https://example.test/v1"
    assert llm._client.chat is llm._client.chat

    found = {}

    def grab():
        found["chat"] = llm._client.chat

    thread = threading.Thread(target=grab)
    thread.start()
    thread.join()

    assert found["chat"] is not llm._client.chat
    # 两条线程各有一份包装器，里面的 OpenAI 客户端仍是同一个。
    assert found["chat"]._wrapper._client is llm._client.chat._wrapper._client
    assert found["chat"]._wrapper._api_url == "http://hindsight.local"
