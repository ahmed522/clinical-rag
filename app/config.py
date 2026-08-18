"""
Application settings.

Separate from src/config.py, which configures the RAG pipeline. This file
configures the web application: database, auth, uploads, LLM provider.
The pipeline's own knobs (chunk size, retrieval k, distance gates) stay
in src/config.py so there is still one home for each concern.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env before any setting is read, so a local .env works without
# exporting anything by hand. Real environment variables still win —
# override=False — so a deployed environment is never overwritten by a
# stray .env that got copied along with the code.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    # python-dotenv is optional: without it, configuration comes from real
    # environment variables only, which is how deployments do it anyway.
    pass


def _normalize_supabase_url(raw: str) -> str:
    """
    The dashboard shows several URLs on the API settings page, and it is
    easy to copy the REST endpoint (".../rest/v1") instead of the bare
    project URL the client library actually wants — it appends "/rest/v1",
    "/auth/v1" etc. itself. Strip a copied suffix rather than fail with a
    confusing double path.
    """
    url = raw.rstrip("/")
    for suffix in ("/rest/v1", "/auth/v1", "/storage/v1"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


class Settings:
    # --------------------------------------------------------------
    # Supabase — database, auth, and storage (PRD architecture decision).
    #
    # SUPABASE_SERVICE_ROLE_KEY bypasses Row Level Security and must never
    # be sent to a browser or used to read/write tenant data — see
    # app/supabase_client.py for where each key is actually used.
    # --------------------------------------------------------------
    SUPABASE_URL = _normalize_supabase_url(os.getenv("SUPABASE_URL", ""))
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # --------------------------------------------------------------
    # Storage
    #
    # Uploaded PDFs live in the `guidelines` Supabase Storage bucket now
    # (per-clinic folders); this directory is only a local staging area
    # for the file mid-upload, before the pipeline and storage calls run.
    # --------------------------------------------------------------
    UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
    MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

    # --------------------------------------------------------------
    # CORS — the frontend (web/) calls this API directly from the browser
    # for document upload and chat, so its origin must be allowed
    # explicitly. Bearer tokens, not cookies, so credentials=True is not
    # needed and a comma-separated allowlist stays safe without it.
    # --------------------------------------------------------------
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if origin.strip()
    ]

    # --------------------------------------------------------------
    # LLM
    #
    # "mock" is a deterministic offline provider: it never invents
    # content, composing answers only from retrieved chunks. That keeps
    # the whole grounding path — including the refusal path — testable
    # without an API key. Swap via LLM_PROVIDER.
    # --------------------------------------------------------------
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")


settings = Settings()
