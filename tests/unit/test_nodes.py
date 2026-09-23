# LOG-C2-034 — Unit tests (per node: success + error/edge).

import json

from framework.schemas.agent_status import AgentStatus
from framework.secrets.base import SecretProvider
from framework.secrets.context import bound_secrets

from src.nodes.failed_delivery_node import FailedDeliveryNode
from src.nodes.konbini_pickup_node import KonbiniPickupNode
from src.nodes.manifest_ingest_node import ManifestIngestNode
from src.nodes.optimize_report_node import OptimizeReportNode
from src.nodes.recipient_contact_node import RecipientContactNode
from src.nodes.slot_confirm_node import SlotConfirmNode
from src.nodes.slot_forecast_node import SlotForecastNode


def _s(**kw):
    st = {"node_history": [], "error_log": [], "execution_time": {}, "correlation_id": "c"}
    st.update(kw)
    return st


_PARCEL = {
    "parcel_id": "P1",
    "recipient_contact": "090-1234-5678",
    "area": "Shibuya",
    "time_window": "18:00-20:00",
}


class TestManifestIngestNode:
    def setup_method(self):
        self.node = ManifestIngestNode()

    def test_success(self):
        payload = json.dumps({"parcels": [_PARCEL]})
        r = self.node.execute(_s(user_input=payload))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["manifest_parcels"][0]["parcel_id"] == "P1"
        assert json.loads(r["validated_input"])["parcels"][0]["parcel_id"] == "P1"

    def test_empty_input(self):
        assert self.node.execute(_s(user_input=""))["status"] == AgentStatus.ERROR

    def test_not_json(self):
        assert self.node.execute(_s(user_input="not json"))["status"] == AgentStatus.ERROR

    def test_missing_parcels_key(self):
        assert self.node.execute(_s(user_input=json.dumps({})))["status"] == AgentStatus.ERROR

    def test_rejects_credential_shaped_contact(self):
        bad = {**_PARCEL, "recipient_contact": "eyJabc.def.ghi"}
        payload = json.dumps({"parcels": [bad]})
        assert self.node.execute(_s(user_input=payload))["status"] == AgentStatus.ERROR

    def test_rejects_malformed_contact_shape(self):
        bad = {**_PARCEL, "recipient_contact": "not-a-contact"}
        payload = json.dumps({"parcels": [bad]})
        assert self.node.execute(_s(user_input=payload))["status"] == AgentStatus.ERROR

    def test_accepts_masked_contact(self):
        # The framework's real S-2 input gate (BaseNode.__call__, before execute())
        # replaces phone/email-shaped PII in the invoke payload with "[MASKED]"
        # before this node ever sees it. execute() must treat that sentinel as a
        # legitimate already-safe value, not reject it as malformed.
        masked = {**_PARCEL, "recipient_contact": "[MASKED]"}
        payload = json.dumps({"parcels": [masked]})
        r = self.node.execute(_s(user_input=payload))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["manifest_parcels"][0]["recipient_contact"] == "[MASKED]"

    def test_drops_invalid_keeps_valid(self):
        bad = {**_PARCEL, "parcel_id": ""}
        payload = json.dumps({"parcels": [bad, _PARCEL]})
        r = self.node.execute(_s(user_input=payload))
        assert r["status"] == AgentStatus.SUCCESS
        assert len(r["manifest_parcels"]) == 1


class TestSlotForecastNode:
    def setup_method(self):
        self.node = SlotForecastNode()

    def test_success(self):
        inner = json.dumps({"parcels": [_PARCEL]})
        r = self.node.execute(_s(user_input=inner))
        assert r["status"] == AgentStatus.SUCCESS
        slots = r["forecasted_slots"]["P1"]
        assert len(slots) == 3
        assert slots[0]["score"] >= slots[1]["score"] >= slots[2]["score"]

    def test_deterministic(self):
        inner = json.dumps({"parcels": [_PARCEL]})
        r1 = self.node.execute(_s(user_input=inner))
        r2 = self.node.execute(_s(user_input=inner))
        assert r1["forecasted_slots"] == r2["forecasted_slots"]

    def test_no_parcels(self):
        assert self.node.execute(_s(user_input=json.dumps({"parcels": []})))["status"] == AgentStatus.ERROR

    def test_bad_json(self):
        assert self.node.execute(_s(user_input="{bad"))["status"] == AgentStatus.ERROR


class TestRecipientContactNode:
    def setup_method(self):
        self.node = RecipientContactNode()

    def test_success(self):
        r = self.node.execute(_s(manifest_parcels=[_PARCEL], forecasted_slots={"P1": [{"slot": "18:00-20:00", "score": 0.9}]}))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["contact_dispatch_status"]["P1"] == "sent"

    def test_no_parcels(self):
        assert self.node.execute(_s(manifest_parcels=[]))["status"] == AgentStatus.ERROR


