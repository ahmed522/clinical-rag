"""
Handles appointment-related queries by reading from the Supabase
appointments table. RLS scopes results to the patient's own rows.
"""

import re
from datetime import datetime, timedelta, timezone

from app.deps import CurrentUser
from app.services.generation import GroundedAnswer

_ACTION_KEYWORDS = re.compile(
    r"\b(book|schedule|cancel|reschedule|rebook|change|move)\b", re.IGNORECASE
)

_AVAILABILITY_KEYWORDS = re.compile(
    r"\b(available\s+doctors?|doctor\s+availability|which\s+doctors?|"
    r"who\s+(?:is|are)\s+available|who\s+can\s+i\s+see|available\s+now)\b",
    re.IGNORECASE,
)

SLOT_MINUTES = 30
DAYS_AHEAD = 14


def appointment_options(user: CurrentUser) -> dict:
    """Return only clinic-safe booking choices for the current patient."""
    doctors = (
        user.db.table("doctors").select("id, name, specialty").eq("status", "available")
        .order("name").execute().data
    )
    windows = user.db.table("doctor_availability").select(
        "doctor_id, day_of_week, start_time, end_time"
    ).execute().data
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    slots = []
    for doctor in doctors:
        for offset in range(DAYS_AHEAD):
            day = (now + timedelta(days=offset)).date()
            weekday_windows = [row for row in windows if row.get("doctor_id") == doctor["id"] and row.get("day_of_week") == day.weekday()]
            for window in weekday_windows:
                start = datetime.fromisoformat(f"{day.isoformat()}T{window['start_time']}").replace(tzinfo=timezone.utc)
                end = datetime.fromisoformat(f"{day.isoformat()}T{window['end_time']}").replace(tzinfo=timezone.utc)
                cursor = start
                while cursor < end:
                    if cursor > now:
                        slots.append({"doctor_id": doctor["id"], "slot": cursor.isoformat()})
                    cursor += timedelta(minutes=SLOT_MINUTES)
    appointments = (
        user.db.table("appointments").select("id, doctor_id, slot, status, doctors(name)")
        .eq("status", "booked").gte("slot", now.isoformat()).order("slot").execute().data
    )
    return {
        "doctors": doctors,
        "slots": sorted(slots, key=lambda row: row["slot"]),
        "appointments": [
            {**row, "doctor_name": row.get("doctors", {}).get("name") if isinstance(row.get("doctors"), dict) else None}
            for row in appointments
        ],
    }


def apply_appointment_action(user: CurrentUser, payload) -> GroundedAnswer:
    """Create, cancel, or move one appointment after UI confirmation.

    All writes use the patient JWT client. RLS enforces patient ownership and
    the database unique index handles simultaneous slot selection safely.
    """
    if not payload.confirmed:
        raise ValueError("Please review and confirm the appointment change.")
    if payload.action == "cancel":
        if not payload.appointment_id:
            raise ValueError("Choose an appointment to cancel.")
        result = user.db.table("appointments").update({"status": "cancelled"}).eq(
            "id", payload.appointment_id
        ).eq("status", "booked").execute().data
        if not result:
            raise ValueError("That appointment is no longer available to cancel.")
        return GroundedAnswer("Your appointment has been cancelled.", grounded=True)

    if not payload.doctor_id or not payload.slot:
        raise ValueError("Choose both a doctor and an available time.")
    slot = payload.slot.isoformat()
    if payload.slot <= datetime.now(timezone.utc):
        raise ValueError("Please choose a future appointment time.")
    valid_slots = {
        (row["doctor_id"], row["slot"])
        for row in appointment_options(user)["slots"]
    }
    if (payload.doctor_id, slot) not in valid_slots:
        raise ValueError("That time is not an available clinic slot. Please choose another time.")
    if payload.action == "book":
        try:
            user.db.table("appointments").insert({
                "clinic_id": user.clinic_id,
                "patient_id": user.db.table("patients").select("id").single().execute().data["id"],
                "doctor_id": payload.doctor_id,
                "slot": slot,
            }).execute()
        except Exception as exc:
            if "23505" in str(exc) or "duplicate" in str(exc).lower():
                raise ValueError("That time was just taken. Please choose another available time.") from exc
            raise
        return GroundedAnswer("Your appointment has been booked. You can review it in My Appointments.", grounded=True)

    if not payload.appointment_id:
        raise ValueError("Choose the appointment you want to reschedule.")
    try:
        result = user.db.table("appointments").update({"doctor_id": payload.doctor_id, "slot": slot}).eq(
            "id", payload.appointment_id
        ).eq("status", "booked").execute().data
    except Exception as exc:
        if "23505" in str(exc) or "duplicate" in str(exc).lower():
            raise ValueError("That time was just taken. Please choose another available time.") from exc
        raise
    if not result:
        raise ValueError("That appointment is no longer available to reschedule.")
    return GroundedAnswer("Your appointment has been rescheduled. You can review it in My Appointments.", grounded=True)


def _doctor_availability_answer(user: CurrentUser) -> GroundedAnswer:
    """Return staffing information, never another patient's booking data."""
    now = datetime.now(timezone.utc)
    doctors = (
        user.db.table("doctors").select("id, name, specialty, status")
        .eq("status", "available").order("name").execute().data
    )
    if not doctors:
        return GroundedAnswer(
            "There are no doctors currently listed as available. Please contact the clinic for help finding a suitable appointment.",
            grounded=True,
        )

    windows = (
        user.db.table("doctor_availability")
        .select("doctor_id, day_of_week, start_time, end_time").execute().data
    )
    current_time = now.time().replace(tzinfo=None).isoformat()
    active_ids = {
        row.get("doctor_id") for row in windows
        if row.get("day_of_week") == now.weekday()
        and row.get("start_time") is not None and row.get("end_time") is not None
        and str(row["start_time"]) <= current_time < str(row["end_time"])
    }
    active = [doctor for doctor in doctors if doctor.get("id") in active_ids]

    def format_doctors(rows):
        return ", ".join(
            f"Dr. {row.get('name')} ({row.get('specialty') or 'General'})" for row in rows
        )

    if active:
        return GroundedAnswer(
            f"Based on the clinic's current availability schedule, you can try: {format_doctors(active)}. "
            "Open the Appointments page to choose an available slot.",
            grounded=True,
        )
    return GroundedAnswer(
        f"The clinic currently lists these doctors as available: {format_doctors(doctors)}. "
        "There is no active availability window at this moment, so please check the Appointments page for upcoming slots.",
        grounded=True,
    )


def handle_appointment_query(user: CurrentUser, query: str) -> GroundedAnswer:
    if _AVAILABILITY_KEYWORDS.search(query):
        return _doctor_availability_answer(user)
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
