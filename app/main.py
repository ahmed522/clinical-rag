"""
Clinical RAG SaaS — application entrypoint.

Run with:
    uvicorn app.main:app --reload

Interactive API docs at http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import settings
from app.routers import auth, chat, documents

# No lifespan/init_db step: the schema lives in Supabase, applied via
# supabase/migrations/0001_schema_and_rls.sql against the project directly
# (`psql` or the SQL editor), not created by this app at startup.

app = FastAPI(
    title="Clinical RAG",
    description=(
        "Multi-tenant clinical guideline assistant. Every clinic's documents "
        "are isolated in their own vector collection, and every patient-facing "
        "answer is grounded in that clinic's uploaded guidance with citations, "
        "or honestly refused."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
def root():
    """
    Send the bare host to the API docs.

    There is no frontend yet, so hitting http://127.0.0.1:8000 otherwise
    returns a bare 404 that reads like the server is broken when it is
    running fine.
    """
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
