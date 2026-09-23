"""AgentCore Platform v1.0 — inner step 1: SlotForecastNode.

The inner subgraph receives only the JSON string user_input (seeded from the
outer validated_input), so this first inner node reconstructs the payload.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import delivery_service as svc


class SlotForecastNode(FunctionNode):
    """Forecast delivery-success probability per candidate slot; rank top-3."""

    # S-1: inner subgraph node — trust authenticated once at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            payload = None
        parcels = payload.get("parcels") if isinstance(payload, dict) else None
        if not isinstance(parcels, list) or not parcels:
            return {"status": AgentStatus.ERROR.value, "error_log": ["SlotForecastNode: no parcels in inner input"]}

        forecasted = {parcel["parcel_id"]: svc.forecast_slots(parcel) for parcel in parcels}
        emit_trace_event(
            "slots_forecasted",
            {"correlation_id": state.get("correlation_id"), "parcel_count": len(parcels)},
            state,
        )
        return {"manifest_parcels": parcels, "forecasted_slots": forecasted, "status": AgentStatus.SUCCESS.value}
