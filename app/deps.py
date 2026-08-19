"""
Request dependencies: who is calling, in what role, for which clinic.

Every tenant-scoped endpoint goes through here. The rule enforced in this
file is the product's core safety property: clinic_id comes from the
verified Supabase token and nowhere else — never from a request body, a
query param, or anything else the caller controls.

Each resolved caller carries its OWN Supabase client (built via
client_for() with the caller's access token), so any database call a
route makes through it is subject to RLS as that specific user. There is
no path from a route handler back to admin_client() — that stays
confined to app/routers/auth.py's registration flow.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.supabase_client import client_for, verify_token

ROLE_CLINIC_ADMIN = "clinic_admin"
ROLE_DOCTOR = "doctor"
ROLE_PATIENT = "patient"

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """The verified caller: identity, tenant, role, and a client scoped to them."""

    user_id: str
    clinic_id: str
    role: str
    access_token: str
    db: Client


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    user = verify_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    metadata = user.app_metadata or {}
    clinic_id = metadata.get("clinic_id")
    role = metadata.get("role")

    # app_metadata is only writable by the service role (see
    # app/routers/auth.py), so a real account missing either claim means
    # registration itself went wrong — not something to paper over with a
    # default tenant.
    if not clinic_id or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not fully provisioned (missing clinic or role)",
        )

    return CurrentUser(
        user_id=user.id,
        clinic_id=clinic_id,
        role=role,
        access_token=token,
        db=client_for(token),
    )


def require_clinic_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != ROLE_CLINIC_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinic admin role required",
        )
    return user


def require_doctor(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != ROLE_DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor role required",
        )
    return user


def require_clinical_staff(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Evaluation reports are visible to doctors and clinic administrators, not patients."""
    if user.role not in {ROLE_DOCTOR, ROLE_CLINIC_ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor or clinic admin role required",
        )
    return user


def require_patient(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != ROLE_PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient role required",
        )
    return user


def current_patient_record(user: CurrentUser = Depends(require_patient)) -> dict:
    """
    The patients row for the logged-in patient.

    RLS's patients_select policy already restricts a non-admin caller to
    their own row, so this filters by auth_id only for clarity — the
    database is the actual enforcement, not this query. A miss here means
    registration created the auth user but never wrote the matching
    patients row.
    """
    result = user.db.table("patients").select("*").eq("auth_id", user.user_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No patient record linked to this account",
        )
    return result.data[0]
