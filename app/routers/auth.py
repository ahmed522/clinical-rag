"""
Registration and login, backed by Supabase Auth.

Every account's tenant lives in `app_metadata` (clinic_id, role) — never
`user_metadata`, which the user themselves can update via the Supabase
client. Putting the tenant there would let a patient re-tenant their own
account. app_metadata can only be set with the service role, which is why
admin_client() (and only it) appears in this file.

Three roles, three registration paths, one direction of authority:
clinic admin registers doctors; a doctor registers their own patients.
Nobody self-registers except the clinic's first admin.

Login is also exposed here as a thin pass-through to Supabase Auth. A
production frontend can call supabase-js directly for this — nothing here
does anything the client SDK couldn't — but keeping the endpoint gives
scripts, tests, and any non-browser client one consistent way in.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, status
from supabase_auth.errors import AuthApiError

from app.deps import (
    ROLE_CLINIC_ADMIN,
    ROLE_DOCTOR,
    ROLE_PATIENT,
    CurrentUser,
    require_clinic_admin,
)
from app.schemas import ClinicRegister, DoctorRegister, LoginRequest, PatientRegister, TokenResponse
from app.supabase_client import admin_client, anon_client

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str) -> str:
    """
    A clinic's URL identifier — lowercase, ascii-ish, dash-separated.

    Not cryptographic and not required to be unguessable: it names a
    clinic's login page, not a capability. The actual tenant boundary
    downstream is the JWT's clinic_id, never the slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "clinic"


def _unique_slug(admin, base_slug: str) -> str:
    """Appends -2, -3, ... on collision, checked against the real table."""
    candidate = base_slug
    suffix = 2
    while admin.table("clinics").select("id").eq("slug", candidate).execute().data:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    return candidate


@router.post(
    "/register-clinic",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a clinic and its admin (no auth required)",
    responses={409: {"description": "Email already registered"}},
)
def register_clinic(payload: ClinicRegister):
    """
    Create a clinic (tenant) and its first admin.

    **Start here.** This is the only registration endpoint that needs no
    token. Whoever the clinic owner designates (a receptionist) fills this
    out and becomes the first account. It returns that account's
    `access_token` — authorize with it to register doctors and patients and
    view clinic statistics. The receptionist never touches documents,
    medical records, or chat (enforced by RLS, not just the UI).
    """
    admin = admin_client()

    slug = _unique_slug(admin, _slugify(payload.clinic_name))
    clinic = admin.table("clinics").insert({
        "name": payload.clinic_name,
        "specialty": payload.specialty,
        "slug": slug,
        "owner_name": payload.owner_name,
        "owner_phone": payload.owner_phone,
        "owner_email": payload.owner_email,
    }).execute().data[0]

    try:
        admin.auth.admin.create_user({
            "email": payload.admin_email,
            "password": payload.admin_password,
            "email_confirm": True,
            "app_metadata": {"clinic_id": clinic["id"], "role": ROLE_CLINIC_ADMIN},
        })
    except AuthApiError as exc:
        # The clinic row is orphaned if account creation fails (e.g. the
        # email is already registered). Roll it back rather than leave a
        # tenant with no admin able to reach it.
        admin.table("clinics").delete().eq("id", clinic["id"]).execute()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    session = anon_client().auth.sign_in_with_password(
        {"email": payload.admin_email, "password": payload.admin_password}
    )

    return TokenResponse(
        access_token=session.session.access_token,
        refresh_token=session.session.refresh_token,
        role=ROLE_CLINIC_ADMIN,
        clinic_id=clinic["id"],
    )


