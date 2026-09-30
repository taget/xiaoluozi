from xiaoluozi.agents.request import agent_request


class ChatAgent:
    """Everyday conversation, and the fallback when no specialist fits.

    handle asks the LLM once. It does not choose agents or write memory.
    """

    id = "chat"
    description = "日常对话。没有更合适的专职代理时，用这个兜底。"
    system = "你是小落子的日常对话代理。用简短的中文接住这句话。不要编造对方没说过的事。"

    def __init__(self, llm):
        self._llm = llm

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return self._llm.answer(self.system, agent_request(message, context, intent))
