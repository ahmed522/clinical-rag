"""
Request/response models.

Note what is absent: no request schema accepts a clinic_id. Tenancy is
taken from the JWT, so it cannot be supplied — or forged — by a caller.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------

class ClinicRegister(BaseModel):
    clinic_name: str = Field(..., min_length=1, max_length=255)
    specialty: str = Field("General", max_length=255)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8, max_length=72)
    # The clinic owner is a contact, not an account: the clinic contracts
    # with them directly and a receptionist fills out this registration.
    owner_name: Optional[str] = Field(None, max_length=255)
    owner_phone: Optional[str] = Field(None, max_length=64)
    owner_email: Optional[EmailStr] = None


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
    # Which doctor the patient is assigned to. Optional: with a single
    # doctor in the clinic the receptionist can omit it and the backend
    # auto-assigns; with more than one it is required.
    doctor_id: Optional[str] = Field(None, max_length=64)


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
    # Legacy triage sessions remain readable, but all newly-created patient
    # conversations are the single normal chat experience.
    mode: str = Field("general", pattern="^general$")


class SessionOut(BaseModel):
    id: str
    mode: str
    started_at: datetime
    # Not a DB column — computed only by GET /chat/sessions (list_sessions).
    # Defaults to 0 so create_session's return (a raw insert result, which
    # never sets this) still validates against this same response model.
    message_count: int = 0

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
    action: Optional[Literal["book", "cancel", "reschedule"]] = None


class AppointmentDoctor(BaseModel):
    id: str
    name: str
    specialty: Optional[str] = None


class AppointmentSlot(BaseModel):
    doctor_id: str
    slot: datetime


class PatientAppointment(BaseModel):
    id: str
    doctor_id: str
    slot: datetime
    status: str
    doctor_name: Optional[str] = None


class AppointmentOptionsOut(BaseModel):
    doctors: List[AppointmentDoctor] = Field(default_factory=list)
    slots: List[AppointmentSlot] = Field(default_factory=list)
    appointments: List[PatientAppointment] = Field(default_factory=list)


class AppointmentActionIn(BaseModel):
    action: Literal["book", "cancel", "reschedule"]
    confirmed: bool = False
    doctor_id: Optional[str] = None
    slot: Optional[datetime] = None
    appointment_id: Optional[str] = None


class AppointmentActionOut(BaseModel):
    message: MessageOut
    grounded: bool
    reason: Optional[str] = None


# ----------------------------------------------------------------------
# Doctor chat (same retrieval as patients, clinician prompt and private history)
# ----------------------------------------------------------------------

class DoctorChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class DoctorChatReply(BaseModel):
    """
    Compatibility response for the original single-turn doctor endpoint.
    Persisted conversations use the doctor-session endpoints below.
    """

    content: str
    grounded: bool
    reason: Optional[str] = None
    citations: Optional[List[Citation]] = None
    evidence_strength: Optional[str] = None
    evidence: Optional[EvidencePackage] = None


class DoctorChatSessionOut(BaseModel):
    id: str
    started_at: datetime
    message_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class DoctorMessageOut(BaseModel):
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


# ----------------------------------------------------------------------
# Bug reports (doctor -> IT queue) and IT pipeline test
# ----------------------------------------------------------------------

class BugReportCreate(BaseModel):
    issue: str = Field(..., min_length=1, max_length=4000)


class BugReportStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|investigating|resolved)$")


class BugReportOut(BaseModel):
    id: str
    clinic_id: str
    document_id: Optional[str] = None
    reported_by: Optional[str] = None
    issue: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PipelineTestRequest(BaseModel):
    document_id: str = Field(..., max_length=64)
    question: str = Field(..., min_length=1, max_length=4000)
