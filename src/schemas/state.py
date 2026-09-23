"""AgentCore Platform v1.0 — LOG-C2-034 state schema.

Last-Mile Delivery Slot Optimization & Redelivery Reduction Agent. Flat
TypedDict extension of AgentState (ADR-005). All agent-specific fields are
NotRequired[...] (CoE C8) and read via state.get(...).
"""

# mypy: disable-error-code="valid-type"
# AgentState IS a real TypedDict at runtime (confirmed via typing.is_typeddict) but
# agenticstar-agentcore ships no py.typed marker, so mypy sees this import as Any and
# cannot verify State's TypedDict-ness statically — hence NotRequired[] below would
# otherwise be flagged as "only usable in a TypedDict definition". Framework-stub gap,
# not a real type issue; scoped to this file only.
from typing import NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Agent state for LOG-C2-034.

    manifest_parcels: normalized carrier manifest — list[{"parcel_id",
      "recipient_contact", "area", "time_window"}].
    forecasted_slots: parcel_id -> list[{"slot": str, "score": float}]
      (top-3 forecasted delivery-success slots, ranked descending).
    contact_dispatch_status: parcel_id -> "sent" | "skipped".
    confirmed_slots: parcel_id -> {"slot": str, "confirmed": bool,
      "written_back": bool}.
    retry_counts: parcel_id -> int (reschedule attempts after a failed
      delivery attempt).
    failed_delivery_state: parcel_id -> {"reschedule_offers": list[str],
      "escalated": bool}.
    konbini_reservations: parcel_id -> {"store_id": str, "reserved": bool}.
    optimization_report: aggregate-only area/route-level report (NEVER
      contains parcel_id / recipient_contact — S-3 gated in post_process).
    """

    manifest_parcels: NotRequired[list[dict]]
    forecasted_slots: NotRequired[dict]
    contact_dispatch_status: NotRequired[dict]
    confirmed_slots: NotRequired[dict]
    retry_counts: NotRequired[dict]
    failed_delivery_state: NotRequired[dict]
    konbini_reservations: NotRequired[dict]
    optimization_report: NotRequired[dict]
