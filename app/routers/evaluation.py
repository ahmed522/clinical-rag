"""Read-only access to the latest offline RAG evaluation artifact."""

import json
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, require_clinical_staff


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_PATHS = (
    PROJECT_ROOT / "evaluation" / "rag_report_configured.json",
    PROJECT_ROOT / "evaluation" / "rag_report.json",
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/latest", response_model=Dict[str, Any])
def latest_report(_user: CurrentUser = Depends(require_clinical_staff)):
    available = [path for path in REPORT_PATHS if path.exists()]
    if not available:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No RAG evaluation report has been generated yet",
        )
    try:
        latest = max(available, key=lambda path: path.stat().st_mtime)
        with open(latest, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The latest RAG evaluation report is unavailable",
        ) from exc
    return report
