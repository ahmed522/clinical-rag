"""
Two-tier query intent classifier.

Tier 1: keyword match catches greetings with zero latency.
Tier 2: LLM classifies appointment vs. medical for everything else.
Defaults to MEDICAL on any ambiguity — the RAG pipeline already has
its own safe refusal path.
"""

import json
import re
from enum import Enum
from typing import Optional, Tuple

from app.llm import get_provider
from app.llm_prompts import CLASSIFICATION_PROMPT


class QueryIntent(Enum):
    GREETING = "greeting"
    APPOINTMENT = "appointment"
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


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).strip().lower()


def _detect_greeting(query: str) -> Optional[GreetingType]:
    normalized = _normalize(query)
    return _ALL_GREETINGS.get(normalized)


def _llm_classify(query: str) -> QueryIntent:
    try:
        raw = get_provider().chat(CLASSIFICATION_PROMPT, query)
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1:
            return QueryIntent.MEDICAL
        data = json.loads(raw[start : end + 1])
        intent = data.get("intent", "medical").lower().strip()
        if intent == "appointment":
            return QueryIntent.APPOINTMENT
    except Exception:
        pass
    return QueryIntent.MEDICAL


def classify_query(query: str) -> Tuple[QueryIntent, Optional[GreetingType]]:
    greeting_type = _detect_greeting(query)
    if greeting_type is not None:
        return QueryIntent.GREETING, greeting_type
    return _llm_classify(query), None
