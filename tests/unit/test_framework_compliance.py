# LOG-C2-034 - Framework compliance tests TC-01..TC-08 (CoE Code Review R1).
# Reference shape: adapted from a sibling Cat 1 template's framework compliance
# test suite to this template's real architecture (Cat 2: outer ManifestIngestNode pre_process +
# GraphNode-wrapped inner slot_forecast/recipient_contact/slot_confirm/failed_delivery/konbini_pickup
# + OptimizeReportNode post_process).

import json
import os
import re

import pytest
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.nodes import (
    failed_delivery_node,
    konbini_pickup_node,
    manifest_ingest_node,
    optimize_report_node,
    recipient_contact_node,
    slot_confirm_node,
    slot_forecast_node,
)
from src.schemas.state import State

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
TRUST = TrustLevel.VERIFIED_EXTERNAL.value

SAMPLE_MANIFEST = json.dumps(
    {"parcels": [{"parcel_id": "P1", "recipient_contact": "090-1234-5678", "area": "Shibuya", "time_window": "18:00-20:00"}]}
)


def _src_files():
    for root, _d, files in os.walk(_SRC):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


# TC-01 - State is a flat TypedDict extending AgentState; added fields are
# JSON-serializable primitives (NotRequired-wrapped).
class TestTC01StateContract:
    def test_state_is_typeddict_extending_agent_state(self):
        assert hasattr(State, "__annotations__")
        assert "user_input" in State.__annotations__
        assert set(AgentState.__annotations__).issubset(set(State.__annotations__))

    def test_added_fields_are_json_safe(self):
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        assert added, "State must declare agent-specific fields"
        for name in added:
            ann_str = str(State.__annotations__[name])
            assert any(t in ann_str for t in ("str", "int", "bool", "float", "list", "dict")), (
                f"{name}: {ann_str} - fields must be JSON-serializable primitives/containers"
            )


# TC-02 - Empty/missing/invalid input yields a fail-closed ERROR outcome, no raise.
class TestTC02Validation:
    def test_empty_input_no_raise(self):
        out = manifest_ingest_node.ManifestIngestNode().execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_credential_shaped_contact_no_raise(self):
        bad_manifest = json.dumps(
            {"parcels": [{"parcel_id": "P1", "recipient_contact": "eyJabc.def.ghi", "area": "A", "time_window": "T"}]}
        )
        out = manifest_ingest_node.ManifestIngestNode().execute({"user_input": bad_manifest})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]


# TC-03 - No JWT / API keys / secrets in src/; no direct os.environ reads (entry-point auth boundary exempted).
class TestTC03NoCredentials:
    def test_no_credential_literals(self):
        pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
        offenders = [fp for fp in _src_files() if pat.search(open(fp, encoding="utf-8").read())]
        assert offenders == []

    def test_no_os_environ_secret_reads(self):
        offenders = []
        for fp in _src_files():
            if "api" in fp.replace("\\", "/").split("/"):
                continue  # entry-point auth boundary exception (see framework docs)
            if "os.environ" in open(fp, encoding="utf-8").read():
                offenders.append(fp)
        assert offenders == []


# TC-04 - InvocationContext is never stored in State after invoke.
class TestTC04ContextIsolation:
    def test_no_invocationcontext_in_state_after_invoke(self):
        from src.graph.graph import Graph

        agent = Graph()
        agent.compile()
        ctx = InvocationContext(session_id="tc04", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="tester-tc04")
        result = agent.invoke(SAMPLE_MANIFEST, ctx=ctx)
        for v in result.values():
            assert not isinstance(v, InvocationContext)

    def test_from_state_available(self):
        assert hasattr(InvocationContext, "from_state")


# TC-05 - Domain events: outer nodes emit >=1 domain event; no node under
# src/nodes/ ever re-emits a framework backbone lifecycle event.
class TestTC05Audit:
    def test_pre_process_emits_domain_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(manifest_ingest_node, "emit_trace_event", lambda e, p, s: events.append(e))
        out = manifest_ingest_node.ManifestIngestNode().execute({"user_input": SAMPLE_MANIFEST})
        assert out["status"] == AgentStatus.SUCCESS
        assert "manifest_ingested" in events
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_source_has_no_backbone_events(self):
        pat = re.compile(r'emit_trace_event\(\s*["\'](node_start|node_complete|node_error|node_skip)["\']')
        offenders = [fp for fp in _src_files() if pat.search(open(fp, encoding="utf-8").read())]
        assert offenders == []


# TC-06 / TC-07 - S-2/S-3 gates are @final on FunctionNode (overriding raises TypeError at class def).
class TestTC0607FinalGates:
    def test_input_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadIn(FunctionNode):  # noqa: N801
                def _security_gate_input(self, state):
                    return state

    def test_output_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadOut(FunctionNode):  # noqa: N801
                def _security_gate_output(self, result):
                    return result

    def test_extra_hook_is_overridable(self):
        assert (
            optimize_report_node.OptimizeReportNode._extra_security_gate_output
            is not FunctionNode._extra_security_gate_output
        )

    def test_output_gate_blocks_recipient_leak(self):
        # The @final S-3 hook actually fires (not vacuous): a report leaking
        # recipient_contact is blocked by the domain-specific aggregate-only hook.
        node = optimize_report_node.OptimizeReportNode()
        out = node._extra_security_gate_output({"optimization_report": {"recipient_contact": "090-1234-5678"}})
        assert out["status"] == AgentStatus.ERROR


# TC-08 - required_trust_level declared valid + enforced: insufficient trust -> ERROR, no raise.
class TestTC08TrustGate:
    def test_declared_trust_levels_valid(self):
        for cls in (
            manifest_ingest_node.ManifestIngestNode,
            slot_forecast_node.SlotForecastNode,
            recipient_contact_node.RecipientContactNode,
            slot_confirm_node.SlotConfirmNode,
            failed_delivery_node.FailedDeliveryNode,
            konbini_pickup_node.KonbiniPickupNode,
            optimize_report_node.OptimizeReportNode,
        ):
            assert cls.required_trust_level in (TrustLevel.ANONYMOUS, TrustLevel.VERIFIED_EXTERNAL, TrustLevel.INTERNAL)

    def test_insufficient_trust_returns_error(self):
        node = manifest_ingest_node.ManifestIngestNode()
        out = node({"caller_trust_level": TrustLevel.ANONYMOUS.value, "user_input": SAMPLE_MANIFEST})
        assert str(out.get("status")).lower().endswith("error")

    def test_sufficient_trust_succeeds(self):
        node = manifest_ingest_node.ManifestIngestNode()
        out = node({"caller_trust_level": TRUST, "user_input": SAMPLE_MANIFEST})
        assert out["status"] == AgentStatus.SUCCESS
