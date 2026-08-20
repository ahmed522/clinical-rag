"""Verify the configured LLM provider without sending clinic or medical data."""

from __future__ import annotations

import json
import sys
from time import perf_counter

from app.config import settings
from app.llm import get_provider


def main() -> int:
    provider = get_provider()
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    model = getattr(provider, "model", None)
    started = perf_counter()
    try:
        raw = provider.chat(
            "Return only a valid JSON object. Do not add prose.",
            'Return exactly this JSON object: {"ok": true}',
        )
        payload = json.loads(raw)
        if payload.get("ok") is not True:
            raise ValueError(f"Unexpected response payload: {payload}")
    except Exception as exc:
        print(f"LLM connection: FAILED", file=sys.stderr)
        print(f"Provider: {provider_name}", file=sys.stderr)
        print(f"Model: {model}", file=sys.stderr)
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    print("LLM connection: OK")
    print(f"Provider: {provider_name}")
    print(f"Model: {model}")
    print(f"Latency: {elapsed_ms} ms")
    print(f"Verifier enabled: {settings.EVIDENCE_VERIFIER_ENABLED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
