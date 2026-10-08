import json

import httpx

from xiaoluozi.channels.weixin import WeixinApi, WeixinChannel, finish_login, message_text, save_account
from xiaoluozi.history import History
from xiaoluozi.loop import Reply


class _ReplyHandle:
    def __init__(self):
        self.messages = []

    def __call__(self, message, channel="web"):
        self.messages.append((channel, message))
        return Reply(text=f"收到：{message}", saved=True)


def test_weixin_text_is_handled_and_sent_back(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = body
        if request.url.path.endswith("/getupdates"):
            return httpx.Response(
                200,
                json={
                    "ret": 0,
                    "get_updates_buf": "cursor-2",
                    "msgs": [
                        {
                            "from_user_id": "user-9",
                            "context_token": "ctx-1",
                            "message_type": 1,
                            "item_list": [{"type": 1, "text_item": {"text": "明天还出门吗"}}],
                        },
                        {
                            "message_type": 2,
                            "item_list": [{"type": 1, "text_item": {"text": "这是机器人自己的话"}}],
                        },
                    ],
                },
            )
        return httpx.Response(200, json={"ret": 0})

    handle = _ReplyHandle()
    channel = WeixinChannel(
        WeixinApi("https://ilink.example", "bot-secret", client=httpx.Client(transport=httpx.MockTransport(handler))),
        handle,
        tmp_path / "default.sync.json",
    )

    assert channel.poll_once() == 1
    assert handle.messages == [("weixin", "明天还出门吗")]
    assert seen["auth"] == "Bearer bot-secret"
    assert seen["body"]["msg"]["to_user_id"] == "user-9"
    assert seen["body"]["msg"]["context_token"] == "ctx-1"
    assert seen["body"]["msg"]["item_list"][0]["text_item"]["text"] == "收到：明天还出门吗"
    assert "bot-secret" not in json.dumps({k: v for k, v in seen.items() if k != "auth"})
    saved = json.loads((tmp_path / "default.sync.json").read_text(encoding="utf-8"))
    assert saved["get_updates_buf"] == "cursor-2"
    assert message_text({"message_type": 2, "item_list": [{"type": 1, "text_item": {"text": "跳过"}}]}) == ""


def test_login_writes_the_account_file_without_printing_the_token(tmp_path, capsys):
    path = tmp_path / "data" / "weixin" / "account.json"
    message = finish_login(
        {
            "status": "confirmed",
            "bot_token": "bot-secret",
            "ilink_bot_id": "bot-1",
            "baseurl": "https://ilink.example",
            "ilink_user_id": "user-1",
        },
        path,
    )

    print(message)
    logged = capsys.readouterr().out
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["token"] == "bot-secret"
    assert stored["baseUrl"] == "https://ilink.example"
    assert "bot-secret" not in logged
    assert "微信已连接" in message
    assert path.stat().st_mode & 0o777 == 0o600
    save_account(path, token="other-secret", base_url="https://ilink.example", user_id="user-1")


def test_history_api_returns_turns_from_both_channels():
    from fastapi.testclient import TestClient

    from tests.fakes import FakeLlm, FakeMemory, FakeModel
    from tests.test_loop import _loop, _route_answer
    from xiaoluozi.app import create_app

    history = History(None)
    loop = _loop(FakeModel([_route_answer(), _route_answer(intent="ask")]), FakeMemory(), FakeLlm("带伞。"), history=history)
    loop.handle("今天出门吗", channel="web")
    loop.handle("微信里再问一次", channel="weixin")
    client = TestClient(create_app(loop=loop, model_configured=True, history=history))

    response = client.get("/api/history")

    assert response.status_code == 200
    body = response.json()
    assert [turn["channel"] for turn in body["turns"]] == ["web", "weixin"]
    assert body["turns"][0]["user"] == "今天出门吗"
    assert "带伞。" in body["turns"][1]["reply"]
    page = client.get("/").text
    assert "/api/history" in page
    assert "setInterval(loadHistory, 3000)" not in page
    assert "微信和这个页面是同一段对话。" in page
