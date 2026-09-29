"""Test doubles. They record calls; they do not talk to Venus or Hindsight."""


class FakeModel:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        if not self.script:
            raise AssertionError("unexpected model call")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeMemory:
    def __init__(self, error=None):
        self.error = error
        self.turns = []
        self.attempts = 0

    def retain_turn(self, turn):
        self.attempts += 1
        if self.error:
            raise self.error
        self.turns.append(turn)


class SpyAgent:
    def __init__(self, agent_id, description):
        self.id = agent_id
        self.description = description
        self.handled = []

    def handle(self, message):
        self.handled.append(message)
        return "spy-reply"
