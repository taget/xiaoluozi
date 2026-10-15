from xiaoluozi.agents.request import agent_request
from xiaoluozi.connectors import require_connectors
from xiaoluozi.skills import require_skills, system_with_skills
from xiaoluozi.tools import tool_specs


def install(agent, llm, skills=(), env=None) -> None:
    agent._llm = llm
    agent._skills = require_skills(agent.skill_ids, skills)
    agent._connectors = require_connectors(getattr(agent, "connector_ids", ()), agent._skills)
    agent._env = dict(env or {})


def reply(agent, message: str, *, context: str = "", intent: str = "") -> str:
    system, request, tools, env, remember = _request(agent, message, context, intent)
    return agent._llm.answer(
        system, request, tools=tools, env=env, remember=remember, recall_query=message
    )


def stream_reply(agent, message: str, *, context: str = "", intent: str = ""):
    system, request, tools, env, remember = _request(agent, message, context, intent)
    source = getattr(agent._llm, "stream", None)
    if source is None:
        text = agent._llm.answer(
            system, request, tools=tools, env=env, remember=remember, recall_query=message
        )
        if text:
            yield text
        return
    yield from source(system, request, tools=tools, env=env, remember=remember, recall_query=message)


def _request(agent, message: str, context: str, intent: str):
    system = system_with_skills(agent.system, agent._skills)
    note = (getattr(agent, "routing_note", "") or "").strip()
    if note:
        system = f"{system}\n\n{note}"
    return (
        system,
        agent_request(message, context, intent, getattr(agent, "roster_note", "") or ""),
        tool_specs(agent._skills),
        agent._env,
        getattr(agent, "remembers", True),
    )
