import json

from fastapi.testclient import TestClient

from xiaoluozi.app import create_app
from xiaoluozi.loop import Reply
from xiaoluozi.open_apps import find_open_app, load_open_apps
from xiaoluozi.tools import open_entry, run_tool
from tests.test_app import StubLoop


def test_the_shipped_list_names_chrome_iterm_and_wxwork():
    apps = {app.id: app for app in load_open_apps()}

    assert apps["chrome"].app == "Google Chrome"
    assert apps["iterm2"].name == "iTerm2"
    assert apps["wxwork"].url == "wxwork://"
    assert find_open_app("企业微信", tuple(apps.values())).id == "wxwork"


def test_a_broken_list_is_refused(tmp_path):
    path = tmp_path / "open_apps.toml"
    path.write_text('[[app]]\nid = "Chrome"\nname = "Chrome"\napp = "Google Chrome"\n', encoding="utf-8")

    try:
        load_open_apps(path)
    except ValueError as exc:
        assert "不合法" in str(exc)
    else:
        raise AssertionError("an uppercase id must be refused")


def test_open_prepares_an_entry_and_does_not_launch(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("open must not launch from the tool")

    monkeypatch.setattr("xiaoluozi.open_apps.subprocess.run", fail)

    result = run_tool("Open", json.dumps({"app": "chrome"}))

    assert result == "可以给用户一个入口：[打开 Chrome](app:chrome)"
    assert open_entry("missing") == "不能打开这个应用。可选：chrome、iterm2、wxwork。"


def test_clicking_chrome_opens_the_allowlisted_app(monkeypatch):
    opened = []

    def record(command, check=False):
        opened.append(command)
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr("xiaoluozi.open_apps.subprocess.run", record)
    client = TestClient(create_app(loop=StubLoop(result=Reply(text="好。", saved=True)), model_configured=True))

    response = client.post("/api/open", json={"id": "chrome"})

    assert response.status_code == 200
    assert response.json() == {"opened": True}
    assert opened == [["open", "-a", "Google Chrome"]]


def test_clicking_wxwork_returns_its_address_without_launching(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("a url entry must not call open")

    monkeypatch.setattr("xiaoluozi.open_apps.subprocess.run", fail)
    client = TestClient(create_app(loop=StubLoop(result=Reply(text="好。", saved=True)), model_configured=True))

    response = client.post("/api/open", json={"id": "wxwork"})

    assert response.status_code == 200
    assert response.json() == {"url": "wxwork://"}


def test_an_unknown_app_is_not_opened():
    client = TestClient(create_app(loop=StubLoop(result=Reply(text="好。", saved=True)), model_configured=True))

    response = client.post("/api/open", json={"id": "finder"})

    assert response.status_code == 404
    assert response.json() == {"error": "不能打开这个应用。"}
