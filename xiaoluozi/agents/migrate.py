"""CVM migration. The Knot call itself lives in knot.py."""

from xiaoluozi.agents.knot import BUILTIN_KNOT_SPECS, KnotAgent, open_knot, split_knot_endpoint

DEFAULT_KNOT_API_URL = BUILTIN_KNOT_SPECS[0].url


class MigrateAgent(KnotAgent):
    spec = BUILTIN_KNOT_SPECS[0]
    id = spec.id
    description = spec.description
    env_keys = ("KNOT_API_TOKEN", "KNOT_API_URL", "KNOT_AGENT_MIGRATE")
