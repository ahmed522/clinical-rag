"""
Two-tier query intent classifier.

Tier 1: keyword match catches greetings with zero latency.
Tier 2: LLM classifies appointment vs. medical for everything else.
Defaults to MEDICAL on any ambiguity — the RAG pipeline already has
its own safe refusal path.
"""

import re
from enum import Enum
from typing import Optional, Tuple

class QueryIntent(Enum):
    GREETING = "greeting"
    APPOINTMENT = "appointment"
    AVAILABILITY = "availability"
    BOOK = "book"
    CANCEL = "cancel"
    RESCHEDULE = "reschedule"
    MEDICAL = "medical"


class GreetingType(Enum):
    HELLO = "hello"
    THANKS = "thanks"
    FAREWELL = "farewell"


_GREETING_PATTERNS: dict[GreetingType, set[str]] = {
    GreetingType.HELLO: {
        "hi", "hello", "hey", "hii", "hiii", "helo",
        "good morning", "good afternoon", "good evening", "good night",
        "assalamu alaikum", "salam", "marhaba", "ahlan",
        "yo", "howdy", "hiya",
    },
    GreetingType.THANKS: {
        "thanks", "thank you", "thank u", "thx", "ty",
        "shukran", "jazakallah",
        "much appreciated", "appreciate it",
    },
    GreetingType.FAREWELL: {
        "bye", "goodbye", "good bye", "see you", "see ya",
        "take care", "later", "cya",
        "ma salama", "fi aman allah",
    },
}

_ALL_GREETINGS: dict[str, GreetingType] = {}
for gtype, patterns in _GREETING_PATTERNS.items():
    for p in patterns:
        _ALL_GREETINGS[p] = gtype


# Scheduling/availability queries are safe deterministic data lookups. They
# should not depend on an LLM deciding what the patient meant.
_BOOKING_PATTERN = re.compile(r"\b(book|schedule|make)\b.{0,40}\b(appointment|visit|slot)\b|\bbook\b", re.IGNORECASE)
_CANCEL_PATTERN = re.compile(r"\b(cancel|remove)\b.{0,40}\b(appointment|visit|booking)\b|\bcancel\b", re.IGNORECASE)
_RESCHEDULE_PATTERN = re.compile(r"\b(reschedule|rebook|move|change)\b.{0,40}\b(appointment|visit|booking|slot)\b|\breschedule\b", re.IGNORECASE)
_AVAILABILITY_PATTERN = re.compile(
    r"\b(available\s+doctors?|doctor\s+availability|which\s+doctors?|"
    r"who\s+(?:is|are)\s+available|who\s+can\s+i\s+see|available\s+now)\b",
    re.IGNORECASE,
)
_APPOINTMENT_PATTERN = re.compile(r"\b(appointment|appointments|upcoming\s+visit|my\s+visit)\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).strip().lower()


def _detect_greeting(query: str) -> Optional[GreetingType]:
    normalized = _normalize(query)
    return _ALL_GREETINGS.get(normalized)


def classify_query(query: str) -> Tuple[QueryIntent, Optional[GreetingType]]:
    greeting_type = _detect_greeting(query)
    if greeting_type is not None:
        return QueryIntent.GREETING, greeting_type
    if _RESCHEDULE_PATTERN.search(query):
        return QueryIntent.RESCHEDULE, None
    if _CANCEL_PATTERN.search(query):
        return QueryIntent.CANCEL, None
    if _BOOKING_PATTERN.search(query):
        return QueryIntent.BOOK, None
    if _AVAILABILITY_PATTERN.search(query):
        return QueryIntent.AVAILABILITY, None
    if _APPOINTMENT_PATTERN.search(query):
        return QueryIntent.APPOINTMENT, None
    return QueryIntent.MEDICAL, None
