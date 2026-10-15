import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from xiaoluozi.agents.wxwork import WxworkAgent
from xiaoluozi.skills import SkillCatalog
from xiaoluozi.tools import run_tool, tool_specs
from xiaoluozi.wecom import _run, gate, run_wecom

BINARY = "/usr/local/bin/wecom-cli"


def _which(_name):
    return BINARY


def _scripted(responses):
    calls = []

    def run(argv, timeout):
        calls.append((argv, timeout))
        stdout, code = responses.pop(0)
        return subprocess.CompletedProcess(argv, code, stdout, "")

    return calls, run


def _ready():
    return [("1.3.0\n", 0), ("authorized\n", 0)]


def test_missing_binary_does_not_run():
    called = False

    def run(_argv, _timeout):
        nonlocal called
        called = True

    text = run_wecom('{"action":"version"}', run=run, which=lambda _name: None)

    assert called is False
    assert "npm install -g @wecom/cli" in text
    assert "auth init" not in text


def test_business_call_checks_version_and_auth_then_passes_json_argv():
    calls, run = _scripted([*_ready(), ('{"name":"乔"}\n', 0)])

    text = run_wecom(
        json.dumps(
            {
                "category": "contact",
                "command": "users search",
                "args": {"query": "乔"},
            }
        ),
        run=run,
        which=_which,
    )

    assert text == '{"name":"乔"}'
    assert [item[0] for item in calls] == [
        [BINARY, "--version"],
        [BINARY, "auth", "show"],
        [BINARY, "contact", "users", "search", "--json", '{"query":"乔"}'],
    ]
    assert all(timeout == 60 for _argv, timeout in calls)


def test_old_cli_stops_before_the_business_command():
    calls, run = _scripted([("1.0.0\n", 0)])

    text = run_wecom(
        json.dumps({"category": "calendar", "command": ["list"]}),
        run=run,
        which=_which,
    )

    assert "1.0.0" in text
    assert "1.3.0" in text
    assert len(calls) == 1


def test_unauthorized_stops_before_the_business_command():
    calls, run = _scripted([("1.3.0\n", 0), ("unauthorized\n", 0)])

    text = run_wecom(
        json.dumps({"category": "message", "command": ["send"], "args": {"text": "hi"}}),
        run=run,
        which=_which,
    )

    assert "wecom-cli auth init" in text
    assert "corp_id" in text
    assert "自建应用" in text
    assert len(calls) == 2


def test_shell_metacharacters_and_flags_are_refused():
    called = False

    def run(_argv, _timeout):
        nonlocal called
        called = True

    assert "命令不合法" in run_wecom(
        json.dumps({"category": "contact", "command": "users;rm"}),
        run=run,
        which=_which,
    )
    assert "命令不合法" in run_wecom(
        json.dumps({"category": "contact", "command": ["--help"]}),
        run=run,
        which=_which,
    )
    assert called is False


def test_auth_action_only_shows_status():
    calls, run = _scripted([("authorized\n", 0)])

    text = run_wecom('{"action":"auth"}', run=run, which=_which)

    assert text == "authorized"
    assert calls[0][0] == [BINARY, "auth", "show"]
    assert run_wecom('{"action":"init"}', run=run, which=_which) == "没有这个操作。"


def test_unknown_category_lists_the_allowlist():
    text = run_wecom(
        json.dumps({"category": "msg", "command": ["send"]}),
        run=lambda *_args: None,
        which=_which,
    )

    assert "没有这个企业微信品类" in text
    assert "message" in text


def test_category_help_still_checks_auth():
    calls, run = _scripted([*_ready(), ("usage\n", 0)])

    text = run_wecom(
        json.dumps({"category": "calendar", "help": True}),
        run=run,
        which=_which,
    )

    assert text == "usage"
    assert calls[-1][0] == [BINARY, "calendar", "--help"]


def test_default_runner_stays_outside_the_repo_and_kills_the_child(tmp_path):
    completed = _run([sys.executable, "-c", "import os; print(os.getcwd())"], 10)

    workdir = Path(completed.stdout.strip()).resolve()
    repo = Path(__file__).resolve().parents[1]
    assert completed.returncode == 0
    assert workdir == Path(tempfile.gettempdir()).resolve() / "xiaoluozi-wecom"
    assert repo not in workdir.parents

    pidfile = tmp_path / "child.pid"
    code = (
        "import sys,time,subprocess;"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
        f"open({str(pidfile)!r},'w').write(str(p.pid));"
        "time.sleep(30)"
    )
    try:
        _run([sys.executable, "-c", code], 2)
    except subprocess.TimeoutExpired:
        killed = True
    else:
        killed = False

    assert killed
    pid = int(pidfile.read_text())
    assert _alive(pid) is False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    text = state.stdout.strip()
    return bool(text) and not text.startswith("Z")


def test_timeout_is_a_sentence():
    def run(_argv, _timeout):
        raise subprocess.TimeoutExpired(_argv, _timeout)

    text = run_wecom('{"action":"version"}', run=run, which=_which)

    assert text == "企业微信 CLI 超时。"


def test_gate_states_the_cli_steps_and_refuses_a_custom_app():
    _calls, run = _scripted([("1.3.4\n", 0), ("Status: unauthorized\n", 0)])

    text = gate(run=run, which=_which)

    assert "wecom-cli auth init" in text
    assert "自建应用" in text
    assert "corp_id" in text
    assert gate(run=_scripted([("1.3.4\n", 0), ("Status: authorized\n", 0)])[1], which=_which) == ""


def test_wxwork_does_not_let_the_model_rewrite_an_auth_block(monkeypatch):
    class _Boom:
        def answer(self, *_args, **_kwargs):
            raise AssertionError("模型不该改写授权说明")

        def stream(self, *_args, **_kwargs):
            raise AssertionError("模型不该改写授权说明")
            yield ""

    agent = WxworkAgent(_Boom(), SkillCatalog().load(("wecom",)))
    sentence = "企业微信还没授权。在终端执行 wecom-cli auth init"
    monkeypatch.setattr("xiaoluozi.agents.wxwork.gate", lambda: sentence)

    assert agent.handle("发一条消息") == sentence
    assert list(agent.stream("发一条消息")) == [sentence]


def test_wxwork_exposes_the_wecom_tool(monkeypatch):
    agent = WxworkAgent(object(), SkillCatalog().load(("wecom",)))
    specs = tool_specs(agent._skills)
    monkeypatch.setattr("xiaoluozi.wecom.shutil.which", lambda _name: None)

    assert agent.id == "wxwork"
    assert agent.connector_ids == ("wecom",)
    assert agent._connectors[0].id == "wecom"
    assert [spec["function"]["name"] for spec in specs] == ["Wecom"]
    assert "npm install -g @wecom/cli" in run_tool("Wecom", '{"action":"version"}')
