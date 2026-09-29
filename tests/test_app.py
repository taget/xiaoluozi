from fastapi.testclient import TestClient

from tests.fakes import FakeMemory, FakeModel
from xiaoluozi.app import create_app
from xiaoluozi.errors import ModelError, ReplyError
from xiaoluozi.loop import Reply


class StubLoop:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.messages = []

    def handle(self, message):
        self.messages.append(message)
        if self.error:
            raise self.error
        return self.result


def test_page_loads_in_chinese_without_knowing_agents():
    client = TestClient(create_app(loop=StubLoop(), model_configured=True))
    response = client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "小落子" in text
    assert "agent_id" not in text
    assert "hindsight" not in text.lower()


def test_status_reports_model_missing():
    client = TestClient(create_app(loop=StubLoop(), model_configured=False))
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {"model_configured": False}


def test_page_error_is_not_a_successful_reply():
    loop = StubLoop(error=ReplyError("模型调用失败。"))
    client = TestClient(create_app(loop=loop, model_configured=True))
    response = client.post("/api/handle", json={"message": "你好"})

    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "模型调用失败。"
    assert "reply" not in body
    assert loop.messages == ["你好"]


def test_handle_response_is_only_the_reply_and_optional_save_note():
    loop = StubLoop(result=Reply(text="带伞比较好。", saved=False, note="这一轮没有存进记忆。"))
    client = TestClient(create_app(loop=loop, model_configured=True))
    response = client.post("/api/handle", json={"message": "今天要不要出门"})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "带伞比较好。",
        "saved": False,
        "note": "这一轮没有存进记忆。",
    }


def test_model_error_is_shown_as_an_error():
    loop = StubLoop(error=ModelError("连不上模型服务。"))
    client = TestClient(create_app(loop=loop, model_configured=True))
    response = client.post("/api/handle", json={"message": "你好"})

    assert response.status_code == 502
    assert response.json() == {"error": "连不上模型服务。"}
    assert loop.messages == ["你好"]


def test_blank_message_is_not_a_reply():
    loop = StubLoop(result=Reply(text="不该出现", saved=True))
    client = TestClient(create_app(loop=loop, model_configured=True))
    response = client.post("/api/handle", json={"message": "   "})

    assert response.status_code == 400
    assert response.json() == {"error": "先写一句话。"}
    assert loop.messages == []


def test_unconfigured_submit_does_not_call_the_loop():
    model = FakeModel(["不该被调用"])
    memory = FakeMemory()
    loop = StubLoop(result=Reply(text="假的成功", saved=True, note=None))
    client = TestClient(create_app(loop=loop, model_configured=False))
    response = client.post("/api/handle", json={"message": "你好"})

    assert response.status_code == 503
    assert "reply" not in response.json()
    assert loop.messages == []
    assert model.calls == []
    assert memory.attempts == 0
