# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `Graph` (`src/graph/graph.py`)
- **L1 Base**: AgentBaseGraph (L1 direct) — outer graph. Cat 2: `main` slot wraps an
  inner `BaseGraph` subgraph (`DeliverySlotWorkflowGraph`) via a `GraphNode`
  (`DeliverySlotWorkflowGraphNode`, also defined in `src/graph/graph.py`).
- **Three-Layer Separation**:
  - State: flat TypedDict composition (`src/schemas/state.py`, no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution; outer `add_edges()` not overridden)

## Architecture Overview

### Node Configuration — Outer graph

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version, session_id, trust_level | — | — | InitializeNode (default) |
| pre_process | `ManifestIngestNode` — validate + normalize the carrier manifest, S-2 credential scan, serialize inner input | `user_input` (JSON) | `manifest_parcels`, `validated_input` | `FunctionNode` |
| main | `DeliverySlotWorkflowGraphNode` — dispatches the inner delivery-slot workflow subgraph | `validated_input` | `forecasted_slots`, `contact_dispatch_status`, `confirmed_slots`, `retry_counts`, `failed_delivery_state`, `konbini_reservations` | `GraphNode` |
| post_process | `OptimizeReportNode` — aggregate-only area/route optimization report (S-3 gated) | merged inner outputs | `optimization_report`, `formatted_output` | `FunctionNode` |
| finalize | response_metadata, total_time_ms | — | — | FinalizeNode (default) |

### Node Configuration — Inner subgraph (`DeliverySlotWorkflowGraph`, `src/graph/domain_workflow_graph.py`)

| Node | Responsibility |
|------|-----------------|
| slot_forecast | `SlotForecastNode` — deterministic delivery-success-probability forecast, ranks top-3 candidate slots per parcel |
| recipient_contact | `RecipientContactNode` — mock LINE/SMS dispatch presenting the top-3 forecasted slots |
| slot_confirm | `SlotConfirmNode` — tracks recipient confirmation; writes the confirmed slot back to the carrier (mock); handles no-response |
| failed_delivery | `FailedDeliveryNode` — on a failed attempt, offers up to 3 reschedule slots and enforces the retry limit (`max_reschedule_retries`, default 3) |
| konbini_pickup | `KonbiniPickupNode` — after the retry limit is exceeded, reserves konbini pickup (mock) |

### Data Flow

```
Outer:
START → initialize → pre_process(ManifestIngestNode) → main(DeliverySlotWorkflowGraphNode)
      → post_process(OptimizeReportNode) → finalize → END

Inner (invoked by main via GraphNode.get_subgraph().invoke(extract_input(state), ctx)):
START → slot_forecast → recipient_contact → slot_confirm → failed_delivery → konbini_pickup → END
```

### LLM Narrative (`generation_mode: "llm"`, `OptimizeReportNode`)

The deterministic rollup (`src/services/delivery_service.py::build_optimization_report`) IS the
report — every field of `optimization_report` except `narrative_summary` comes from it, always.
The LLM only adds an optional one-paragraph narrative summarizing that rollup for a carrier ops
planner; it never influences report content and is never given raw per-parcel data.

