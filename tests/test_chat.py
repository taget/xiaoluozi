from tests.fakes import FakeModel
from xiaoluozi.agents.chat import ChatAgent


def test_chat_agent_is_the_everyday_fallback_and_returns_model_text():
    model = FakeModel(["你好，我在。"])
    agent = ChatAgent(model)

    assert agent.id == "chat"
    assert "日常" in agent.description
    assert "兜底" in agent.description
    assert agent.handle("在吗") == "你好，我在。"
    joined = "\n".join(message["content"] for message in model.calls[0])
    assert "在吗" in joined
    assert len(model.calls) == 1
