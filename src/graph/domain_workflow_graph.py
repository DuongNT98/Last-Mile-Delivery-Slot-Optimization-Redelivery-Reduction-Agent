"""AgentCore Platform v1.0 — LOG-C2-034 inner delivery-slot workflow (Cat 2).

Instantiated by DeliverySlotWorkflowGraphNode.get_subgraph(). Receives only
the JSON string user_input (seeded from the outer validated_input); the
first inner node reconstructs the payload.

Pipeline: slot_forecast -> recipient_contact -> slot_confirm ->
          failed_delivery -> konbini_pickup
"""

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.failed_delivery_node import FailedDeliveryNode
from src.nodes.konbini_pickup_node import KonbiniPickupNode
from src.nodes.recipient_contact_node import RecipientContactNode
from src.nodes.slot_confirm_node import SlotConfirmNode
from src.nodes.slot_forecast_node import SlotForecastNode
from src.schemas.state import State


class DeliverySlotWorkflowGraph(BaseGraph):
    """Inner multi-step last-mile delivery slot optimization workflow."""

    @property
    def name(self) -> str:
        return "log_c2_034_delivery_slot_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        pass

    def register_nodes(self) -> None:
        max_retries = self.config.get("max_reschedule_retries", 3) if hasattr(self, "config") else 3
        self._nodes["slot_forecast"] = SlotForecastNode()
        self._nodes["recipient_contact"] = RecipientContactNode()
        self._nodes["slot_confirm"] = SlotConfirmNode()
        self._nodes["failed_delivery"] = FailedDeliveryNode(max_retries=max_retries)
        self._nodes["konbini_pickup"] = KonbiniPickupNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "slot_forecast")
        self._sg.add_edge("slot_forecast", "recipient_contact")
        self._sg.add_edge("recipient_contact", "slot_confirm")
        self._sg.add_edge("slot_confirm", "failed_delivery")
        self._sg.add_edge("failed_delivery", "konbini_pickup")
        self._sg.add_edge("konbini_pickup", END)

    def route(self, state: AgentState) -> str:
        return END if state.get("status") == AgentStatus.ERROR.value else "konbini_pickup"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "manifest_parcels": state.get("manifest_parcels", []),
            "forecasted_slots": state.get("forecasted_slots", {}),
            "contact_dispatch_status": state.get("contact_dispatch_status", {}),
            "confirmed_slots": state.get("confirmed_slots", {}),
            "retry_counts": state.get("retry_counts", {}),
            "failed_delivery_state": state.get("failed_delivery_state", {}),
            "konbini_reservations": state.get("konbini_reservations", {}),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
