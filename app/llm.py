"""
LLM provider interface.

One seam so the provider can be swapped without touching the generation
logic or the prompts (PRD sec.8).

The default provider is a deterministic mock. That is a real choice, not
a placeholder: it lets the entire grounding path — retrieval, the refusal
branch, citation validation, persistence — be exercised and tested with
no API key and no network. The mock never invents clinical content; it
only quotes retrieved chunks, so a demo cannot accidentally show
fabricated medical text.
"""

import json
import os
from typing import List, Optional

from app.config import settings


class LLMResult:
    """Structured answer: prose, which sources were used, and whether the model could answer."""

    def __init__(self, answer: str, citations: Optional[List[int]] = None, sufficient: bool = True):
        self.answer = answer
        self.citations = citations or []
        self.sufficient = sufficient

    @classmethod
    def from_json(cls, raw: str) -> "LLMResult":
        """
        Parse a provider response.

        A provider that returns unparseable output is treated as unable to
        answer rather than having its raw text passed through to a
        patient — malformed output must not become an ungrounded answer.
        """
        try:
            start, end = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[start : end + 1]) if start != -1 else {}
        except (ValueError, TypeError):
            return cls("", [], sufficient=False)

        citations = [c for c in data.get("citations", []) if isinstance(c, int)]
        return cls(
            answer=str(data.get("answer", "")).strip(),
            citations=citations,
            sufficient=bool(data.get("sufficient", False)),
        )


class MockProvider:
    """
    Deterministic, offline, and incapable of inventing clinical content.

    Answers are assembled from the retrieved sources verbatim. If nothing
    was retrieved it reports insufficient rather than producing prose,
    which is exactly the behaviour the real providers are instructed to
    follow.
    """

    name = "mock"

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        if not sources:
            return LLMResult("", [], sufficient=False)

        top = sources[0]
        excerpt = " ".join(top["text"].split())
        if len(excerpt) > 400:
            excerpt = excerpt[:400].rsplit(" ", 1)[0] + "..."

        answer = (
            f"Based on the clinic's uploaded guidance [1]: {excerpt}\n\n"
            "This is general information from your clinic's documents, not "
            "advice about your individual case. Please speak to your doctor "
            "about what it means for you."
        )
        return LLMResult(answer, [1], sufficient=True)


class AnthropicProvider:
    """Claude. Requires LLM_API_KEY and the `anthropic` package."""

    name = "anthropic"

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model or "claude-sonnet-4-5"
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": _user_message(sources, question, context)}],
        )
        return LLMResult.from_json("".join(b.text for b in response.content if b.type == "text"))


class GroqProvider:
    """
    Groq. Requires LLM_API_KEY (or GROQ_API_KEY) and the `groq` package.

    Temperature is pinned low deliberately. The prompt forbids using
    anything outside the retrieved sources, and sampling variety is exactly
    what erodes that: the failure mode here is not a dull answer, it is a
    plausible sentence that no source supports.
    """

    name = "groq"

    # Chosen by testing the actual JSON contract against what Groq serves:
    # qwen3.6-27b fails Groq's own json_object validation on this prompt,
    # and the llama-3.x models are not available on the free tier. Swap via
    # LLM_MODEL without touching this file.
    DEFAULT_MODEL = "openai/gpt-oss-120b"

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        from groq import Groq

        client = Groq(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _user_message(sources, question, context)},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=1024,
        )
        return LLMResult.from_json(response.choices[0].message.content or "")


class OpenAIProvider:
    """OpenAI chat completions. Requires LLM_API_KEY and the `openai` package."""

    name = "openai"

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model or "gpt-4o-mini"
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")

    def complete(self, system: str, sources: List[dict], question: str, context: str = "") -> LLMResult:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _user_message(sources, question, context)},
            ],
            response_format={"type": "json_object"},
        )
        return LLMResult.from_json(response.choices[0].message.content or "")


def _user_message(sources: List[dict], question: str, context: str = "") -> str:
    """Render sources as a numbered list the model can cite by index."""
    blocks = []
    for i, source in enumerate(sources, start=1):
        blocks.append(
            f"[{i}] {source['title']} — page {source['page_number']}"
            f"{', ' + source['section_title'] if source.get('section_title') else ''}\n"
            f"{source['text']}"
        )

    parts = ["SOURCES:", "\n\n".join(blocks) if blocks else "(none)"]
    if context:
        parts += ["", "PATIENT CONTEXT:", context]
    if blocks:
        # State the range explicitly. Left implicit, models cite numbers
        # that were never offered — one ran sources 1 and 2 together as
        # "12", which citation validation then rejected, throwing away a
        # perfectly good grounded answer.
        parts += [
            "",
            f"Valid source numbers: 1 to {len(blocks)}. "
            f'Cite each as its own integer, e.g. "citations": [1, 2].',
        ]
    parts += ["", f"PATIENT QUESTION: {question}"]
    return "\n".join(parts)


def get_provider():
    provider = (settings.LLM_PROVIDER or "mock").lower()
    if provider == "groq":
        return GroqProvider(settings.LLM_MODEL, settings.LLM_API_KEY)
    if provider == "anthropic":
        return AnthropicProvider(settings.LLM_MODEL, settings.LLM_API_KEY)
    if provider == "openai":
        return OpenAIProvider(settings.LLM_MODEL, settings.LLM_API_KEY)
    return MockProvider()
