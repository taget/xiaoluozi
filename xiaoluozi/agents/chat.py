from xiaoluozi.agents.request import agent_request
from xiaoluozi.skills import require_skills, system_with_skills


class ChatAgent:
    """Everyday conversation, and the fallback when no specialist fits.

    handle asks the LLM once. It does not choose agents or write memory.
    Skills named in skill_ids are appended to the system prompt.
    """

    id = "chat"
    description = "日常对话。没有更合适的专职代理时，用这个兜底。"
    system = "你是小落子的日常对话代理。用简短的中文接住这句话。不要编造对方没说过的事。"
    skill_ids = ()

    def __init__(self, llm, skills=()):
        self._llm = llm
        self._skills = require_skills(self.skill_ids, skills)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return self._llm.answer(
            system_with_skills(self.system, self._skills),
            agent_request(message, context, intent),
        )
