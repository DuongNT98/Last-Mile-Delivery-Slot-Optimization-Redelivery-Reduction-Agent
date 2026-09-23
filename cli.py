"""AGENTIC STAR Marketplace entrypoint — one-shot Pod process.

Referenced by this repo's Dockerfile as the image `CMD`. Compiles the agent,
provisions its secrets, then hands off to shared.bootstrap.marketplace_app
for the Marketplace lifecycle (identity, input, events, terminal delivery,
exit). Mirrors agentcore's own `agents/base/chat_agent/cli.py` (the pattern
this file was copied from).

`namespace=` here is the Marketplace secret-provisioning namespace — a different
concept from `config/agent.yaml`'s AgentRegistry `namespace:` key that happens to
share its value. Mirrors
`src/api/server.py`'s existing `secrets_factory(namespace="log",
agent_name="log-c2-034")` call shape rather than a per-template value: one
Marketplace Pod deploys exactly one template, so there is no cross-template
secret-path collision to guard against, and `log` is filled in at
scaffold init the same way `server.py` already expects it to be.
"""

from pathlib import Path

from framework.utils.config_loader import load_agent_config
from shared.bootstrap.marketplace_app import run_agent_marketplace
from src.graph.graph import Graph

# Add config overrides here to set values without touching config/config.yaml.
extend_config = {}

if __name__ == "__main__":
    run_agent_marketplace(
        Graph,  # src/graph/graph.py's Graph class
        agent_name="log-c2-034",
        namespace="log",
        config={**load_agent_config(Path(__file__).resolve().parent), **extend_config},
    )