- **Resolution** (`resolve_llm()` in `src/nodes/optimize_report_node.py`): built fresh per
  invocation inside `execute()` from `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` /
  `AZURE_OPENAI_DEPLOYMENT`, resolved via `InvocationContext.from_state(state).secrets` — never
  cached on `self` (a node instance is reused across every invocation via the registry's LRU
  cache; caching a client built from one caller's secrets would leak it to the next caller).
- **Secrets placement**: all three keys are declared under `config/agent.yaml`
  `requires.extras: ["openai"]`, deliberately **not** under `requires.secrets` — that field is
  enforced via `require_at_compile()` (a hard compile-time 503 if absent), which would contradict
  the graceful-degrade design below. Same precedent as the scaffold's own `ANTHROPIC_API_KEY`
  handling.
- **Failure contract — two distinct cases, deliberately different**:
  1. **No secret configured, or any other resolution failure** (missing key, malformed
     `AZURE_OPENAI_ENDPOINT`, etc.) — `resolve_llm()` returns `None`; `execute()` silently keeps
     the deterministic rollup with no `narrative_summary`. This is the default production shape
     today (no Azure key exists in any environment yet) and is not an error.
  2. **A resolved client's `.complete()` call fails or returns empty content** — reported as
     `status=error` with a descriptive `error_log` entry, not silently degraded. Rationale
     (pre-existing, unchanged by this addition): silently dropping the narrative would hand the
     caller a report that looks complete while the piece it specifically asked for is missing.
- **Known operational limit**: `AZURE_OPENAI_ENDPOINT` must be the bare resource endpoint
  (`https://<resource>.services.ai.azure.com`, no `/openai` path segment anywhere) —
  `AzureOpenAIClient.__init__`'s `_to_openai_base_url()` raises `ValueError` on a value containing
  one, rather than rewriting it.

Data crossing the GraphNode boundary is JSON-string-encoded: outer `pre_process` sets
`validated_input = json.dumps({"parcels": normalized})`; `extract_input()` forwards that
string; the first inner node (`slot_forecast`) `json.loads()`s it back. Config
(`max_reschedule_retries`) reaches the inner graph via `_parent_config()`, not state.
`merge_output()` maps the inner `get_output()` dict back onto the outer state (only the
changed keys).

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `manifest_parcels` | `NotRequired[list[dict]]` | Normalized carrier manifest (parcel_id, recipient_contact, area, time_window) | No |
| `forecasted_slots` | `NotRequired[dict]` | parcel_id -> top-3 ranked `{slot, score}` forecasts | No |
| `contact_dispatch_status` | `NotRequired[dict]` | parcel_id -> `"sent"` \| `"skipped"` | No |
| `confirmed_slots` | `NotRequired[dict]` | parcel_id -> `{slot, confirmed, written_back}` | No |
| `retry_counts` | `NotRequired[dict]` | parcel_id -> reschedule attempt count | No |
| `failed_delivery_state` | `NotRequired[dict]` | parcel_id -> `{reschedule_offers, escalated}` | No |
| `konbini_reservations` | `NotRequired[dict]` | parcel_id -> `{store_id, reserved}` | No |
| `optimization_report` | `NotRequired[dict]` | Aggregate-only area/route rollup (never parcel_id/recipient_contact) | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [ ] ConnectionPolicy (retry/timeout strategy) — not applicable; the `OptimizeReportNode` LLM
      call (the only live external network call in this template) has no retry — a failure surfaces
      immediately as `status=error` by design (see "LLM Narrative" above), not a
      retry-then-degrade policy
- [x] SecurityViolationError (framework-raised on S-1/S-2/S-3 violations)
- [x] S-2: `_extra_security_gate_input()` — not implemented as a separate hook; the S-2
      credential/PII scan is performed deterministically inside `ManifestIngestNode.execute()`
      itself (recipient_contact shape + credential-shaped rejection), since the check must
      raise a business ERROR result rather than a non-raising hook mutation.
- [x] S-3: `_extra_security_gate_output()` — `OptimizeReportNode` implements the
      **aggregate-only preservation variant**: verifies the final report contains no
      `parcel_id` / `recipient_contact` keys or values before it leaves the agent (the named
      compliance risk from the proposal §4).
- [x] S-4: `emit_trace_event()` — at least one domain-specific event inside every node's
      `execute()` (`manifest_ingested`, `slots_forecasted`, `recipient_contacted`,
      `slot_confirmation_tracked`, `failed_delivery_evaluated`, `konbini_pickup_evaluated`,
      `optimization_report_generated`), plus dispatch/completion events in the `GraphNode`
      wrapper's `extract_input()`/`merge_output()` hooks.

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — `DeliverySlotWorkflowGraphNode` wraps the inner
  `DeliverySlotWorkflowGraph` (`BaseGraph`).
- **Composition target**: `src/graph/domain_workflow_graph.py::DeliverySlotWorkflowGraph`
- **Error propagation strategy**: `propagate` (fail fast — inner errors surface as
  `SubgraphError` to the outer graph; no HITL in this template, `propagate_hitl=False`).

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Fixed multi-step domain workflow, no autonomous think/act loop needed |
| Composition pattern | Flat 3-slot (Cat 1 style) | GraphNode + inner BaseGraph (Cat 2) | GraphNode + inner BaseGraph | Cat 2 requires the outer/inner split per `gate-composition`; 5 domain steps map to the inner subgraph, manifest ingest/report generation stay at the outer boundary |
| Recipient dispatch / carrier write-back / konbini reservation | Live external API integration | Deterministic mock service functions | Deterministic mock | No external carrier/LINE/SMS/konbini API credentials or contracts are available yet; `src/services/delivery_service.py` isolates the mock logic behind pure functions so a real integration can replace them later without touching node contracts |
