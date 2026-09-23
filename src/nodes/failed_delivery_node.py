"""AgentCore Platform v1.0 — inner step 4: FailedDeliveryNode."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import delivery_service as svc


class FailedDeliveryNode(FunctionNode):
    """On a failed delivery attempt: offer up to 3 reschedule slots; enforce a retry limit.

    Parcels that were confirmed and had no simulated failure pass through
    unchanged (delivered). Parcels flagged as failed increment their retry
    count and get flagged for escalation once the configured retry limit
    (`max_reschedule_retries`, default 3) is exceeded — escalation is picked
    up by KonbiniPickupNode.
    """

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, max_retries: int = 3) -> None:
        self._max_retries = max_retries

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        parcels = state.get("manifest_parcels") or []
        forecasted = state.get("forecasted_slots") or {}
        if not parcels:
            return {"status": AgentStatus.ERROR.value, "error_log": ["FailedDeliveryNode: no parcels to evaluate"]}

        retry_counts = dict(state.get("retry_counts") or {})
        failed_state: dict[str, Any] = {}
        escalated_count = 0
        for parcel in parcels:
            pid = parcel["parcel_id"]
            outcome = svc.evaluate_delivery_attempt(parcel)
            if outcome == "delivered":
                continue
            retry_counts[pid] = retry_counts.get(pid, 0) + 1
            escalate = svc.should_escalate_to_konbini(retry_counts[pid], self._max_retries)
            failed_state[pid] = {
                "reschedule_offers": svc.offer_reschedule(forecasted.get(pid, [])),
                "escalated": escalate,
            }
            if escalate:
                escalated_count += 1

        emit_trace_event(
            "failed_delivery_evaluated",
            {
                "correlation_id": state.get("correlation_id"),
                "failed_count": len(failed_state),
                "escalated_count": escalated_count,
            },
            state,
        )
        return {
            "retry_counts": retry_counts,
            "failed_delivery_state": failed_state,
            "status": AgentStatus.SUCCESS.value,
        }
