# LOG-C2-034 — Integration test: full graph compile + invoke.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


class FakeLLM:
    def complete(self, *a, **k):
        return "aggregate optimization narrative"


def _ctx(session="it-1"):
    return InvocationContext(session_id=session, caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="tester")


def _agent(max_retries: int = 3):
    a = Graph(config={"llm": FakeLLM(), "max_retry": 1, "max_reschedule_retries": max_retries})
    a.compile()
    return a


def test_full_pipeline_success():
    payload = json.dumps(
        {
            "parcels": [
                {"parcel_id": "P1", "recipient_contact": "090-1234-5678", "area": "Shibuya", "time_window": "18:00-20:00"},
                {"parcel_id": "P2", "recipient_contact": "test@example.com", "area": "Ginza", "time_window": "09:00-12:00"},
            ]
        }
    )
    result = _agent().invoke(payload, ctx=_ctx())
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    nh = result.get("node_history") or []
    assert len(nh) >= 5, f"expected >=5 nodes, got {len(nh)}: {nh}"
    report = result.get("output") or {}
    assert isinstance(report, dict)
    areas = {a["area"] for a in report.get("areas", [])}
    assert areas == {"Shibuya", "Ginza"}


def test_empty_input_errors():
    result = _agent().invoke("", ctx=_ctx("it-2"))
    assert result["status"] in (
        AgentStatus.ERROR,
        AgentStatus.ERROR.value,
        AgentStatus.CANCELLED,
        AgentStatus.CANCELLED.value,
    )


def test_failed_delivery_escalates_to_konbini_and_report_stays_aggregate_only():
    payload = json.dumps(
        {
            "parcels": [
                {
                    "parcel_id": "P3",
                    "recipient_contact": "090-9999-0000",
                    "area": "Ikebukuro",
                    "time_window": "20:00-21:00",
                    "simulated_delivery_result": "failed",
                }
            ]
        }
    )
    result = _agent(max_retries=1).invoke(payload, ctx=_ctx("it-3"))
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    report = result.get("output") or {}
    ikebukuro = next(a for a in report.get("areas", []) if a["area"] == "Ikebukuro")
    assert ikebukuro["escalated_to_konbini"] == 1
    assert ikebukuro["konbini_reserved"] == 1
    report_blob = json.dumps(report).lower()
    assert "090-9999-0000" not in report_blob
    assert "p3" not in report_blob
