import pytest

from xiaoluozi.connectors import load_connector, require_connectors


def test_wecom_connector_follows_the_workbuddy_definition():
    connector = load_connector("wecom")

    assert connector.skill == "wecom"
    assert connector.version_argv == ("wecom-cli", "--version")
    assert connector.min_version == (1, 3, 0)
    assert connector.status_argv == ("wecom-cli", "auth", "show")
    assert connector.init_command == "npm install -g @wecom/cli"
    assert connector.authorized("authorized")
    assert connector.authorized("bot: authorized\n")
    assert connector.authorized("unauthorized") is False
    assert "auth_command" not in connector.__dataclass_fields__


def test_unknown_connector_is_refused():
    with pytest.raises(ValueError, match="未知连接器 missing"):
        load_connector("missing")


def test_connector_requires_its_skill_on_the_agent():
    with pytest.raises(ValueError, match="连接器 wecom 没有装到这个代理上"):
        require_connectors(("wecom",), ())
