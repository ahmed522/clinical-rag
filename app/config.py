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


class Settings:
    # --------------------------------------------------------------
    # Database
    #
    # Defaults to SQLite so the demo runs with zero setup. PostgreSQL is
    # the production target (PRD sec.8) and needs no code change — set
    # DATABASE_URL and run docker-compose up. The schema is identical
    # either way because everything goes through SQLAlchemy.
    # --------------------------------------------------------------
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{PROJECT_ROOT / 'data' / 'clinical_rag.db'}",
    )

    # --------------------------------------------------------------
    # Auth
    #
    # The JWT carries `role` and `clinic_id`. Every tenant-scoped query
    # takes clinic_id from the token, never from the request body, so a
    # caller cannot ask for another clinic's data by editing a payload.
    # --------------------------------------------------------------
    JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-before-deploying")
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))

    # --------------------------------------------------------------
    # Storage
    # --------------------------------------------------------------
    UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
    MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

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
