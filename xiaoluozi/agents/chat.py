class ChatAgent:
    """Everyday conversation, and the fallback when no specialist fits.

    handle is one chat completion. It does not write memory or choose agents.
    """

    id = "chat"
    description = "日常对话。没有更合适的专职代理时，用这个兜底。"

    def __init__(self, model):
        self._model = model

    def handle(self, message: str) -> str:
        return self._model.complete(
            [
                {
                    "role": "system",
                    "content": "你是小落子，负责日常对话。用中文直接回答用户这一句话，简洁、具体。",
                },
                {"role": "user", "content": message},
            ]
        )