class TestSlotConfirmNode:
    def setup_method(self):
        self.node = SlotConfirmNode()

    def test_confirms_default_top_slot(self):
        forecast = {"P1": [{"slot": "18:00-20:00", "score": 0.9}]}
        r = self.node.execute(_s(manifest_parcels=[_PARCEL], forecasted_slots=forecast))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["confirmed_slots"]["P1"]["confirmed"] is True
        assert r["confirmed_slots"]["P1"]["slot"] == "18:00-20:00"

    def test_no_response_not_confirmed(self):
        parcel = {**_PARCEL, "simulated_response": "no_response"}
        forecast = {"P1": [{"slot": "18:00-20:00", "score": 0.9}]}
        r = self.node.execute(_s(manifest_parcels=[parcel], forecasted_slots=forecast))
        assert r["confirmed_slots"]["P1"]["confirmed"] is False
        assert r["status"] == AgentStatus.SUCCESS

    def test_no_parcels(self):
        assert self.node.execute(_s(manifest_parcels=[]))["status"] == AgentStatus.ERROR


class TestFailedDeliveryNode:
    def setup_method(self):
        self.node = FailedDeliveryNode(max_retries=2)

    def test_delivered_parcel_passes_through(self):
        forecast = {"P1": [{"slot": "18:00-20:00", "score": 0.9}]}
        r = self.node.execute(_s(manifest_parcels=[_PARCEL], forecasted_slots=forecast))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["failed_delivery_state"] == {}

    def test_failed_parcel_increments_retry(self):
        parcel = {**_PARCEL, "simulated_delivery_result": "failed"}
        forecast = {"P1": [{"slot": "18:00-20:00", "score": 0.9}]}
        r = self.node.execute(_s(manifest_parcels=[parcel], forecasted_slots=forecast))
        assert r["retry_counts"]["P1"] == 1
        assert r["failed_delivery_state"]["P1"]["escalated"] is False

    def test_escalates_past_retry_limit(self):
        parcel = {**_PARCEL, "simulated_delivery_result": "failed"}
        forecast = {"P1": [{"slot": "18:00-20:00", "score": 0.9}]}
        r = self.node.execute(_s(manifest_parcels=[parcel], forecasted_slots=forecast, retry_counts={"P1": 1}))
        assert r["retry_counts"]["P1"] == 2
        assert r["failed_delivery_state"]["P1"]["escalated"] is True

    def test_no_parcels(self):
        assert self.node.execute(_s(manifest_parcels=[]))["status"] == AgentStatus.ERROR


class TestKonbiniPickupNode:
    def setup_method(self):
        self.node = KonbiniPickupNode()

    def test_reserves_for_escalated(self):
        failed_state = {"P1": {"reschedule_offers": [], "escalated": True}}
        r = self.node.execute(_s(manifest_parcels=[_PARCEL], failed_delivery_state=failed_state))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["konbini_reservations"]["P1"]["reserved"] is True

    def test_no_reservation_when_not_escalated(self):
        r = self.node.execute(_s(manifest_parcels=[_PARCEL], failed_delivery_state={}))
        assert r["konbini_reservations"] == {}

    def test_no_parcels(self):
        assert self.node.execute(_s(manifest_parcels=[]))["status"] == AgentStatus.ERROR


class _DictLLM:
    """Canonical fake: complete(messages: list) -> {"content": str, ...}."""

    def __init__(self, content: str):
        self._content = content
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return {"content": self._content, "tool_calls": [], "model": "fake", "usage": {}}


class _RaisingLLM:
    def complete(self, messages):
        raise RuntimeError("provider timeout")


class _EmptyLLM:
    def complete(self, messages):
        return {"content": "", "tool_calls": [], "model": "fake", "usage": {}}


class _FakeSecretProvider(SecretProvider):
    """In-memory SecretProvider test double — no real secret backend involved."""

    def __init__(self, values: dict):
        self._values = values

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._values.get(key, default)


