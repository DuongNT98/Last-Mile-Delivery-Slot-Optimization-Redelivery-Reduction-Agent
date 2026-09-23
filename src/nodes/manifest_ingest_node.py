"""AgentCore Platform v1.0 — outer pre_process: ManifestIngestNode (S-1 + S-2)."""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import delivery_service as svc

MAX_INPUT_CHARS = 200_000


class ManifestIngestNode(FunctionNode):
    """Ingest + validate the carrier delivery manifest, serialize inner input.

    Accepts a JSON payload:
        {"parcels": [{"parcel_id": "...", "recipient_contact": "...",
                       "area": "...", "time_window": "..."}, ...]}
    Rejects empty input, oversized input, malformed payloads, and any
    recipient_contact that is credential-shaped (S-2 deterministic scan).
    Serializes the normalized parcel list to validated_input (JSON string)
    for the inner subgraph.
    """

    # S-1: outer boundary node — matches agent.yaml default (recipient PII intake).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        emit_trace_event("manifest_ingest_started", {"correlation_id": state.get("correlation_id")}, state)

        if not isinstance(raw, str) or not raw.strip():
            return {"status": AgentStatus.ERROR.value, "error_log": ["ManifestIngestNode: empty input"]}
        if len(raw) > MAX_INPUT_CHARS:
            return {"status": AgentStatus.ERROR.value, "error_log": ["ManifestIngestNode: input too large"]}

        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return {"status": AgentStatus.ERROR.value, "error_log": ["ManifestIngestNode: payload is not valid JSON"]}
        if not isinstance(payload, dict):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ManifestIngestNode: payload must be a JSON object"],
            }

        raw_parcels = payload.get("parcels")
        if not isinstance(raw_parcels, list) or not raw_parcels:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ManifestIngestNode: 'parcels' must be a non-empty list"],
            }

        normalized: list[dict[str, Any]] = []
        for raw_parcel in raw_parcels:
            parcel = svc.normalize_parcel(raw_parcel)
            if parcel is not None:
                normalized.append(parcel)

        if not normalized:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ManifestIngestNode: no valid parcel records after validation"],
            }

        # S-4: counts only — never log raw recipient_contact.
        emit_trace_event(
            "manifest_ingested",
            {"correlation_id": state.get("correlation_id"), "parcel_count": len(normalized)},
            state,
        )
        return {
            "manifest_parcels": normalized,
            "validated_input": json.dumps({"parcels": normalized}, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }
