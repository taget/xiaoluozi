class Registry:
    """In-process agents. The router reads descriptions; only the loop calls handle."""

    def __init__(self, agents: list):
        self._agents = []
        self._by_id = {}
        for agent in agents:
            if agent.id in self._by_id:
                raise ValueError(f"重复的代理 {agent.id}")
            self._agents.append(agent)
            self._by_id[agent.id] = agent

    def get(self, agent_id: str):
        return self._by_id[agent_id]

    def ids(self) -> set[str]:
        return set(self._by_id)

    def listing(self) -> list[tuple[str, str]]:
        return [(agent.id, agent.description) for agent in self._agents]
