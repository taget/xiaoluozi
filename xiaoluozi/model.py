import json

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from xiaoluozi.errors import ModelError, ModelNotConfigured
from xiaoluozi.log import get_logger
from xiaoluozi.config import DEFAULT_TOOL_MAX_ROUNDS
from xiaoluozi.tools import finish_answer

logger = get_logger("xiaoluozi.model")
_NOT_CONFIGURED = "模型还没配好。在 .env 里设置 TYPESAFE_API_KEY 后再试。"
_LLM_NOT_CONFIGURED = "问答模型还没配好。在 .env 里设置 LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL_NAME 后再试。"


def chat_base_url(base_url: str) -> str:
    """OpenAI client appends /chat/completions. A URL that already ends there is trimmed."""
    base = base_url.strip().rstrip("/")
    suffix = "/chat/completions"
    if base.endswith(suffix):
        return base[: -len(suffix)]
    return base


def systemone_url(base_url: str) -> str:
    """POST target for a Jev decision. A base that already ends at systemone is used as-is."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/systemone"):
        return base
    return f"{base}/v1/systemone"


class ClosedModel:
    """Stand-in used when no API key is configured. It never calls the network."""

    def decide(self, state, questions: dict) -> dict:
        logger.info("模型请求被拒绝 未配置")
        raise ModelNotConfigured(_NOT_CONFIGURED)


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _ChatCompletion:
    """Shape wrap_openai reads after the model call: choices[0].message.content."""

    def __init__(self, content: str):
        self.choices = [_Choice(content)]


class SystemoneOpenAI:
    """OpenAI-shaped client. chat.completions.create posts a Jev systemone body."""

    def __init__(self, jev: "JevClient"):
        self._jev = jev
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        answers = self._jev._post(_state_from_messages(kwargs.get("messages") or []), kwargs.get("questions") or {})
        return _ChatCompletion(json.dumps(answers, ensure_ascii=False))


def _state_from_messages(messages: list) -> str:
    system = []
    user = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content:
            continue
        if message.get("role") == "system":
            system.append(content)
        elif message.get("role") == "user":
            user.append(content)
    body = "\n".join(user)
    if not system:
        return body
    return "\n\n".join(system) + "\n\n" + body


class JevClient:
    """One Jev systemone decision. Questions are choice, score, or noul. No chat text."""

    def __init__(self, api_key: str, base_url: str, model: str, client: httpx.Client | None = None):
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._client = client
        self._wrapped = None
        self._owns_client = client is None
        if self._owns_client and self._api_key:
            self._client = httpx.Client(timeout=60.0)

    def bind(self, wrapped) -> None:
        """Use a wrap_openai client for recall, injection, and conversation storage."""
        self._wrapped = wrapped

    def decide(self, state, questions: dict) -> dict:
        if self._wrapped is None:
            return self._post(state, questions)
        text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
        logger.info("模型请求经 wrap_openai model=%s", self._model)
        try:
            response = self._wrapped.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": text}],
                questions=questions,
                hindsight_query=text,
            )
        except (ModelError, ModelNotConfigured):
            raise
        except Exception as exc:
            logger.info("模型请求失败 %s", exc)
            raise ModelError("模型调用失败。") from exc
        content = ""
        choices = getattr(response, "choices", None) or []
        if choices:
            content = getattr(getattr(choices[0], "message", None), "content", "") or ""
        try:
            answers = json.loads(content)
        except Exception as exc:
            raise ModelError("模型返回里没有回复内容。") from exc
        if not isinstance(answers, dict) or not answers:
            raise ModelError("模型返回里没有回复内容。")
        return answers

    def _post(self, state, questions: dict) -> dict:
        if not self._api_key or self._client is None:
            logger.info("模型请求被拒绝 未配置")
            raise ModelNotConfigured(_NOT_CONFIGURED)
        url = systemone_url(self._base_url)
        payload = {"model": self._model, "state": state, "questions": questions}
        logger.info("模型请求 POST %s\n%s", url, json.dumps(payload, ensure_ascii=False))
        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            logger.info("模型请求失败 超时 %s", url)
            raise ModelError("模型调用超时。") from exc
        except httpx.HTTPError as exc:
            logger.info("模型请求失败 连不上 %s %s", url, exc)
            raise ModelError("连不上模型服务。") from exc
        body = response.text.replace(self._api_key, "[redacted]")
        logger.info("模型响应 %s %s\n%s", response.status_code, url, body)
        if response.status_code >= 400:
            raise ModelError(f"模型调用失败（{response.status_code}）。")
        try:
            answers = response.json()["answers"]
        except Exception as exc:
            raise ModelError("模型返回里没有回复内容。") from exc
        if not isinstance(answers, dict) or not answers:
            raise ModelError("模型返回里没有回复内容。")
        return answers


class ClosedLlm:
    """Stand-in used when the chat LLM is not configured. It never calls the network."""

    def answer(self, system: str, message: str, tools=None, env=None) -> str:
        logger.info("问答请求被拒绝 未配置")
        raise ModelNotConfigured(_LLM_NOT_CONFIGURED)


class LoggingOpenAI:
    """Last hop before the HTTP call. Logs the messages the backend actually receives."""

    def __init__(self, client, api_key: str = ""):
        self._client = client
        self._api_key = api_key.strip()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        logger.info(
            "大模型请求后端 model=%s\n%s",
            kwargs.get("model", ""),
            _format_messages(kwargs.get("messages") or [], self._api_key),
        )
        return self._client.chat.completions.create(**kwargs)


class LlmClient:
    """One chat completion. The caller supplies the system prompt."""

    def __init__(self, client, model: str, api_key: str = "", max_tool_rounds: int = DEFAULT_TOOL_MAX_ROUNDS):
        self._client = client
        self._model = model.strip()
        self._api_key = api_key.strip()
        self._max_tool_rounds = max_tool_rounds

    def answer(self, system: str, message: str, tools=None, env=None) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ]
        secrets = _secret_values(env)
        text = finish_answer(
            lambda messages, tools: self._create(messages, tools, secrets),
            messages,
            tools,
            env,
            max_rounds=self._max_tool_rounds,
        )
        logger.info("问答响应 %s", self._redact(text, secrets))
        return text

    def stream(self, system: str, message: str, tools=None, env=None):
        """Yield the answer as the model produces it. Tool rounds finish before any text is yielded."""
        if tools:
            yield self.answer(system, message, tools=tools, env=env)
            return
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ]
        secrets = _secret_values(env)
        parts: list[str] = []
        response = self._create(messages, [], secrets, stream=True)
        try:
            for piece in _delta_text(response):
                parts.append(piece)
                yield piece
        except (ModelError, ModelNotConfigured):
            raise
        except APITimeoutError as exc:
            logger.info("问答请求失败 超时 %s", self._redact(str(exc), secrets))
            raise ModelError("问答模型调用超时。") from exc
        except APIConnectionError as exc:
            logger.info("问答请求失败 连不上 %s", self._redact(str(exc), secrets))
            raise ModelError("连不上问答模型。") from exc
        except APIStatusError as exc:
            logger.info("问答响应 %s\n%s", exc.status_code, self._redact(exc.response.text, secrets))
            raise ModelError(f"问答模型调用失败（{exc.status_code}）。") from exc
        except Exception as exc:
            logger.info("问答请求失败 %s", self._redact(str(exc), secrets))
            raise ModelError("问答模型调用失败。") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        text = "".join(parts).strip()
        logger.info("问答响应 %s", self._redact(text, secrets))
        if not text:
            raise ModelError("模型返回里没有回复内容。")

    def _create(self, messages: list, tools: list, secrets=(), stream: bool = False):
        logger.info(
            "问答请求 model=%s\n%s",
            self._model,
            _format_messages(messages, self._api_key, secrets),
        )
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if stream:
            kwargs["stream"] = True
        try:
            return self._client.chat.completions.create(**kwargs)
        except APITimeoutError as exc:
            logger.info("问答请求失败 超时 %s", self._redact(str(exc), secrets))
            raise ModelError("问答模型调用超时。") from exc
        except APIConnectionError as exc:
            logger.info("问答请求失败 连不上 %s", self._redact(str(exc), secrets))
            raise ModelError("连不上问答模型。") from exc
        except APIStatusError as exc:
            logger.info("问答响应 %s\n%s", exc.status_code, self._redact(exc.response.text, secrets))
            raise ModelError(f"问答模型调用失败（{exc.status_code}）。") from exc
        except (ModelError, ModelNotConfigured):
            raise
        except Exception as exc:
            logger.info("问答请求失败 %s", self._redact(str(exc), secrets))
            raise ModelError("问答模型调用失败。") from exc

    def _redact(self, text: str, secrets=()) -> str:
        if self._api_key and self._api_key in text:
            text = text.replace(self._api_key, "[redacted]")
        for value in secrets:
            if value and value in text:
                text = text.replace(value, "[redacted]")
        return text


def _delta_text(response):
    for chunk in response:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        piece = getattr(delta, "content", None) if delta is not None else None
        if piece:
            yield piece


def _secret_values(env) -> tuple[str, ...]:
    values = []
    for value in (env or {}).values():
        if isinstance(value, str) and value and value not in values:
            values.append(value)
    return tuple(values)


def _format_messages(messages, api_key: str = "", secrets=()) -> str:
    blocks = []
    for message in messages:
        if not isinstance(message, dict):
            blocks.append(_redact(str(message), api_key))
            continue
        role = message.get("role") or "message"
        content = _redact(_format_content(message.get("content")), api_key, secrets)
        blocks.append(f"[{role}]\n{content}")
    return "\n\n".join(blocks)


def _format_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(json.dumps(item, ensure_ascii=False, indent=2))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False, indent=2)


def _redact(text: str, api_key: str, secrets=()) -> str:
    if api_key and api_key in text:
        text = text.replace(api_key, "[redacted]")
    for value in secrets:
        if value and value in text:
            text = text.replace(value, "[redacted]")
    return text

