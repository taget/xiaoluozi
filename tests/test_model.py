import json

import httpx

from xiaoluozi.errors import ModelError, ModelNotConfigured
from xiaoluozi.model import OpenAICompatibleClient


def test_model_client_posts_chat_completions_and_returns_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "  好的。  "}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleClient(
        "secret-key",
        "http://v2.open.venus.oa.com/llmproxy",
        "jev-1.13.0",
        client=client,
    )

    assert model.complete([{"role": "user", "content": "你好"}]) == "好的。"
    assert seen["url"] == "http://v2.open.venus.oa.com/llmproxy/chat/completions"
    assert seen["auth"] == "Bearer secret-key"
    assert seen["body"]["model"] == "jev-1.13.0"
    assert seen["body"]["messages"] == [{"role": "user", "content": "你好"}]
    assert "tools" not in seen["body"]


def test_blank_model_key_does_not_call_the_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank key must not call the model")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleClient("  ", "http://example.test", "jev-1.13.0", client=client)
    try:
        model.complete([{"role": "user", "content": "你好"}])
    except ModelNotConfigured:
        pass
    else:
        raise AssertionError("blank key must refuse")


def test_model_error_body_is_not_treated_as_a_reply():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleClient("secret-key", "http://example.test/llmproxy", "jev-1.13.0", client=client)
    try:
        model.complete([{"role": "user", "content": "你好"}])
    except ModelError as exc:
        assert "401" in str(exc)
    else:
        raise AssertionError("HTTP failure must not become a reply")
