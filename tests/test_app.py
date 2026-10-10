import json
import logging

from fastapi.testclient import TestClient

from tests.fakes import FakeMemory, FakeModel
from xiaoluozi.app import create_app
from xiaoluozi.log import QuietHistoryAccess
from xiaoluozi.errors import ModelError, ReplyError
from xiaoluozi.loop import Reply


class StubLoop:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.messages = []

    def handle(self, message, channel="web"):
        self.messages.append(message)
        self.channels = getattr(self, "channels", [])
        self.channels.append(channel)
        if self.error:
            raise self.error
        return self.result

    def stream(self, message, channel="web"):
        self.messages.append(message)
        self.channels = getattr(self, "channels", [])
        self.channels.append(channel)
        if self.error:
            raise self.error
        yield from getattr(self, "pieces", ())
        if self.result is not None:
            yield self.result


def test_page_loads_in_chinese_without_knowing_agents():
    client = TestClient(create_app(loop=StubLoop(), model_configured=True))
    response = client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "小落子" in text
    assert "/api/handle/stream" in text
    assert "agent_id" not in text
    assert "hindsight" not in text.lower()


def test_status_reports_model_missing():
    client = TestClient(create_app(loop=StubLoop(), model_configured=False))
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {"model_configured": False, "weixin_configured": False}


def test_page_error_is_not_a_successful_reply():
    loop = StubLoop(error=ReplyError("模型调用失败。"))
    client = TestClient(create_app(loop=loop, model_configured=True))
    response = client.post("/api/handle", json={"message": "你好"})

    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "模型调用失败。"
    assert "reply" not in body
    assert loop.messages == ["你好"]


def test_handle_response_is_only_the_reply_and_optional_save_note(capsys):
    loop = StubLoop(result=Reply(text="带伞比较好。", saved=False, note="这一轮没有存进记忆。"))
    client = TestClient(create_app(loop=loop, model_configured=True))
    response = client.post("/api/handle", json={"message": "今天要不要出门"})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "带伞比较好。",
        "saved": False,
        "note": "这一轮没有存进记忆。",
    }
    logged = capsys.readouterr().err
    assert "请求 POST /api/handle 今天要不要出门" in logged
    assert "入口接受 channel=web 今天要不要出门" in logged
    assert "响应 200 POST /api/handle" in logged
    assert "带伞比较好。" in logged


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


def test_history_poll_stays_out_of_the_info_log(capsys):
    client = TestClient(create_app(loop=StubLoop(), model_configured=True))
    response = client.get("/api/history")

    assert response.status_code == 200
    assert "GET /api/history" not in capsys.readouterr().err


def test_history_poll_is_dropped_from_the_access_log():
    quiet = QuietHistoryAccess()
    history = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/api/history", "1.1", 200),
        None,
    )
    failed = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/api/history", "1.1", 500),
        None,
    )
    handle = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "POST", "/api/handle", "1.1", 200),
        None,
    )

    assert quiet.filter(history) is False
    assert quiet.filter(failed) is True
    assert quiet.filter(handle) is True


def test_stream_sends_each_piece_then_the_finished_reply():
    loop = StubLoop(result=Reply(text="带伞。\n\n选用 chat。依据：日常对话。", saved=True))
    loop.pieces = ["带", "伞。"]
    client = TestClient(create_app(loop=loop, model_configured=True))

    with client.stream("POST", "/api/handle/stream", json={"message": "今天要不要出门"}) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]

    assert [json.loads(line) for line in lines] == [
        {"delta": "带"},
        {"delta": "伞。"},
        {"reply": "带伞。\n\n选用 chat。依据：日常对话。", "saved": True, "note": None},
    ]
    assert loop.messages == ["今天要不要出门"]


def test_stream_error_stays_on_one_line():
    loop = StubLoop(error=ReplyError("先写一句话。"))
    client = TestClient(create_app(loop=loop, model_configured=True))

    with client.stream("POST", "/api/handle/stream", json={"message": "   "}) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert json.loads(body) == {"error": "先写一句话。"}
    assert loop.messages == []


def test_stream_unexpected_failure_is_one_error_line():
    loop = StubLoop(error=RuntimeError("boom"))
    client = TestClient(create_app(loop=loop, model_configured=True))

    with client.stream("POST", "/api/handle/stream", json={"message": "你好"}) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert json.loads(body) == {"error": "没能回复。"}


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
