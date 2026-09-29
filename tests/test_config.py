from xiaoluozi.config import DEFAULT_BASE_URL, DEFAULT_MODEL, Settings


def test_settings_use_documented_defaults_when_env_is_empty(monkeypatch):
    for name in (
        "TYPESAFE_API_KEY",
        "TYPESAFE_BASE_URL",
        "TYPESAFE_DEFAULT_MODEL",
        "HINDSIGHT_BASE_URL",
        "HINDSIGHT_BANK_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.base_url == DEFAULT_BASE_URL == "http://v2.open.venus.oa.com/llmproxy"
    assert settings.model == DEFAULT_MODEL == "jev-1.13.0"
    assert settings.model_configured is False
    assert settings.memory_configured is False


def test_blank_base_url_and_model_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("TYPESAFE_BASE_URL", "  ")
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.base_url == DEFAULT_BASE_URL
    assert settings.model == DEFAULT_MODEL
