from xiaoluozi.agents.request import agent_request
from xiaoluozi.skills import require_skills, system_with_skills
from xiaoluozi.tools import tool_specs


def install(agent, llm, skills=(), env=None) -> None:
    agent._llm = llm
    agent._skills = require_skills(agent.skill_ids, skills)
    agent._env = dict(env or {})


def reply(agent, message: str, *, context: str = "", intent: str = "") -> str:
    return agent._llm.answer(
        system_with_skills(agent.system, agent._skills),
        agent_request(message, context, intent),
        tools=tool_specs(agent._skills),
        env=agent._env,
    )
