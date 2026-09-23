"""AgentCore Platform v1.0 — inner step 3: SlotConfirmNode."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import delivery_service as svc


class SlotConfirmNode(FunctionNode):
    """Track recipient confirmation of a forecasted slot; write confirmed slot back to the carrier.

    Handles no-response as a distinct (non-error) outcome — the parcel simply
    proceeds without a confirmed slot and is picked up at the failed-delivery
    stage on the next attempt.
    """

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        parcels = state.get("manifest_parcels") or []
        forecasted = state.get("forecasted_slots") or {}
        if not parcels:
            return {"status": AgentStatus.ERROR.value, "error_log": ["SlotConfirmNode: no parcels to confirm"]}

        confirmed = {}
        for parcel in parcels:
            pid = parcel["parcel_id"]
            confirmed[pid] = svc.confirm_slot(parcel, forecasted.get(pid, []))

        emit_trace_event(
            "slot_confirmation_tracked",
            {
                "correlation_id": state.get("correlation_id"),
                "confirmed": sum(1 for v in confirmed.values() if v["confirmed"]),
            },
            state,
        )
        return {"confirmed_slots": confirmed, "status": AgentStatus.SUCCESS.value}
