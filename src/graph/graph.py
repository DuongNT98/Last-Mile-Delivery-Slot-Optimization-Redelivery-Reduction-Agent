"""AgentCore Platform v1.0 — LOG-C2-034 outer graph (Cat 2).

Outer (AgentBaseGraph): initialize -> pre_process(ManifestIngestNode) ->
main(DeliverySlotWorkflowGraphNode) -> post_process(OptimizeReportNode) -> finalize.
Inner (BaseGraph): slot_forecast -> recipient_contact -> slot_confirm ->
failed_delivery -> konbini_pickup.

The GraphNode wrapper lives in THIS file (not src/nodes/) so the PB-6
invoke-order probe does not mis-assert its deliberately-delegated lifecycle
(see the Cat 2 reference pattern documentation).
"""

from typing import TYPE_CHECKING, Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.manifest_ingest_node import ManifestIngestNode
from src.nodes.optimize_report_node import OptimizeReportNode
from src.schemas.state import State

if TYPE_CHECKING:
    from src.graph.domain_workflow_graph import DeliverySlotWorkflowGraph


class DeliverySlotWorkflowGraphNode(GraphNode):
    """Wraps the inner slot-forecast/contact/confirm/failed-delivery/konbini workflow (main slot)."""

    # S-1: the outer main-slot wrapper is the first node to receive caller input,
    # so it must enforce the agent-level trust floor from config/agent.yaml
    # (VERIFIED_EXTERNAL) rather than inheriting BaseNode's permissive ANONYMOUS.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def __init__(self, max_reschedule_retries: int = 3) -> None:
        super().__init__()
        self._max_reschedule_retries = max_reschedule_retries

    def get_subgraph(self) -> "DeliverySlotWorkflowGraph":
        from src.graph.domain_workflow_graph import DeliverySlotWorkflowGraph

        sg = DeliverySlotWorkflowGraph(config=self._parent_config())
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        emit_trace_event("delivery_slot_workflow_dispatched", {"correlation_id": state.get("correlation_id")}, state)
        return str(state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "delivery_slot_workflow_completed",
            {"correlation_id": state.get("correlation_id"), "status": str(sub_result.get("status"))},
            state,
        )
        return {
            "manifest_parcels": sub_result.get("manifest_parcels", []),
            "forecasted_slots": sub_result.get("forecasted_slots", {}),
            "contact_dispatch_status": sub_result.get("contact_dispatch_status", {}),
            "confirmed_slots": sub_result.get("confirmed_slots", {}),
            "retry_counts": sub_result.get("retry_counts", {}),
            "failed_delivery_state": sub_result.get("failed_delivery_state", {}),
            "konbini_reservations": sub_result.get("konbini_reservations", {}),
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {"max_reschedule_retries": self._max_reschedule_retries}


class Graph(AgentBaseGraph):
    """LOG-C2-034 — Last-Mile Delivery Slot Optimization & Redelivery Reduction Agent."""

    @property
    def name(self) -> str:
        return "log-c2-034"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize

        max_retries = self.config.get("max_reschedule_retries", 3) if hasattr(self, "config") else 3

        self._nodes["pre_process"] = ManifestIngestNode()
        self._nodes["main"] = DeliverySlotWorkflowGraphNode(max_reschedule_retries=max_retries)
        # No llm= passed here: OptimizeReportNode resolves its own Azure OpenAI
        # client per invocation from the caller's bound secrets (resolve_llm()
        # in src/nodes/optimize_report_node.py) rather than a static config-time
        # value, since a node instance is constructed once and reused across
        # every invocation via the registry's LRU cache.
        self._nodes["post_process"] = OptimizeReportNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
