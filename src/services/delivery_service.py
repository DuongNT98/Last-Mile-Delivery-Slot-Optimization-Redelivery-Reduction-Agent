"""AgentCore Platform v1.0 — LOG-C2-034 delivery domain service.

Pure, deterministic domain logic for the last-mile delivery slot workflow.
No I/O, no agenticstar imports, no credentials. All "external" calls
(carrier manifest fetch, LINE/SMS dispatch, carrier slot write-back, konbini
reservation) are deterministic mocks — this template has no live network
dependency; nodes call these functions directly.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# S-2 deterministic sensitive-content patterns (credential-shaped, non-LLM).
# Every quantifier is bounded (no unbounded +/*/{N,}) to avoid ReDoS on
# attacker-controlled input; each segment is capped generously above any
# realistic real-world value.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{1,1024}\.[A-Za-z0-9_\-]{1,4096}\.[A-Za-z0-9_\-]{1,1024}")
_BEARER_RE = re.compile(r"\bBearer\s{1,8}[A-Za-z0-9._\-]{1,4096}", re.IGNORECASE)

# Loose contact shape check: phone-like or email-like. Deliberately permissive —
# this is a shape check, not a full validator.
_PHONE_RE = re.compile(r"^\+?[\d][\d\-() ]{6,19}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{1,24}$")

# The framework's S-2 input gate (BaseNode.__call__, before execute()) detects
# phone/email-shaped PII in the raw invoke payload and replaces the value with
# this literal sentinel before any node sees it (verified against the real
# agenticstar-agentcore==1.0.0 wheel on CI; the local dev stub does not
# reproduce this). A masked contact is a legitimate, already-safe value —
# the recipient identity is tracked by parcel_id downstream, not by the
# contact string — so it must be accepted, not rejected as malformed.
MASKED_CONTACT_SENTINEL = "[MASKED]"

_CANDIDATE_SLOTS = ["09:00-12:00", "13:00-15:00", "18:00-20:00", "20:00-21:00"]


def is_credential_shaped(text: str) -> bool:
    """S-2: reject payloads carrying JWT/Bearer-shaped tokens."""
    return bool(_JWT_RE.search(text) or _BEARER_RE.search(text))


def is_valid_contact(contact: str) -> bool:
    if contact == MASKED_CONTACT_SENTINEL:
        return True
    return bool(_PHONE_RE.match(contact) or _EMAIL_RE.match(contact))


def normalize_parcel(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Validate + normalize one manifest record. Returns None when invalid."""
    if not isinstance(raw, dict):
        return None
    parcel_id = str(raw.get("parcel_id", "") or "").strip()
    contact = str(raw.get("recipient_contact", "") or "").strip()
    area = str(raw.get("area", "") or "").strip()
    time_window = str(raw.get("time_window", "") or "").strip()
    if not parcel_id or not contact or not area or not time_window:
        return None
    if is_credential_shaped(contact) or not is_valid_contact(contact):
        return None
    normalized = {"parcel_id": parcel_id, "recipient_contact": contact, "area": area, "time_window": time_window}
    # Carry through optional simulation hooks (deterministic mock scenarios for tests).
    for key in ("simulated_response", "simulated_delivery_result"):
        if key in raw:
            normalized[key] = raw[key]
    return normalized


def forecast_slots(parcel: dict[str, Any], top_n: int = 3) -> list[dict[str, Any]]:
    """Deterministic delivery-success-probability forecast for candidate slots.

    Score is derived from a stable hash of (area, time_window, slot) — no
    randomness, so results are reproducible across invocations/tests.
    """
    seed = f"{parcel.get('area', '')}|{parcel.get('time_window', '')}"
    scored: list[dict[str, Any]] = []
    for slot in _CANDIDATE_SLOTS:
        digest = hashlib.sha256(f"{seed}|{slot}".encode("utf-8")).hexdigest()
        score = round((int(digest[:8], 16) % 1000) / 1000.0, 3)
        scored.append({"slot": slot, "score": score})
    scored.sort(key=lambda s: float(s["score"]), reverse=True)
    return scored[:top_n]


