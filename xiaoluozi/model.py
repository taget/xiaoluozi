import httpx

from xiaoluozi.errors import ModelError, ModelNotConfigured


class ClosedModel:
    """Stand-in used when no API key is configured. It never calls the network."""

    def complete(self, messages: list[dict]) -> str:
        raise ModelNotConfigured("模型还没配好。设置 TYPESAFE_API_KEY 后再试。")


class OpenAICompatibleClient:
    """One chat completion against an OpenAI-compatible endpoint. No tools."""

    def __init__(self, api_key: str, base_url: str, model: str, client: httpx.Client | None = None):
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._client = client
        self._owns_client = client is None
        if self._owns_client and self._api_key:
            self._client = httpx.Client(timeout=60.0)

    def complete(self, messages: list[dict]) -> str:
        if not self._api_key:
            raise ModelNotConfigured("模型还没配好。设置 TYPESAFE_API_KEY 后再试。")
        if self._client is None:
            raise ModelNotConfigured("模型还没配好。设置 TYPESAFE_API_KEY 后再试。")
        url = f"{self._base_url}/chat/completions"
        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "messages": messages, "temperature": 0},
            )
        except httpx.TimeoutException as exc:
            raise ModelError("模型调用超时。") from exc
        except httpx.HTTPError as exc:
            raise ModelError("连不上模型服务。") from exc
        if response.status_code >= 400:
            raise ModelError(f"模型调用失败（{response.status_code}）。")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ModelError("模型返回里没有回复内容。") from exc
        if not isinstance(content, str) or not content.strip():
            raise ModelError("模型返回里没有回复内容。")
        return content.strip()
