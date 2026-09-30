"""Check that the API key can call Jev on the systemone endpoint.

The key stays in ``.env`` and is never printed.
"""

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xiaoluozi.config import Settings
from xiaoluozi.model import systemone_url

MODEL = "laya"


def main() -> int:
    settings = Settings.load()
    if not settings.model_configured:
        print("失败：.env 里没有 TYPESAFE_API_KEY。")
        return 1

    url = systemone_url(settings.base_url)
    payload = {
        "model": MODEL,
        "state": "The customer says the invoice is wrong and asks for immediate help.",
        "questions": {
            "is_urgent": {
                "type": "noul",
                "instructions": "Is this request urgent?",
            },
            "department": {
                "type": "choice",
                "instructions": "Which department should handle this request?",
                "criteria": {"billing": None, "support": None},
            },
            "frustration": {
                "type": "score",
                "instructions": "Rate the customer's frustration.",
                "criteria": ["calm", "frustrated"],
            },
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.api_key}",
    }
    print(f"POST {url} model={MODEL}")
    try:
        response = httpx.post(url, headers=headers, content=json.dumps(payload), timeout=60.0)
    except httpx.HTTPError as exc:
        print(f"失败：{exc}")
        return 1

    body = response.text.replace(settings.api_key, "[redacted]")
    if response.status_code != 200:
        print(body)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
