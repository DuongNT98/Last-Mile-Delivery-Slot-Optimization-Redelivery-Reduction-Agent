# LOG-C2-034 — Last-Mile Delivery Slot Optimization & Redelivery Reduction Agent

> **Category**: Cat 2 (multiple processing steps combined to complete one specific use case)
> **Industry**: Logistics

## Overview

This template ingests a carrier's daily delivery manifest and, for each parcel, forecasts the
delivery time slot most likely to succeed based on historical delivery outcomes for that area and
time window. It proactively contacts the recipient ahead of the first delivery attempt with the
top three candidate slots, tracks the recipient's confirmation, and writes the confirmed slot back
to the carrier's own system. If a delivery attempt still fails, it offers a limited number of
reschedule slots before falling back to a convenience-store (or equivalent) pickup option once the
retry limit is exceeded. Finally, it produces an aggregate, area-level workload report for
planning purposes — the report is generated deterministically and never contains individual
recipient or parcel identifiers; a short narrative summary can optionally be added by a language
model, and its absence (no model configured) is a normal, fully-supported outcome, not an error.

It does not decide carrier routing, staffing levels, or pricing — those decisions remain outside
its scope. It also does not communicate with recipients through channels other than the ones it is
configured for, and it does not retain communication content beyond what is needed to track a
delivery's confirmation status.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and operational documentation
```

See `docs/` for the design spec and test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
