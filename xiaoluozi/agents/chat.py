from xiaoluozi.agents.support import install, reply, stream_reply


class ChatAgent:
    """Everyday conversation, and the fallback when no specialist fits.

    handle asks the LLM once. It does not choose agents or write memory.
    Skills named in skill_ids are appended to the system prompt.
    """

    id = "chat"
    description = "日常对话。没有更合适的专职代理时，用这个兜底。"
    system = "你是小落子的日常对话代理。用简短的中文接住这句话。不要编造对方没说过的事。"
    skill_ids = ()
    env_keys = ()

    def __init__(self, llm, skills=(), env=None):
        install(self, llm, skills, env)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return reply(self, message, context=context, intent=intent)

    def stream(self, message: str, *, context: str = "", intent: str = ""):
        yield from stream_reply(self, message, context=context, intent=intent)
