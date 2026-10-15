from types import SimpleNamespace

from tests.fakes import FakeLlm
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.wiring import _skill_ids


def test_chat_agent_sends_context_and_intent_to_the_llm():
    llm = FakeLlm("在的。")
    agent = ChatAgent(llm)

    assert agent.id == "chat"
    assert "日常" in agent.description
    assert "兜底" in agent.description
    assert agent.handle("在吗", context="上次说要出门", intent="在寒暄") == "在的。"
    call = llm.calls[0]
    assert call["system"].startswith(agent.system)
    assert "公开检索" in call["system"]
    assert call["tools"][0]["function"]["name"] == "Search"
    assert "这次没有找到专职代理" not in call["system"]
    assert "上次说要出门" in call["message"]
    assert "用户意图：在寒暄" in call["message"]
    assert "用户问题：在吗" in call["message"]
    assert len(llm.calls) == 1


def test_fallback_note_is_appended_after_the_prompt():
    llm = FakeLlm("我先回答能说的部分。")
    agent = ChatAgent(llm)
    agent.routing_note = "这次没有找到专职代理，由你兜底。\n{\"choice\": \"none\"}"

    agent.handle("随便说说")

    system = llm.calls[0]["system"]
    assert system.index("公开检索") < system.index("这次没有找到专职代理")
    assert '"choice": "none"' in system


def test_empty_chat_skills_keep_the_system_prompt():
    llm = FakeLlm("在的。")
    agent = ChatAgent(llm, skill_ids=())

    agent.handle("在吗")

    assert llm.calls[0]["system"] == ChatAgent.system
    assert llm.calls[0]["tools"] == []


def test_chat_skills_defaults_to_search_and_can_be_cleared():
    assert _skill_ids(ChatAgent, SimpleNamespace(dotenv={})) == ("search",)
    assert _skill_ids(ChatAgent, SimpleNamespace(dotenv={"CHAT_SKILLS": ""})) == ()
    assert _skill_ids(ChatAgent, SimpleNamespace(dotenv={"CHAT_SKILLS": "search, search"})) == ("search",)
