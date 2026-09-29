import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://v2.open.venus.oa.com/llmproxy"
DEFAULT_MODEL = "jev-1.13.0"


def _or_default(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    hindsight_base_url: str
    hindsight_bank_id: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.environ.get("TYPESAFE_API_KEY", ""),
            base_url=_or_default("TYPESAFE_BASE_URL", DEFAULT_BASE_URL),
            model=_or_default("TYPESAFE_DEFAULT_MODEL", DEFAULT_MODEL),
            hindsight_base_url=os.environ.get("HINDSIGHT_BASE_URL", ""),
            hindsight_bank_id=os.environ.get("HINDSIGHT_BANK_ID", ""),
        )

    @property
    def model_configured(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def memory_configured(self) -> bool:
        return bool(self.hindsight_base_url.strip() and self.hindsight_bank_id.strip())
