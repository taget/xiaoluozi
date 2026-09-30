from xiaoluozi.agents.request import agent_request


class QaAgent:
    """Answer a question with one chat completion and a fixed system prompt.

    It does not choose agents, call tools, or write memory.
    """

    id = "qa"
    description = "回答需要说明或解释的问题。用户在提问时用这个。"
    system = "你是小落子的问答代理。用简短的中文直接回答问题。不知道就说不知道，不要编造。"

    def __init__(self, llm):
        self._llm = llm

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return self._llm.answer(self.system, agent_request(message, context, intent))
