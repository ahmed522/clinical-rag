"""LLM provider boundary for structured, evidence-audited generation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, List

from app.config import settings
from app.llm_prompts import EVIDENCE_VERIFICATION_PROMPT


def _json_object(raw: str) -> dict:
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < start:
            return {}
        value = json.loads(raw[start : end + 1])
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


@dataclass(frozen=True)
class EvidenceReference:
    source_id: int
    excerpt: str

    @classmethod
    def from_value(cls, value: Any) -> "EvidenceReference | None":
        if not isinstance(value, dict):
            return None
        source_id = value.get("source_id")
        excerpt = value.get("excerpt")
        if not isinstance(source_id, int) or isinstance(source_id, bool):
            return None
        if not isinstance(excerpt, str) or not excerpt.strip():
            return None
        return cls(source_id=source_id, excerpt=excerpt.strip())


@dataclass(frozen=True)
class GeneratedClaim:
    text: str
    evidence: List[EvidenceReference] = field(default_factory=list)

    @classmethod
    def from_value(cls, value: Any) -> "GeneratedClaim | None":
        if not isinstance(value, dict):
            return None
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        refs = []
        for item in value.get("evidence", []):
            parsed = EvidenceReference.from_value(item)
            if parsed is not None:
                refs.append(parsed)
        return cls(text=text.strip(), evidence=refs)


@dataclass
class LLMResult:
    recommendation_claims: List[GeneratedClaim] = field(default_factory=list)
    supporting_claims: List[GeneratedClaim] = field(default_factory=list)
    sufficient: bool = False
    partial: bool = False
    missing_evidence: str = ""

    @classmethod
    def from_json(cls, raw: str) -> "LLMResult":
        data = _json_object(raw)
        recommendations = [
            claim
            for item in data.get("recommendation_claims", [])
            if (claim := GeneratedClaim.from_value(item)) is not None
        ]
        supporting = [
            claim
            for item in data.get("supporting_claims", [])
            if (claim := GeneratedClaim.from_value(item)) is not None
        ]
        sufficient = data.get("sufficient") is True
        if sufficient and not recommendations:
            sufficient = False
        return cls(
            recommendation_claims=recommendations,
            supporting_claims=supporting,
            sufficient=sufficient,
            partial=data.get("partial") is True,
            missing_evidence=str(data.get("missing_evidence") or "").strip(),
        )


@dataclass(frozen=True)
class ClaimVerification:
    claim_id: str
    supported: bool
    relevant: bool
    safe: bool
    overconfident: bool
    reason: str = ""


@dataclass
class VerificationResult:
    results: List[ClaimVerification] = field(default_factory=list)

    @classmethod
    def from_json(cls, raw: str) -> "VerificationResult":
        data = _json_object(raw)
        results = []
        for value in data.get("results", []):
            if not isinstance(value, dict) or not isinstance(value.get("claim_id"), str):
                continue
            results.append(
                ClaimVerification(
                    claim_id=value["claim_id"].strip(),
                    supported=value.get("supported") is True,
                    relevant=value.get("relevant") is True,
                    safe=value.get("safe") is True,
                    overconfident=value.get("overconfident") is True,
                    reason=str(value.get("reason") or "").strip(),
                )
            )
        return cls(results=results)


def _verification_message(question: str, claims: List[dict]) -> str:
    payload = {"patient_question": question, "claims": claims}
    return (
        "BEGIN_UNTRUSTED_EVIDENCE_AUDIT_INPUT\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\nEND_UNTRUSTED_EVIDENCE_AUDIT_INPUT"
    )


class MockProvider:
    """Deterministic provider that only derives output from retrieved text."""

    name = "mock"
    model = "deterministic-extractive"

    def chat(self, system: str, message: str) -> str:
        return '{"intent": "medical"}'

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        if not sources:
            return LLMResult(sufficient=False, missing_evidence="No source was retrieved.")

        excerpt = " ".join(sources[0]["text"].split())
        if len(excerpt) > 420:
            excerpt = excerpt[:420].rsplit(" ", 1)[0]
        claim = GeneratedClaim(
            text=f"The clinic's uploaded guidance states: {excerpt}",
            evidence=[EvidenceReference(source_id=1, excerpt=excerpt)],
        )
        return LLMResult(recommendation_claims=[claim], sufficient=True)

    def verify(self, question: str, claims: List[dict]) -> VerificationResult:
        return VerificationResult(
            results=[
                ClaimVerification(
                    claim_id=claim["claim_id"],
                    supported=bool(claim.get("excerpts")),
                    relevant=True,
                    safe=True,
                    overconfident=False,
                    reason="Deterministic mock accepted mechanically validated evidence.",
                )
                for claim in claims
            ]
        )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model or "claude-sonnet-4-5"
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")

    def _client(self, timeout: float):
        import anthropic

        return anthropic.Anthropic(api_key=self.api_key, timeout=timeout)

    @staticmethod
    def _text(response) -> str:
        return "".join(block.text for block in response.content if block.type == "text")

    def chat(self, system: str, message: str) -> str:
        response = self._client(settings.LLM_TIMEOUT_SECONDS).messages.create(
            model=self.model,
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": message}],
        )
        return self._text(response)

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        response = self._client(settings.LLM_TIMEOUT_SECONDS).messages.create(
            model=self.model,
            max_tokens=1600,
            system=system,
            messages=[{"role": "user", "content": _user_message(sources, question, context)}],
        )
        return LLMResult.from_json(self._text(response))

    def verify(self, question: str, claims: List[dict]) -> VerificationResult:
        response = self._client(settings.EVIDENCE_VERIFIER_TIMEOUT_SECONDS).messages.create(
            model=self.model,
            max_tokens=1000,
            system=EVIDENCE_VERIFICATION_PROMPT,
            messages=[{"role": "user", "content": _verification_message(question, claims)}],
        )
        return VerificationResult.from_json(self._text(response))


class GroqProvider:
    name = "groq"
    DEFAULT_MODEL = "openai/gpt-oss-120b"

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")

    def _client(self, timeout: float):
        from groq import Groq

        return Groq(api_key=self.api_key, timeout=timeout)

    def _request(self, system: str, message: str, max_tokens: int, timeout: float) -> str:
        extra = {}
        # Omitted entirely when unset, so a non-reasoning Groq model does not
        # 400 on an unsupported parameter.
        if settings.LLM_REASONING_EFFORT:
            extra["reasoning_effort"] = settings.LLM_REASONING_EFFORT
        response = self._client(timeout).chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=max_tokens,
            **extra,
        )
        return response.choices[0].message.content or ""

    def chat(self, system: str, message: str) -> str:
        return self._request(system, message, 128, settings.LLM_TIMEOUT_SECONDS)

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        # Headroom over the ~500 tokens a low-effort answer actually uses:
        # truncation here is not a short answer, it is a hard 400 from Groq.
        raw = self._request(system, _user_message(sources, question, context), 3000, settings.LLM_TIMEOUT_SECONDS)
        return LLMResult.from_json(raw)

    def verify(self, question: str, claims: List[dict]) -> VerificationResult:
        raw = self._request(
            EVIDENCE_VERIFICATION_PROMPT,
            _verification_message(question, claims),
            1000,
            settings.EVIDENCE_VERIFIER_TIMEOUT_SECONDS,
        )
        return VerificationResult.from_json(raw)


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model or "gpt-4o-mini"
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")

    def _request(self, system: str, message: str, max_tokens: int, timeout: float) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, timeout=timeout)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat(self, system: str, message: str) -> str:
        return self._request(system, message, 128, settings.LLM_TIMEOUT_SECONDS)

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        raw = self._request(system, _user_message(sources, question, context), 1600, settings.LLM_TIMEOUT_SECONDS)
        return LLMResult.from_json(raw)

    def verify(self, question: str, claims: List[dict]) -> VerificationResult:
        raw = self._request(
            EVIDENCE_VERIFICATION_PROMPT,
            _verification_message(question, claims),
            1000,
            settings.EVIDENCE_VERIFIER_TIMEOUT_SECONDS,
        )
        return VerificationResult.from_json(raw)


class OpenRouterProvider:
    """OpenAI-compatible endpoint over OpenRouter's free-tagged open models.

    Free tier there is request-count-limited (not token-limited like Groq),
    so this is a manual failover to switch to via LLM_PROVIDER when Groq is
    rate-limited, not a replacement default. Verify the current free model
    lineup at openrouter.ai before relying on the default below — free
    model availability rotates.
    """

    name = "openrouter"
    # Verified live on openrouter.ai on 2026-08-19: two active free
    # providers (Google AI Studio, Darkbloom), 100% 3-day uptime, explicit
    # "structured output support" — relevant since complete()/verify() both
    # require response_format json_object. Free model availability rotates;
    # re-check openrouter.ai/models?max_price=0 before trusting this later.
    DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    def _client(self, timeout: float):
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=timeout,
        )

    def _request(self, system: str, message: str, max_tokens: int, timeout: float) -> str:
        response = self._client(timeout).chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat(self, system: str, message: str) -> str:
        return self._request(system, message, 128, settings.LLM_TIMEOUT_SECONDS)

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        # Headroom against truncation on free open models, matching the
        # same lesson learned from Groq's reasoning-token truncation bug.
        raw = self._request(system, _user_message(sources, question, context), 3000, settings.LLM_TIMEOUT_SECONDS)
        return LLMResult.from_json(raw)

    def verify(self, question: str, claims: List[dict]) -> VerificationResult:
        raw = self._request(
            EVIDENCE_VERIFICATION_PROMPT,
            _verification_message(question, claims),
            1000,
            settings.EVIDENCE_VERIFIER_TIMEOUT_SECONDS,
        )
        return VerificationResult.from_json(raw)


def _user_message(sources: List[dict], question: str, context: str = "") -> str:
    """Render retrieved text as numbered, explicitly untrusted evidence."""
    blocks = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            f"BEGIN_UNTRUSTED_SOURCE_{index}\n"
            f"[{index}] {source['title']} — page {source.get('page_number')}"
            f"{', ' + source['section_title'] if source.get('section_title') else ''}\n"
            f"{source['text']}\n"
            f"END_UNTRUSTED_SOURCE_{index}"
        )

    parts = ["SOURCES:", "\n\n".join(blocks) if blocks else "(none)"]
    if context:
        parts += ["", "BEGIN_UNTRUSTED_PATIENT_CONTEXT", context, "END_UNTRUSTED_PATIENT_CONTEXT"]
    if blocks:
        parts += ["", f"Valid source_id integers: 1 to {len(blocks)}."]
    parts += ["", "BEGIN_PATIENT_QUESTION", question, "END_PATIENT_QUESTION"]
    return "\n".join(parts)


def get_provider():
    provider = (settings.LLM_PROVIDER or "mock").lower()
    if provider == "groq":
        return GroqProvider(settings.LLM_MODEL, settings.LLM_API_KEY)
    if provider == "anthropic":
        return AnthropicProvider(settings.LLM_MODEL, settings.LLM_API_KEY)
    if provider == "openai":
        return OpenAIProvider(settings.LLM_MODEL, settings.LLM_API_KEY)
    if provider == "openrouter":
        return OpenRouterProvider(settings.LLM_MODEL, settings.LLM_API_KEY)
    return MockProvider()
