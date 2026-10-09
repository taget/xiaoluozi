from xiaoluozi.agents.support import install, reply


class QaAgent:
    """Answer a question with one chat completion.

    It does not choose agents, call tools, or write memory.
    Skills named in skill_ids are appended to the system prompt.
    """

    id = "qa"
    description = "回答需要说明或解释的问题。用户在提问时用这个。"
    system = "你是小落子的问答代理。用简短的中文直接回答问题。不知道就说不知道，不要编造。"
    skill_ids = ()
    env_keys = ()

    def __init__(self, llm, skills=(), env=None):
        install(self, llm, skills, env)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return reply(self, message, context=context, intent=intent)
