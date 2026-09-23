"""AgentCore Platform v1.0 — inner step 5 (final): KonbiniPickupNode."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import delivery_service as svc


class KonbiniPickupNode(FunctionNode):
    """After the retry limit is exceeded: offer konbini pickup, reserve it (mock API)."""

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        parcels = state.get("manifest_parcels") or []
        failed_state = state.get("failed_delivery_state") or {}
        if not parcels:
            return {"status": AgentStatus.ERROR.value, "error_log": ["KonbiniPickupNode: no parcels to evaluate"]}

        reservations: dict[str, Any] = {}
        for parcel in parcels:
            pid = parcel["parcel_id"]
            if failed_state.get(pid, {}).get("escalated"):
                reservations[pid] = svc.reserve_konbini(pid, parcel.get("area", "unknown"))

        emit_trace_event(
            "konbini_pickup_evaluated",
            {"correlation_id": state.get("correlation_id"), "reserved_count": len(reservations)},
            state,
        )
        return {"konbini_reservations": reservations, "status": AgentStatus.SUCCESS.value}