def dispatch_contact(slots: list[dict[str, Any]]) -> str:
    """Mock LINE/SMS dispatch presenting the top forecasted slots. Deterministic — no network I/O."""
    return "sent" if slots else "skipped"


def confirm_slot(parcel: dict[str, Any], slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Mock recipient confirmation + carrier slot write-back.

    simulated_response == "no_response" -> not confirmed (awaiting).
    simulated_response matching a forecasted slot -> confirms that slot.
    otherwise -> defaults to the top forecasted slot (best-effort auto-confirm).
    """
    if not slots:
        return {"slot": None, "confirmed": False, "written_back": False}
    response = parcel.get("simulated_response")
    if response == "no_response":
        return {"slot": None, "confirmed": False, "written_back": False}
    slot_names = [s["slot"] for s in slots]
    chosen = response if response in slot_names else slots[0]["slot"]
    return {"slot": chosen, "confirmed": True, "written_back": True}


def evaluate_delivery_attempt(parcel: dict[str, Any]) -> str:
    """Deterministic delivery outcome — driven by an optional simulation hook."""
    return str(parcel.get("simulated_delivery_result", "delivered"))


def offer_reschedule(slots: list[dict[str, Any]]) -> list[str]:
    """Offer up to 3 reschedule slot options from the forecasted candidates."""
    return [s["slot"] for s in slots[:3]]


def should_escalate_to_konbini(retry_count: int, max_retries: int) -> bool:
    return retry_count >= max_retries


def reserve_konbini(parcel_id: str, area: str) -> dict[str, Any]:
    """Mock konbini pickup reservation — deterministic store_id from area."""
    digest = hashlib.sha256(f"konbini|{area}".encode("utf-8")).hexdigest()
    store_id = f"KONBINI-{digest[:6].upper()}"
    return {"store_id": store_id, "reserved": True}


def build_optimization_report(
    parcels: list[dict[str, Any]],
    confirmed_slots: dict[str, Any],
    failed_delivery_state: dict[str, Any],
    konbini_reservations: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate area/route-level rollup — NEVER includes parcel_id or recipient_contact.

    Only area-keyed counts + rates are returned; this is the S-3 aggregate-only
    compliance boundary named in the proposal.
    """
    by_area: dict[str, dict[str, Any]] = {}
    for parcel in parcels:
        area = parcel.get("area", "unknown")
        bucket = by_area.setdefault(
            area, {"total_parcels": 0, "confirmed": 0, "escalated_to_konbini": 0, "konbini_reserved": 0}
        )
        bucket["total_parcels"] += 1
        pid = parcel.get("parcel_id", "")
        if confirmed_slots.get(pid, {}).get("confirmed"):
            bucket["confirmed"] += 1
        if failed_delivery_state.get(pid, {}).get("escalated"):
            bucket["escalated_to_konbini"] += 1
        if konbini_reservations.get(pid, {}).get("reserved"):
            bucket["konbini_reserved"] += 1

    areas_summary = []
    for area, bucket in by_area.items():
        total = bucket["total_parcels"]
        confirmation_rate = round(bucket["confirmed"] / total, 3) if total else 0.0
        escalation_rate = round(bucket["escalated_to_konbini"] / total, 3) if total else 0.0
        areas_summary.append(
            {
                "area": area,
                "total_parcels": total,
                "confirmed": bucket["confirmed"],
                "confirmation_rate": confirmation_rate,
                "escalated_to_konbini": bucket["escalated_to_konbini"],
                "escalation_rate": escalation_rate,
                "konbini_reserved": bucket["konbini_reserved"],
            }
        )

    return {
        "areas": sorted(areas_summary, key=lambda a: a["area"]),
        "total_parcels": len(parcels),
    }
