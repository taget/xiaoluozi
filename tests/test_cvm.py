from tests.fakes import FakeLlm, FakeMemory, FakeModel
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.agents.cvm import CvmAgent
from xiaoluozi.loop import Loop
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router
from xiaoluozi.skills import SkillCatalog


def _route_answer(agent="cvm", intent="ask"):
    return {
        "agent_id": {"type": "choice", "choice": agent},
        "intent": {"type": "choice", "choice": intent},
    }


def test_cvm_agent_appends_yunxiao_ops_and_calls_the_llm_once():
    llm = FakeLlm("先看库存水位。")
    agent = CvmAgent(
        llm,
        SkillCatalog().load(CvmAgent.skill_ids),
        env={"YUNXIAO_SECRET_ID": "sid-test-value", "YUNXIAO_SECRET_KEY": ""},
    )

    assert agent.id == "cvm"
    assert "CVM" in agent.description
    assert agent.skill_ids == ("yunxiao-ops",)
    assert agent.handle("看看广州库存", context="上次问过宿主机", intent="在提问") == "先看库存水位。"

    system = llm.calls[0]["system"]
    assert system.startswith(agent.system)
    assert "yunxiao" in system
    assert "beacon" in system
    message = llm.calls[0]["message"]
    assert "上次问过宿主机" in message
    assert "用户意图：在提问" in message
    assert "用户问题：看看广州库存" in message
    assert llm.calls[0]["tools"][0]["function"]["name"] == "Bash"
    assert llm.calls[0]["env"]["YUNXIAO_SECRET_ID"] == "sid-test-value"
    assert len(llm.calls) == 1


def test_laya_chooses_cvm_then_the_agent_calls_the_llm():
    model = FakeModel([_route_answer()])
    llm = FakeLlm("先看库存水位。")
    agent = CvmAgent(llm, SkillCatalog().load(CvmAgent.skill_ids))
    registry = Registry([ChatAgent(FakeLlm()), agent])
    result = Loop(
        registry=registry,
        router=Router(model, registry, selectable=["chat", "cvm"]),
        model=model,
        memory=FakeMemory(),
    ).handle("看看广州库存")

    assert result.text.startswith("先看库存水位。\n\n选用 cvm。")
    assert len(model.calls) == 1
    assert "- cvm：" in model.calls[0]["state"]
    assert len(llm.calls) == 1
    assert "yunxiao" in llm.calls[0]["system"]
