"""AgentCore Platform v1.0 — inner step 2: RecipientContactNode."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import delivery_service as svc


class RecipientContactNode(FunctionNode):
    """Contact the recipient 24h before delivery, presenting the top-3 forecasted slots.

    Dispatch is a deterministic mock (LINE/SMS) — no live network call, no raw
    recipient_contact ever logged.
    """

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        parcels = state.get("manifest_parcels") or []
        forecasted = state.get("forecasted_slots") or {}
        if not parcels:
            return {"status": AgentStatus.ERROR.value, "error_log": ["RecipientContactNode: no parcels to contact"]}

        dispatch_status = {}
        for parcel in parcels:
            pid = parcel["parcel_id"]
            dispatch_status[pid] = svc.dispatch_contact(forecasted.get(pid, []))

        emit_trace_event(
            "recipient_contacted",
            {
                "correlation_id": state.get("correlation_id"),
                "dispatched": sum(1 for v in dispatch_status.values() if v == "sent"),
            },
            state,
        )
        return {"contact_dispatch_status": dispatch_status, "status": AgentStatus.SUCCESS.value}
