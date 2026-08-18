"""
Request/response models.

Note what is absent: no request schema accepts a clinic_id. Tenancy is
taken from the JWT, so it cannot be supplied — or forged — by a caller.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------

class ClinicRegister(BaseModel):
    clinic_name: str = Field(..., min_length=1, max_length=255)
    specialty: str = Field("General", max_length=255)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8, max_length=72)


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
    token_type: str = "bearer"
    role: str
    clinic_id: str


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
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------

class SessionCreate(BaseModel):
    mode: str = Field("general", pattern="^(general|triage|consult)$")


class SessionOut(BaseModel):
    id: str
    mode: str
    started_at: datetime

    class Config:
        from_attributes = True


class MessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class Citation(BaseModel):
    document: str
    page: Optional[int] = None
    section: Optional[str] = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: Optional[List[Citation]] = None
    created_at: datetime

    class Config:
        from_attributes = True


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
