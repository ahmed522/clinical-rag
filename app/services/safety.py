"""Deterministic pre-generation checks for explicit personal clinical requests."""

from __future__ import annotations

import re


_PERSONAL_DIAGNOSIS = re.compile(
    r"\b(?:do i have|what do i have|what(?:'s| is) wrong with me|diagnose me|"
    r"my diagnosis|diagnosis for me|is this (?:a|an)|are these symptoms|what condition do i)\b",
    re.IGNORECASE,
)

_PERSONAL_DOSAGE = re.compile(
    r"\b(?:what|which|how (?:much|many|often)|should|can|may)\b.{0,45}"
    r"\b(?:i|me|my)\b.{0,45}\b(?:dose|dosage|take|tablet|pill|medicine|medication|"
    r"increase|decrease|start|stop|change)\b|"
    r"\b(?:increase|decrease|start|stop|change)\b.{0,30}\bmy\b.{0,20}"
    r"\b(?:dose|medicine|medication|treatment)\b|"
    r"\b(?:dose|dosage|prescribe|prescription|treat)\b.{0,80}\b(?:my patient|for me|i should|i)\b",
    re.IGNORECASE,
)


def personal_clinical_request(question: str) -> str | None:
    """Return the explicit unsafe request type, keeping general questions allowed."""
    normalized = " ".join(question.split())
    if _PERSONAL_DIAGNOSIS.search(normalized):
        return "patient_specific_diagnosis"
    if _PERSONAL_DOSAGE.search(normalized):
        return "patient_specific_dosage_or_treatment"
    return None
