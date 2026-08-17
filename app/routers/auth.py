"""
Registration and login.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_PATIENT,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db import get_db
from app.deps import require_clinic_admin
from app.models import Clinic, Patient, User
from app.schemas import ClinicRegister, LoginRequest, PatientRegister, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register-clinic", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_clinic(payload: ClinicRegister, db: Session = Depends(get_db)):
    """Create a clinic (tenant) and its first admin."""
    existing = db.query(User).filter(User.email == payload.admin_email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered",
        )

    clinic = Clinic(name=payload.clinic_name, specialty=payload.specialty)
    db.add(clinic)
    db.flush()  # assign clinic.id before the user references it

    admin = User(
        clinic_id=clinic.id,
        email=payload.admin_email,
        password_hash=hash_password(payload.admin_password),
        role=ROLE_CLINIC_ADMIN,
    )
    db.add(admin)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(admin.id, admin.role, admin.clinic_id),
        role=admin.role,
        clinic_id=admin.clinic_id,
    )


@router.post("/register-patient", status_code=status.HTTP_201_CREATED)
def register_patient(
    payload: PatientRegister,
    db: Session = Depends(get_db),
    admin: User = Depends(require_clinic_admin),
):
    """
    Register a patient under the caller's clinic.

    The clinic comes from the admin's token, so a patient cannot be
    created inside someone else's clinic.
    """
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered",
        )

    user = User(
        clinic_id=admin.clinic_id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=ROLE_PATIENT,
    )
    db.add(user)
    db.flush()

    patient = Patient(
        clinic_id=admin.clinic_id,
        name=payload.name,
        age=payload.age,
        phone=payload.phone,
        auth_id=user.id,
    )
    db.add(patient)
    db.commit()

    return {"patient_id": patient.id, "user_id": user.id, "clinic_id": admin.clinic_id}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Same error whether the email is unknown or the password is wrong,
    # so the endpoint cannot be used to enumerate registered accounts.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    return TokenResponse(
        access_token=create_access_token(user.id, user.role, user.clinic_id),
        role=user.role,
        clinic_id=user.clinic_id,
    )
