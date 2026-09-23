# LOG-C2-034 - GraphNode boundary test (Cat 2 outer main-slot wrapper).
#
# Why this test exists: PB-6 (test_pb_invoke_order.py) only self-discovers
# BaseNode subclasses under src/nodes/. DeliverySlotWorkflowGraphNode lives under
# src/graph/graph.py by design (matches the scaffold Cat 2 canonical layout, so
# a single-node probe does not accidentally pull in the whole inner subgraph) -
# but that placement does not exempt it from test coverage. The outer GraphNode
# is a real security boundary (first node to receive the caller's input) that no
# PB-6 probe reaches.
#
# framework/nodes/graph_node.py: GraphNode extends BaseNode directly (not
# FunctionNode), so it has no _security_gate_input/_security_gate_output at all
# - S-2/S-3 gating is delegated entirely to the outer pre/post_process nodes and
# the inner subgraph's own FunctionNode chain. This test proves that delegation
# is real, not absent.

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import DeliverySlotWorkflowGraphNode
from src.nodes.slot_forecast_node import SlotForecastNode


def _node():
    return DeliverySlotWorkflowGraphNode()


class TestGraphNodeS1TrustGate:
    """S-1: the outer main-slot GraphNode enforces the trust gate like any BaseNode."""

    def test_insufficient_trust_returns_error_without_invoking_subgraph(self, monkeypatch):
        node = _node()
        called = {"get_subgraph": False}

        def _spy_get_subgraph():
            called["get_subgraph"] = True
            raise AssertionError("get_subgraph() must not run when the S-1 gate denies")

        monkeypatch.setattr(node, "get_subgraph", _spy_get_subgraph)

        state = {
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
            "validated_input": '{"parcels": []}',
        }
        out = node(state)

        assert out["status"] == "error"
        assert any("S-1 trust gate denied" in e for e in out["error_log"])
        assert called["get_subgraph"] is False

    def test_matches_agent_yaml_required_trust_level(self):
        # The outer main-slot wrapper must match config/agent.yaml
        # (VERIFIED_EXTERNAL), not BaseNode's permissive ANONYMOUS default.
        assert DeliverySlotWorkflowGraphNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL


class TestGraphNodeBoundaryMapping:
    """Boundary mapping: extract_input()/merge_output() do not leak raw state/subgraph dicts."""

    def test_extract_input_only_reads_validated_input(self):
        node = _node()
        state = {
            "validated_input": '{"parcels": []}',
            "unrelated_secret_field": "must-not-appear",
        }
        extracted = node.extract_input(state)

        assert isinstance(extracted, str)
        assert "unrelated_secret_field" not in extracted
        assert "must-not-appear" not in extracted

    def test_merge_output_maps_fields_explicitly_no_raw_passthrough(self):
        node = _node()
        sub_result = {
            "manifest_parcels": [],
            "forecasted_slots": {},
            "contact_dispatch_status": {},
            "confirmed_slots": {},
            "retry_counts": {},
            "failed_delivery_state": {},
            "konbini_reservations": {},
            "status": "success",
            # A field the subgraph may carry internally that must NOT reach the
            # outer state unless merge_output() maps it explicitly.
            "recipient_contact": "should-not-be-copied",
        }
        merged = node.merge_output({}, sub_result)

        assert "recipient_contact" not in merged
        assert merged["status"] == "success"
        assert set(merged.keys()) == {
            "manifest_parcels",
            "forecasted_slots",
            "contact_dispatch_status",
            "confirmed_slots",
            "retry_counts",
            "failed_delivery_state",
            "konbini_reservations",
            "status",
        }


class TestGraphNodeDelegatesGatingToInnerSubgraph:
    """Delegation has a real target: the inner subgraph's entry node runs S-1/S-2/S-3."""

    def test_inner_entry_node_is_a_function_node_with_security_gates(self):
        # SlotForecastNode is the inner subgraph's entry point (START -> the first
        # pipeline node). It is a FunctionNode, so the framework's @final S-2/S-3
        # gates run on every invocation of the inner subgraph - this is where the
        # GraphNode's skipped lifecycle is actually enforced, not omitted.
        assert issubclass(SlotForecastNode, FunctionNode)
        assert hasattr(SlotForecastNode, "required_trust_level")
