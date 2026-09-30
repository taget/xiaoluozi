import json

from xiaoluozi.config import DEFAULT_BASE_URL, DEFAULT_MODEL, Settings, account_path, env_path


def test_settings_use_documented_defaults_when_dotenv_is_missing(tmp_path):
    settings = Settings.load(tmp_path / ".env")

    assert settings.base_url == DEFAULT_BASE_URL == "http://v2.open.venus.oa.com/llmproxy"
    assert settings.model == DEFAULT_MODEL == "jev-1.13.0"
    assert settings.api_key == ""
    assert settings.model_configured is False
    assert settings.memory_configured is False
    assert settings.llm_api_key == ""
    assert settings.llm_base_url == ""
    assert settings.llm_model == ""
    assert settings.llm_configured is False
    assert settings.laya_model == "laya"
    assert settings.enabled_agents == ("chat", "qa")
    assert settings.default_agent == "chat"
    assert settings.weixin_enabled is False
    assert settings.weixin_configured is False
    assert settings.weixin_token == ""
    assert settings.weixin_base_url == "https://ilinkai.weixin.qq.com"


def test_blank_base_url_and_model_fall_back_to_defaults(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        'TYPESAFE_BASE_URL=""\nTYPESAFE_DEFAULT_MODEL=""\n',
        encoding="utf-8",
    )

    settings = Settings.load(env)

    assert settings.base_url == DEFAULT_BASE_URL
    assert settings.model == DEFAULT_MODEL


def test_settings_come_from_the_dotenv_file_not_the_process(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                'TYPESAFE_API_KEY="secret"',
                'TYPESAFE_BASE_URL="http://example.test/llmproxy"',
                'TYPESAFE_DEFAULT_MODEL="demo-model"',
                'HINDSIGHT_BASE_URL="http://memory.test"',
                'HINDSIGHT_BANK_ID="bank-1"',
                'LLM_API_KEY="llm-secret"',
                'LLM_BASE_URL="https://example.test/v1/chat/completions"',
                'LLM_MODEL_NAME="demo-llm"',
                'LAYA_MODEL="laya"',
                'ENABLED_AGENTS="qa, chat"',
                'DEFAULT_AGENT="qa"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-the-shell")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://shell.example")
    monkeypatch.setenv("LLM_API_KEY", "from-the-shell")
    monkeypatch.setenv("LLM_MODEL_NAME", "from-the-shell")

    settings = Settings.load(env)

    assert settings.api_key == "secret"
    assert settings.base_url == "http://example.test/llmproxy"
    assert settings.model == "demo-model"
    assert settings.hindsight_base_url == "http://memory.test"
    assert settings.hindsight_bank_id == "bank-1"
    assert settings.llm_api_key == "llm-secret"
    assert settings.llm_base_url == "https://example.test/v1/chat/completions"
    assert settings.llm_model == "demo-llm"
    assert settings.model_configured is True
    assert settings.memory_configured is True
    assert settings.llm_configured is True
    assert settings.laya_model == "laya"
    assert settings.enabled_agents == ("qa", "chat")
    assert settings.default_agent == "qa"


def test_default_env_path_is_the_project_root_dotenv():
    path = env_path()

    assert path.name == ".env"
    assert (path.parent / "pyproject.toml").is_file()


def test_weixin_token_comes_from_the_dotenv_or_the_account_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("WEIXIN_ENABLED=true\nWEIXIN_BOT_TOKEN=from-env\n", encoding="utf-8")
    monkeypatch.setenv("WEIXIN_BOT_TOKEN", "from-the-shell")
    monkeypatch.setenv("WEIXIN_ENABLED", "false")

    from_env = Settings.load(env)

    assert from_env.weixin_enabled is True
    assert from_env.weixin_token == "from-env"
    assert from_env.weixin_configured is True

    env.write_text("WEIXIN_ENABLED=true\n", encoding="utf-8")
    account = account_path(tmp_path)
    account.parent.mkdir(parents=True)
    account.write_text(
        json.dumps({"token": "from-file", "baseUrl": "https://ilink.example", "userId": "user-1"}),
        encoding="utf-8",
    )

    from_file = Settings.load(env)

    assert from_file.weixin_token == "from-file"
    assert from_file.weixin_base_url == "https://ilink.example"
    assert from_file.weixin_configured is True
