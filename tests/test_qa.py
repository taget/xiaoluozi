import httpx
from openai import APIStatusError

from xiaoluozi.agents.qa import QaAgent
from xiaoluozi.errors import ModelError, ModelNotConfigured
from xiaoluozi.model import ClosedLlm, LlmClient, LoggingOpenAI, chat_base_url


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content="带伞。", error=None):
        self.content = content
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return _Response(self.content)


class _Client:
    def __init__(self, completions):
        self.chat = self
        self.completions = completions


def test_qa_agent_sends_the_system_prompt_and_returns_the_answer(capsys):
    completions = _Completions("  出门带伞。  ")
    agent = QaAgent(LlmClient(_Client(completions), "demo-llm", "llm-secret"))

    assert agent.id == "qa"
    assert "提问" in agent.description
    assert agent.handle("今天出门要带伞吗") == "出门带伞。"
    call = completions.calls[0]
    assert call["model"] == "demo-llm"
    user = call["messages"][1]["content"]
    assert call["messages"][0] == {"role": "system", "content": agent.system}
    assert "用户问题：今天出门要带伞吗" in user
    assert "没有可用的上下文。" in user
    assert len(completions.calls) == 1
    logged = capsys.readouterr().err
    assert "问答请求 model=demo-llm" in logged
    assert "今天出门要带伞吗" in logged
    assert "问答响应 出门带伞。" in logged
    assert "llm-secret" not in logged


def test_qa_agent_forwards_context_and_intent():
    completions = _Completions("带伞。")
    agent = QaAgent(LlmClient(_Client(completions), "demo-llm"))

    agent.handle("今天出门要带伞吗", context="用户出门要带伞", intent="在提问")

    user = completions.calls[0]["messages"][1]["content"]
    assert "用户出门要带伞" in user
    assert "用户意图：在提问" in user
    assert "用户问题：今天出门要带伞吗" in user


def test_llm_stream_yields_each_piece(capsys):
    class _Delta:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.delta = _Delta(content)

    class _Chunk:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class _Events:
        def __init__(self):
            self._parts = iter([_Chunk("带"), _Chunk(None), _Chunk("伞。")])
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._parts)

        def close(self):
            self.closed = True

    events = _Events()

    class _Completions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return events

    completions = _Completions()
    pieces = list(LlmClient(_Client(completions), "demo-llm", "llm-secret").stream("系统", "今天呢"))

    assert pieces == ["带", "伞。"]
    assert completions.kwargs["stream"] is True
    assert events.closed is True
    assert "问答响应 带伞。" in capsys.readouterr().err


def test_llm_request_prints_the_context_sent_to_the_backend(capsys):
    completions = _Completions("好。")
    client = LoggingOpenAI(_Client(completions), "llm-secret")
    LlmClient(client, "demo-llm", "llm-secret").answer(
        "你是小落子。",
        "当前上下文：\n用户出门要带伞\n\n用户问题：今天呢",
    )

    logged = capsys.readouterr().err
    assert "大模型请求后端 model=demo-llm" in logged
    assert "[system]\n你是小落子。" in logged
    assert "[user]\n当前上下文：\n用户出门要带伞\n\n用户问题：今天呢" in logged
    assert "llm-secret" not in logged
    assert completions.calls[0]["messages"][1]["content"].startswith("当前上下文：")


def test_qa_agent_rejects_an_empty_completion():
    agent = QaAgent(LlmClient(_Client(_Completions("  ")), "demo-llm"))
    try:
        agent.handle("今天出门要带伞吗")
    except ModelError as exc:
        assert "没有回复内容" in str(exc)
    else:
        raise AssertionError("empty completion must not become a reply")


def test_qa_error_body_redacts_the_key(capsys):
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(401, text='{"error":"bad llm-secret"}', request=request)
    error = APIStatusError("bad llm-secret", response=response, body=None)
    agent = QaAgent(LlmClient(_Client(_Completions(error=error)), "demo-llm", "llm-secret"))

    try:
        agent.handle("今天出门要带伞吗")
    except ModelError as exc:
        assert "401" in str(exc)
    else:
        raise AssertionError("HTTP failure must not become a reply")
    logged = capsys.readouterr().err
    assert "问答响应 401" in logged
    assert "llm-secret" not in logged
    assert "[redacted]" in logged


def test_unconfigured_qa_does_not_call_the_network():
    agent = QaAgent(ClosedLlm())
    try:
        agent.handle("今天出门要带伞吗")
    except ModelNotConfigured as exc:
        assert "LLM_API_KEY" in str(exc)
    else:
        raise AssertionError("missing LLM config must refuse")


def test_chat_completions_suffix_is_trimmed_from_the_base_url():
    assert chat_base_url("https://example.test/v1/chat/completions") == "https://example.test/v1"
    assert chat_base_url("https://example.test/v1") == "https://example.test/v1"
