"""
Clinical RAG SaaS — application entrypoint.

Run with:
    uvicorn app.main:app --reload

Interactive API docs at http://127.0.0.1:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.db import init_db
from app.routers import auth, chat, documents


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Clinical RAG",
    description=(
        "Multi-tenant clinical guideline assistant. Every clinic's documents "
        "are isolated in their own vector collection, and every patient-facing "
        "answer is grounded in that clinic's uploaded guidance with citations, "
        "or honestly refused."
    ),
    version="0.1.0",
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
