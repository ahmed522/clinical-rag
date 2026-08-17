"""
Request dependencies: who is calling, in what role, for which clinic.

Every tenant-scoped endpoint goes through here. The rule enforced in this
file is the product's core safety property: clinic_id comes from the
verified token and nowhere else.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import ROLE_CLINIC_ADMIN, ROLE_PATIENT, decode_access_token
from app.db import get_db
from app.models import Patient, User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = decode_access_token(credentials.credentials)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = db.query(User).filter(User.id == claims.get("sub")).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")

    # The token's tenant must still match the stored one. Without this, a
    # token issued before a user was moved between clinics would keep
    # working against the old tenant.
    if claims.get("clinic_id") != user.clinic_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant mismatch")

    return user


def require_clinic_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_CLINIC_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinic admin role required",
        )
    return user


def require_patient(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient role required",
        )
    return user


def current_patient(
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
) -> Patient:
    """
    The Patient row for the logged-in patient user.

    Scoped by clinic_id as well as auth_id so a patient can only ever
    resolve to a patient record inside their own clinic.
    """
    patient = (
        db.query(Patient)
        .filter(Patient.auth_id == user.id, Patient.clinic_id == user.clinic_id)
        .first()
    )
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No patient record linked to this account",
        )
    return patient
