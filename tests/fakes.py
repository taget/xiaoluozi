"""Test doubles. They record calls; they do not talk to Venus or Hindsight."""


class FakeModel:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def decide(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        if not self.script:
            raise AssertionError("unexpected model call")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeMemory:
    def __init__(self, error=None, memories=None):
        self.error = error
        self.turns = []
        self.decision_batches = []
        self.attempts = 0
        self.memories = list(memories or [])
        self.queries = []
        self.agent_ids = []

    def recall(self, query, agent_id=""):
        self.queries.append(query)
        self.agent_ids.append(agent_id)
        return list(self.memories)

    def retain_turn(self, turn):
        self.attempts += 1
        if self.error:
            raise self.error
        self.turns.append(turn)

    def retain_decisions(self, decisions):
        if self.error:
            raise self.error
        self.decision_batches.append(list(decisions))


class FakeLlm:
    def __init__(self, text="带伞。", error=None):
        self.text = text
        self.error = error
        self.calls = []

    def answer(self, system, message):
        self.calls.append({"system": system, "message": message})
        if self.error is not None:
            raise self.error
        return self.text


class SpyAgent:
    def __init__(self, agent_id, description):
        self.id = agent_id
        self.description = description
        self.handled = []
        self.requests = []

    def handle(self, message, *, context="", intent=""):
        self.handled.append(message)
        self.requests.append({"message": message, "context": context, "intent": intent})
        return "spy-reply"
