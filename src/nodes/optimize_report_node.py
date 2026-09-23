"""AgentCore Platform v1.0 — outer post_process: OptimizeReportNode (S-3 aggregate-only gate)."""

import json
import logging
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import delivery_service as svc
from src.services.llm_response import build_llm_messages, extract_llm_text

logger = logging.getLogger(__name__)

# Forbidden per-recipient keys/markers that must NEVER appear in the aggregate report.
_FORBIDDEN_KEYS = ("parcel_id", "recipient_contact")


def resolve_llm(constructor_llm: Any | None, state: dict[str, Any]) -> Any | None:
    """Return the injected test-double llm, or build a fresh AzureOpenAIClient
    from the per-invocation caller's bound secrets.

    Built fresh here (never at __init__/register_nodes(), never cached on
    self) because node instances are constructed once and reused across every
    invocation via the registry's LRU cache — caching a client built from one
    caller's secrets would leave it visible to the next caller.

    Any resolution failure (no secret bound, MissingSecret, a malformed
    AZURE_OPENAI_ENDPOINT, PB-6's bare-state fixture lacking session_id/
    thread_id/trace_id, ...) returns None so the caller keeps the
    deterministic rollup — this function only ever degrades, it never raises.
    Once a client IS resolved, a failure *during the actual LLM call* is a
    separate, deliberately different case (see execute()): it is reported as
    status=error, not silently degraded, so the caller is never handed a
    report that looks complete while the narrative it asked for is missing.
    """
    if constructor_llm is not None:
        return constructor_llm
    try:
        from shared.services.llm.azure_openai_client import AzureOpenAIClient

        ctx = InvocationContext.from_state(state)
        return AzureOpenAIClient(
            {
                "api_key": ctx.secrets.require("AZURE_OPENAI_API_KEY"),
                "azure_endpoint": ctx.secrets.require("AZURE_OPENAI_ENDPOINT"),
                "azure_deployment": ctx.secrets.require("AZURE_OPENAI_DEPLOYMENT"),
            }
        )
    except Exception:  # noqa: BLE001 - any resolution failure degrades to the deterministic rollup
        return None


class OptimizeReportNode(FunctionNode):
    """Generate an area/route-level carrier workload optimization report.

    S-3 named compliance risk (Engineer Review §4): the report MUST be
    aggregate-only — no individual recipient / parcel_id data. The
    deterministic rollup (build_optimization_report) never includes those
    keys; the optional LLM narrative is generated strictly from the
    aggregate dict, never from raw parcels, and the S-3 hook independently
    re-verifies the final report dict contains no forbidden per-recipient
    keys or values before it leaves the agent.

    LLM narrative (generation_mode: "llm"): resolve_llm() builds an
    AzureOpenAIClient per invocation from AZURE_OPENAI_API_KEY/_ENDPOINT/
    _DEPLOYMENT (declared under config/agent.yaml requires.extras, kept out
    of requires.secrets so a missing key degrades instead of 503ing the
    agent at compile time — see that file's comment). No secret configured,
    or any other resolution failure, silently keeps the deterministic
    rollup with no narrative_summary. A resolved client that then fails the
    actual call is a different case: reported as status=error, not
    silently degraded.
    """

    # S-1: outer boundary node — matches agent.yaml default.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            emit_trace_event(
                "optimize_report_skipped_upstream_error", {"correlation_id": state.get("correlation_id")}, state
            )
            return {"status": AgentStatus.ERROR.value}

        parcels = state.get("manifest_parcels") or []
        report = svc.build_optimization_report(
            parcels,
            state.get("confirmed_slots") or {},
            state.get("failed_delivery_state") or {},
            state.get("konbini_reservations") or {},
        )

        # The deterministic rollup above is the report; the LLM only adds a
        # narrative summary. No LLM resolved (no secret configured, or
        # resolution otherwise failed — see resolve_llm()) is a supported
        # production mode: it degrades silently to the rollup with no
        # narrative. But once an LLM IS resolved, a call failure must surface
        # as ERROR — degrading silently would hand the caller a report that
        # looks complete while the narrative it asked for is simply missing.
        llm = resolve_llm(self._llm, state)
        if llm is not None:
            prompt = (
                f"Summarize this last-mile delivery optimization rollup for a carrier ops planner "
                f"(aggregate only, no individual recipient data): {json.dumps(report, ensure_ascii=False)}"
            )
            try:
                narrative = extract_llm_text(llm.complete(build_llm_messages(prompt)))
            except Exception as exc:
                logger.error(
                    "OptimizeReportNode: LLM completion failed (correlation_id=%s): %s",
                    state.get("correlation_id"),
                    exc,
                )
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": [f"OptimizeReportNode: LLM completion failed: {exc}"],
                }
            if not narrative.strip():
                logger.error(
                    "OptimizeReportNode: LLM returned empty content (correlation_id=%s)",
                    state.get("correlation_id"),
                )
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": ["OptimizeReportNode: LLM returned empty narrative summary"],
                }
            report = {**report, "narrative_summary": narrative}

        emit_trace_event(
            "optimization_report_generated",
            {"correlation_id": state.get("correlation_id"), "area_count": len(report.get("areas", []))},
            state,
        )
        return {"optimization_report": report, "formatted_output": report, "status": AgentStatus.SUCCESS.value}

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3 aggregate-only gate (framework-invoked after execute(); never raises)."""
        report = state.get("optimization_report") or {}
        if not report:
            return state
        serialized = json.dumps(report, ensure_ascii=False)
        if any(key in serialized for key in _FORBIDDEN_KEYS):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OptimizeReportNode: report leaks per-recipient data — aggregate-only violation"],
            }
        for parcel in state.get("manifest_parcels") or []:
            pid = parcel.get("parcel_id", "")
            if pid and pid in serialized:
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": ["OptimizeReportNode: report references a parcel_id — aggregate-only violation"],
                }
        return state
