from tests.fakes import FakeLlm
from xiaoluozi.agents.knot import knot_specs
from xiaoluozi.agents.perf_gap import PerfGapAgent
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router
from xiaoluozi.skills import SkillCatalog
from xiaoluozi.tools import tool_specs
from tests.fakes import FakeModel


def test_perf_gap_answers_from_the_sop_without_tools():
    llm = FakeLlm("现在不能认定根因。先核对吞吐口径。")
    agent = PerfGapAgent(llm, SkillCatalog().load(("perf-gap",)))

    assert agent.handle("云主机比物理机慢了 30%", context="上次问过库存", intent="在提问") == (
        "现在不能认定根因。先核对吞吐口径。"
    )
    assert agent.consultable is True
    assert getattr(agent, "exclusive", False) is False
    assert tool_specs(agent._skills) == []
    system = llm.calls[0]["system"]
    assert "现在不能认定根因" in system
    assert "collect_perf.sh" in system
    assert "不要把业务差距直接写成虚拟化开销" in system
    assert "bash collect_perf.sh" in system
    assert "上次问过库存" in llm.calls[0]["message"]
    assert llm.calls[0]["tools"] == []


def test_perf_gap_can_be_a_read_only_consultant():
    agent = PerfGapAgent(FakeLlm(), SkillCatalog().load(("perf-gap",)))
    registry = Registry([agent])
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "perf_gap", "confidence": 0.9},
                "consultant_1": {"type": "choice", "choice": "none"},
            }
        ]
    )

    decision = Router(model, registry).route("云主机吞吐比物理机低三成")

    assert decision.agent_id == "perf_gap"
    assert decision.consultants == ()
    assert "perf_gap" in model.calls[0]["questions"]["consultant_1"]["criteria"]


def test_a_knot_alias_cannot_replace_perf_gap():
    try:
        knot_specs(
            {
                "KNOT_AGENT_PERF_GAP": "http://knot.woa.com/apigw/api/v1/agents/agui/abc",
                "KNOT_AGENT_PERF_GAP_DESCRIPTION": "性能。",
            }
        )
    except ValueError as exc:
        assert "perf-gap" in str(exc)
    else:
        raise AssertionError("perf-gap must not become a second Knot agent")
