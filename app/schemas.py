"""
Request/response models.

Note what is absent: no request schema accepts a clinic_id. Tenancy is
taken from the JWT, so it cannot be supplied — or forged — by a caller.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------

class ClinicRegister(BaseModel):
    clinic_name: str = Field(..., min_length=1, max_length=255)
    specialty: str = Field("General", max_length=255)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8, max_length=72)


class DoctorRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    specialty: str = Field("General", max_length=255)


class PatientRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    age: Optional[int] = Field(None, ge=0, le=130)
    phone: Optional[str] = Field(None, max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    clinic_id: str


class ClinicPublicOut(BaseModel):
    """
    Non-clinical, non-sensitive — just enough for the /clinic/{slug} page
    to show branding before login and for the frontend to verify the
    authenticated patient's clinic_id actually matches this slug after.
    """

    id: str
    name: str
    slug: str


# ----------------------------------------------------------------------
# Documents
# ----------------------------------------------------------------------

class DocumentOut(BaseModel):
    id: str
    title: str
    publisher: Optional[str] = None
    source_url: Optional[str] = None
    topic: Optional[str] = None
    verified: bool
    status: str = "ready"
    processing_error: Optional[str] = None
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    file_sha256: Optional[str] = None
    extraction_report: Dict[str, Any] = Field(default_factory=dict)
    extraction_version: Optional[str] = None
    chunking_version: Optional[str] = None
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------

class SessionCreate(BaseModel):
    mode: str = Field("general", pattern="^(general|triage)$")


class SessionOut(BaseModel):
    id: str
    mode: str
    started_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class Citation(BaseModel):
    id: Optional[str] = None
    source_id: Optional[int] = None
    rank: Optional[int] = None
    document_id: Optional[str] = None
    document: str
    publisher: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_id: Optional[str] = None
    source_url: Optional[str] = None
    excerpt: Optional[str] = None
    vector_distance: Optional[float] = None
    rerank_score: Optional[float] = None


class EvidenceChecks(BaseModel):
    retrieval_passed: bool = False
    exact_excerpts_passed: bool = False
    citation_coverage: float = Field(0.0, ge=0.0, le=1.0)
    evidence_match_passed: bool = False
    safety_passed: bool = False
    verifier_passed: bool = False


class RecommendationClaim(BaseModel):
    claim_id: str
    text: str
    citation_ids: List[str] = Field(default_factory=list)


class SupportingEvidence(BaseModel):
    claim_id: str
    claim: str
    citation_ids: List[str] = Field(default_factory=list)


class EvidencePackage(BaseModel):
    recommendation: str
    recommendation_claims: List[RecommendationClaim] = Field(default_factory=list)
    supporting_evidence: List[SupportingEvidence] = Field(default_factory=list)
    evidence_strength: str = Field(pattern="^(high|medium|low|insufficient)$")
    safety_notice: str
    evidence_checked: List[str] = Field(default_factory=list)
    missing_evidence: str = ""
    checks: EvidenceChecks


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: Optional[List[Citation]] = None
    grounded: Optional[bool] = None
    reason: Optional[str] = None
    evidence_strength: Optional[str] = None
    evidence: Optional[EvidencePackage] = None
    prompt_version: Optional[str] = None
    rag_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatReply(BaseModel):
    """
    The answer plus why it looks the way it does.

    `grounded` is False when the system declined to answer from the
    documents. Surfacing it explicitly keeps a refusal visibly different
    from an answer, rather than a paragraph the UI has to interpret.
    """

    message: MessageOut
    grounded: bool
    reason: Optional[str] = None
