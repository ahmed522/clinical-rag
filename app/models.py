"""
Multi-tenant schema (PRD sec.9).

Tenancy rule: every domain table carries `clinic_id`, including tables
that are only one hop from the clinic (medical_records, messages reach it
via patient/session). Denormalising it means every query can filter by
tenant directly instead of relying on a join being written correctly —
one forgotten join is a cross-clinic data leak.

UUIDs are stored as CHAR(36) rather than a native UUID column so the same
schema runs on both SQLite (demo) and PostgreSQL (production).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


def new_uuid():
    return str(uuid.uuid4())


def uuid_pk():
    return Column(String(36), primary_key=True, default=new_uuid)


class Clinic(Base):
    __tablename__ = "clinics"

    id = uuid_pk()
    name = Column(String(255), nullable=False)
    specialty = Column(String(255), nullable=False, default="General")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    users = relationship("User", back_populates="clinic")
    documents = relationship("Document", back_populates="clinic")


class User(Base):
    """
    Login identity for both roles.

    Not in the PRD's table list, but auth needs somewhere to hold
    credentials. `patients.auth_id` points here for patient logins;
    clinic admins have a User with no Patient row.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id = uuid_pk()
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)  # clinic_admin | patient
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    clinic = relationship("Clinic", back_populates="users")


class Doctor(Base):
    __tablename__ = "doctors"

    id = uuid_pk()
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    specialty = Column(String(255), nullable=False, default="General")
    status = Column(String(32), nullable=False, default="available")  # available | off


class Patient(Base):
    __tablename__ = "patients"

    id = uuid_pk()
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    age = Column(Integer, nullable=True)
    phone = Column(String(64), nullable=True)
    auth_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)


class Document(Base):
    """
    An uploaded guideline.

    `verified` starts False: a clinic admin must confirm the source is
    official before it is used in patient-facing answers (guardrail #5).
    """

    __tablename__ = "documents"

    id = uuid_pk()
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    publisher = Column(String(255), nullable=True)
    source_url = Column(String(1024), nullable=True)
    topic = Column(String(255), nullable=True)
    file_path = Column(String(1024), nullable=False)
    verified = Column(Boolean, nullable=False, default=False)
    page_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    clinic = relationship("Clinic", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """
    Provenance record for one chunk.

    Deliberately mirrored with the vector store: this row is the source of
    truth for where the text came from, while the vector store holds the
    embedding. `vector_ref` is the join key and equals the chunk id used
    in Chroma — which is why chunk ids must be deterministic
    (src/chunk.py: make_chunk_id), or re-ingesting a document would orphan
    every row here.
    """

    __tablename__ = "chunks"

    id = uuid_pk()
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    section_title = Column(String(512), nullable=True)
    page_number = Column(Integer, nullable=True)
    vector_ref = Column(String(255), nullable=False, index=True)

    document = relationship("Document", back_populates="chunks")


class Appointment(Base):
    __tablename__ = "appointments"

    id = uuid_pk()
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = Column(String(36), ForeignKey("doctors.id"), nullable=False, index=True)
    slot = Column(DateTime, nullable=False)
    status = Column(String(32), nullable=False, default="booked")  # booked|cancelled|done


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id = uuid_pk()
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    diagnosis = Column(String(512), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = uuid_pk()
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    mode = Column(String(32), nullable=False, default="general")  # general|triage|consult
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    """
    One turn of a conversation.

    `citations` stores the resolved {document title, page} list actually
    used, so an answer stays auditable after the fact — a clinician can
    check what the system claimed and where it came from.
    """

    __tablename__ = "messages"

    id = uuid_pk()
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False, index=True)
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ChatSession", back_populates="messages")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = uuid_pk()
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    clinic_id = Column(String(36), ForeignKey("clinics.id"), nullable=False, index=True)
    tier = Column(String(32), nullable=False, default="free")  # free | premium
    status = Column(String(32), nullable=False, default="active")
    renews_at = Column(DateTime, nullable=True)
