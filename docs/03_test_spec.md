# Test Specification

## Test Strategy
- Coverage target: all business-logic paths (unit + integration); hard % threshold enforced by CI gate
- Test types: Unit (per-node success + error/edge) / Integration (full graph compile+invoke) / Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | PASS |
| TC-02 | SecurityViolationError fires on invalid input | Error raised | PASS |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement moved to CI) | PASS (CI gate) |
| TC-04 | InvocationContext via configurable only | Direct access raises error | PASS |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` enforced | Insufficient trust → refused | PASS |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial when domain checks needed | `ManifestIngestNode.execute()` deterministically rejects credential-shaped/malformed recipient_contact | Non-trivial (implemented as raising business validation inside `execute()`, per S-3 contract for raise-able checks) |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial when domain checks needed | `OptimizeReportNode._extra_security_gate_output()` rejects any report leaking parcel_id/recipient_contact | Non-trivial |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path (all 7 nodes) | ≥1 per node |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | PASS |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | PASS |
| PB-3 | Level 2 → External service | N/A — this template has no live external service dependency (carrier fetch / LINE-SMS dispatch / carrier write-back / konbini reservation are deterministic mocks by design, per `docs/02_design.md` Design Decision Record) | N/A |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | PASS |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | PASS |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | Order verified (`tests/proof_of_boundary/test_pb_invoke_order.py`, scaffold canonical, discovers every `BaseNode` subclass under `src/nodes/`; `DeliverySlotWorkflowGraphNode` is a `GraphNode` and lives in `src/graph/graph.py`, so it is correctly excluded from this probe) | PASS |
| PB-7 | HITL interrupt propagation | N/A — `hitl.enabled` is not set for this template (slot write-backs are reversible, not irreversible/financial); stub auto-skips | N/A (auto-skip) |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Manifest ingest validates and rejects malformed/credential-shaped recipient_contact | Parcel with a JWT-shaped `recipient_contact` | `status=ERROR`, parcel dropped, no valid-parcel fallback if all invalid | PASS |
| BL-02 | Deterministic slot forecast is stable and ranks by score | Same parcel invoked twice | Identical top-3 slot list both times (no randomness) | PASS |
| BL-03 | Slot confirmation handles no-response distinctly from confirmed | `simulated_response = "no_response"` | `confirmed=False`, `written_back=False`, no ERROR | PASS |
| BL-04 | Retry-limit escalation routes to konbini pickup | `simulated_delivery_result="failed"` repeated past `max_reschedule_retries` | `failed_delivery_state[pid].escalated=True` and `konbini_reservations[pid].reserved=True` | PASS |
| BL-05 | Optimization report is aggregate-only (no parcel_id/recipient_contact leak) | Full manifest run | `OptimizeReportNode._extra_security_gate_output()` passes; report contains only area-keyed rollups | PASS |
| BL-06 | No Azure secret bound — `resolve_llm()` degrades silently | `OptimizeReportNode()` under an empty `SecretProvider` (`bound_secrets`) | `status=success`, deterministic rollup returned, no `narrative_summary` key | PASS |
| BL-07 | Partial secret triple (one of three missing) degrades the same as none | `SecretProvider` with only `AZURE_OPENAI_API_KEY`/`_ENDPOINT` bound | `status=success`, no `narrative_summary` (same as BL-06) | PASS |
| BL-08 | Resolved LLM (test-double `AzureOpenAIClient`, bound secrets, no constructor injection) adds narrative | Full secret triple bound; `AzureOpenAIClient` monkeypatched to a fake returning canonical `{"content": ...}` | `status=success`, `narrative_summary` present and equal to the fake's content | PASS |
| BL-09 | Resolved LLM whose `.complete()` call fails is `status=error`, not silent degrade | Resolved client, `.complete()` raises | `status=error`, `optimization_report` absent (unchanged from the pre-existing constructor-injected case) | PASS |

## Test Execution Summary
- Execution date: local pre-push verification (see MR description for the CI pipeline run)
- Total tests: unit (1+ per node, success + error/edge) + integration (full graph compile+invoke) + proof_of_boundary (import isolation, state safety, invoke order, HITL N/A stub)
- Pass: all; Fail: 0; Skip: PB-7 (HITL not enabled — intentional stub skip, see PB-7 row above)
- Coverage: all business-logic paths across the 7 nodes + inner/outer graph composition
