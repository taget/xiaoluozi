from tests.fakes import FakeLlm
from xiaoluozi.agents.chat import ChatAgent


def test_chat_agent_sends_context_and_intent_to_the_llm():
    llm = FakeLlm("在的。")
    agent = ChatAgent(llm)

    assert agent.id == "chat"
    assert "日常" in agent.description
    assert "兜底" in agent.description
    assert agent.handle("在吗", context="上次说要出门", intent="在寒暄") == "在的。"
    call = llm.calls[0]
    assert call["system"] == agent.system
    assert "上次说要出门" in call["message"]
    assert "用户意图：在寒暄" in call["message"]
    assert "用户问题：在吗" in call["message"]
    assert len(llm.calls) == 1
