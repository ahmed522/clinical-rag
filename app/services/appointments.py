"""
Handles appointment-related queries by reading from the Supabase
appointments table. RLS scopes results to the patient's own rows.
"""

import re
from datetime import datetime, timezone

from app.deps import CurrentUser
from app.services.generation import GroundedAnswer

_ACTION_KEYWORDS = re.compile(
    r"\b(book|schedule|cancel|reschedule|rebook|change|move)\b", re.IGNORECASE
)


def handle_appointment_query(user: CurrentUser, query: str) -> GroundedAnswer:
    if _ACTION_KEYWORDS.search(query):
        return GroundedAnswer(
            "I can show you your existing appointments, but I'm not able to "
            "book, cancel, or reschedule appointments yet. Please contact "
            "the clinic directly to manage your schedule.",
            grounded=True,
        )

    rows = (
        user.db.table("appointments")
        .select("slot, status, doctor_id, doctors(name)")
        .eq("status", "booked")
        .gte("slot", datetime.now(timezone.utc).isoformat())
        .order("slot", desc=False)
        .limit(10)
        .execute()
        .data
    )

    if not rows:
        return GroundedAnswer(
            "You don't have any upcoming appointments scheduled. "
            "If you'd like to book one, please contact the clinic.",
            grounded=True,
        )

    lines = []
    for row in rows:
        doctor_name = "your doctor"
        if isinstance(row.get("doctors"), dict) and row["doctors"].get("name"):
            doctor_name = f"Dr. {row['doctors']['name']}"

        slot = datetime.fromisoformat(row["slot"])
        lines.append(f"- {doctor_name} on {slot.strftime('%A, %B %d, %Y at %I:%M %p')}")

    header = "Here are your upcoming appointments:\n" if len(lines) > 1 else "You have an upcoming appointment:\n"
    return GroundedAnswer(header + "\n".join(lines), grounded=True)