@router.post(
    "/register-doctor",
    status_code=status.HTTP_201_CREATED,
    summary="Register a doctor (clinic admin only)",
    responses={
        401: {"description": "Missing or invalid token — authorize as a clinic admin first"},
        403: {"description": "Authenticated, but not a clinic admin"},
        409: {"description": "Email already registered"},
    },
)
def register_doctor(payload: DoctorRegister, admin: CurrentUser = Depends(require_clinic_admin)):
    """
    Register a doctor under the caller's clinic.

    The admin sets the doctor's initial password and communicates it to
    them directly (call, message — no email delivery in the MVP). The
    doctor is required to change it on first login: must_change_password
    defaults to true and the frontend gates on it before anything else.
    """
    root = admin_client()

    try:
        user = root.auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
            "app_metadata": {"clinic_id": admin.clinic_id, "role": ROLE_DOCTOR},
        })
    except AuthApiError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    # Insert through the ADMIN's own client: doctors_admin_write already
    # allows a clinic admin to write doctor rows for their own clinic_id,
    # so this goes through the same policy every other write does.
    doctor = admin.db.table("doctors").insert({
        "clinic_id": admin.clinic_id,
        "auth_id": user.user.id,
        "name": payload.name,
        "email": payload.email,
        "specialty": payload.specialty,
    }).execute().data[0]

    return {"doctor_id": doctor["id"], "user_id": user.user.id, "clinic_id": admin.clinic_id}


@router.post(
    "/register-patient",
    status_code=status.HTTP_201_CREATED,
    summary="Register a patient (receptionist / clinic admin only)",
    responses={
        400: {"description": "No doctor to assign, or an invalid doctor for this clinic"},
        401: {"description": "Missing or invalid token — authorize as a receptionist first"},
        403: {"description": "Authenticated, but not a receptionist"},
        409: {"description": "Email already registered"},
    },
)
def register_patient(payload: PatientRegister, admin: CurrentUser = Depends(require_clinic_admin)):
    """
    Register a patient under the caller's clinic, assigned to a doctor.

    Patient registration is the receptionist's job — a data-entry task, not
    a clinical one. The patient must still be attached to a doctor from the
    start (that link is the ownership key used throughout RLS). If the
    clinic has exactly one doctor and none is named, it is assigned
    automatically; with more than one, `doctor_id` is required. The
    receptionist sets the initial password and shares the clinic link +
    credentials with the patient directly; must_change_password forces them
    to set their own on first login.
    """
    # Resolve which doctor this patient is assigned to, restricted to the
    # caller's own clinic. This runs through the admin's RLS-scoped client,
    # so doctors_select already limits it to this clinic; the explicit
    # clinic_id filter is defensive redundancy, not the boundary.
    clinic_doctors = (
        admin.db.table("doctors").select("id").eq("clinic_id", admin.clinic_id).execute().data
    )
    if not clinic_doctors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Register a doctor before registering patients",
        )

    doctor_ids = {row["id"] for row in clinic_doctors}
    if payload.doctor_id:
        if payload.doctor_id not in doctor_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That doctor does not belong to this clinic",
            )
        assigned_doctor_id = payload.doctor_id
    elif len(doctor_ids) == 1:
        assigned_doctor_id = next(iter(doctor_ids))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This clinic has more than one doctor; choose which one to assign",
        )

    root = admin_client()

    try:
        user = root.auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
            "app_metadata": {"clinic_id": admin.clinic_id, "role": ROLE_PATIENT},
        })
    except AuthApiError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    # Through the RECEPTIONIST's own client: patients_admin_insert requires
    # is_clinic_admin() and a doctor_id within this clinic. If the insert
    # fails, roll back the orphaned auth user so a failed registration
    # never leaves a login with no patient row behind it.
    try:
        patient = admin.db.table("patients").insert({
            "clinic_id": admin.clinic_id,
            "doctor_id": assigned_doctor_id,
            "auth_id": user.user.id,
            "name": payload.name,
            "email": payload.email,
            "age": payload.age,
            "phone": payload.phone,
        }).execute().data[0]
    except Exception:
        root.auth.admin.delete_user(user.user.id)
        raise

    return {"patient_id": patient["id"], "user_id": user.user.id, "clinic_id": admin.clinic_id}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    try:
        session = anon_client().auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
    except AuthApiError:
        # Same error whether the email is unknown or the password is
        # wrong, so this endpoint cannot be used to enumerate accounts.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    metadata = session.user.app_metadata or {}
    return TokenResponse(
        access_token=session.session.access_token,
        refresh_token=session.session.refresh_token,
        role=metadata.get("role", ""),
        clinic_id=metadata.get("clinic_id", ""),
    )