class TestOptimizeReportNode:
    def setup_method(self):
        self.node = OptimizeReportNode()

    def test_success(self):
        r = self.node.execute(
            _s(
                manifest_parcels=[_PARCEL],
                confirmed_slots={"P1": {"slot": "18:00-20:00", "confirmed": True, "written_back": True}},
                failed_delivery_state={},
                konbini_reservations={},
            )
        )
        assert r["status"] == AgentStatus.SUCCESS
        assert r["optimization_report"]["areas"][0]["area"] == "Shibuya"
        assert r["optimization_report"]["areas"][0]["confirmed"] == 1

    def test_upstream_error(self):
        assert self.node.execute(_s(status=AgentStatus.ERROR.value))["status"] == AgentStatus.ERROR

    def test_s3_gate_passes_clean_report(self):
        good = _s(optimization_report={"areas": [{"area": "Shibuya", "total_parcels": 1}], "total_parcels": 1})
        assert self.node._extra_security_gate_output(good) is good

    def test_s3_gate_blocks_parcel_id_leak(self):
        bad = _s(optimization_report={"areas": [], "leaked_note": "parcel_id P1 was late"})
        assert self.node._extra_security_gate_output(bad)["status"] == AgentStatus.ERROR

    def test_s3_gate_blocks_recipient_contact_leak(self):
        bad = _s(optimization_report={"recipient_contact": "090-1234-5678"})
        assert self.node._extra_security_gate_output(bad)["status"] == AgentStatus.ERROR

    def _rollup_state(self):
        return _s(
            manifest_parcels=[_PARCEL],
            confirmed_slots={"P1": {"slot": "18:00-20:00", "confirmed": True, "written_back": True}},
            failed_delivery_state={},
            konbini_reservations={},
        )

    def test_llm_narrative_from_canonical_dict(self):
        r = OptimizeReportNode(llm=_DictLLM("Rollup looks healthy.")).execute(self._rollup_state())
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["optimization_report"]["narrative_summary"] == "Rollup looks healthy."

    def test_llm_receives_canonical_message_list(self):
        llm = _DictLLM("ok")
        OptimizeReportNode(llm=llm).execute(self._rollup_state())
        assert isinstance(llm.last_messages, list)
        assert llm.last_messages[0]["role"] == "user"

    def test_configured_llm_raising_is_error_not_silent_degrade(self):
        r = OptimizeReportNode(llm=_RaisingLLM()).execute(self._rollup_state())
        assert r["status"] == AgentStatus.ERROR.value
        assert "optimization_report" not in r

    def test_configured_llm_empty_content_is_error(self):
        r = OptimizeReportNode(llm=_EmptyLLM()).execute(self._rollup_state())
        assert r["status"] == AgentStatus.ERROR.value

    def test_no_llm_configured_returns_deterministic_rollup(self):
        r = OptimizeReportNode(llm=None).execute(self._rollup_state())
        assert r["status"] == AgentStatus.SUCCESS.value
        assert "narrative_summary" not in r["optimization_report"]

    def _full_state(self, **overrides):
        state = self._rollup_state()
        state.update(session_id="s1", thread_id="t1", trace_id="tr1")
        state.update(overrides)
        return state

    def test_no_secret_bound_falls_back_to_deterministic_rollup(self):
        """resolve_llm() with an empty SecretProvider degrades silently — the real
        production shape in any environment without an Azure key configured."""
        with bound_secrets(_FakeSecretProvider({})):
            r = OptimizeReportNode().execute(self._full_state())
        assert r["status"] == AgentStatus.SUCCESS.value
        assert "narrative_summary" not in r["optimization_report"]

    def test_partial_secrets_falls_back_to_deterministic_rollup(self):
        """A missing key mid-triple (MissingSecret) is caught the same as none at all."""
        provider = _FakeSecretProvider({"AZURE_OPENAI_API_KEY": "k", "AZURE_OPENAI_ENDPOINT": "https://x.services.ai.azure.com"})
        with bound_secrets(provider):
            r = OptimizeReportNode().execute(self._full_state())
        assert r["status"] == AgentStatus.SUCCESS.value
        assert "narrative_summary" not in r["optimization_report"]

    def test_resolves_llm_from_bound_secrets_when_not_constructor_injected(self, monkeypatch):
        """No llm= passed (the real production wiring) — resolve_llm() builds one from
        bound secrets. AzureOpenAIClient itself is monkeypatched so no real network call
        is ever made; only the resolution + wiring is under test."""
        import src.nodes.optimize_report_node as mod

        fake_llm = _DictLLM("From resolved client.")
        monkeypatch.setattr(
            "shared.services.llm.azure_openai_client.AzureOpenAIClient",
            lambda config: fake_llm,
        )
        provider = _FakeSecretProvider(
            {
                "AZURE_OPENAI_API_KEY": "k",
                "AZURE_OPENAI_ENDPOINT": "https://x.services.ai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "d",
            }
        )
        with bound_secrets(provider):
            r = mod.OptimizeReportNode().execute(self._full_state())
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["optimization_report"]["narrative_summary"] == "From resolved client."

    def test_resolved_llm_call_failure_is_error_not_silent_degrade(self, monkeypatch):
        """Once resolve_llm() DOES return a client, a call failure is still status=error
        (unchanged from test_configured_llm_raising_is_error_not_silent_degrade) — the
        new resolve_llm() seam only changes how the client is obtained, never the
        already-established behaviour once one is in hand."""
        import src.nodes.optimize_report_node as mod

        monkeypatch.setattr(
            "shared.services.llm.azure_openai_client.AzureOpenAIClient",
            lambda config: _RaisingLLM(),
        )
        provider = _FakeSecretProvider(
            {
                "AZURE_OPENAI_API_KEY": "k",
                "AZURE_OPENAI_ENDPOINT": "https://x.services.ai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "d",
            }
        )
        with bound_secrets(provider):
            r = mod.OptimizeReportNode().execute(self._full_state())
        assert r["status"] == AgentStatus.ERROR.value
