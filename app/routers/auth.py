"""
Registration and login, backed by Supabase Auth.

Every account's tenant lives in `app_metadata` (clinic_id, role) — never
`user_metadata`, which the user themselves can update via the Supabase
client. Putting the tenant there would let a patient re-tenant their own
account. app_metadata can only be set with the service role, which is why
admin_client() (and only it) appears in this file.

Login is also exposed here as a thin pass-through to Supabase Auth. A
production frontend can call supabase-js directly for this — nothing here
does anything the client SDK couldn't — but keeping the endpoint gives
scripts, tests, and any non-browser client one consistent way in.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from supabase_auth.errors import AuthApiError

from app.deps import ROLE_CLINIC_ADMIN, ROLE_PATIENT, CurrentUser, require_clinic_admin
from app.schemas import ClinicRegister, LoginRequest, PatientRegister, TokenResponse
from app.supabase_client import admin_client, anon_client

router = APIRouter(prefix="/auth", tags=["auth"])


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
    token. It returns an admin `access_token` — authorize with it to
    upload documents and register patients.
    """
    admin = admin_client()

    clinic = admin.table("clinics").insert(
        {"name": payload.clinic_name, "specialty": payload.specialty}
    ).execute().data[0]

    try:
        user = admin.auth.admin.create_user({
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
        role=ROLE_CLINIC_ADMIN,
        clinic_id=clinic["id"],
    )


@router.post(
    "/register-patient",
    status_code=status.HTTP_201_CREATED,
    summary="Register a patient (clinic admin only)",
    responses={
        401: {"description": "Missing or invalid token — authorize as a clinic admin first"},
        403: {"description": "Authenticated, but not a clinic admin"},
        409: {"description": "Email already registered"},
    },
)
def register_patient(payload: PatientRegister, admin: CurrentUser = Depends(require_clinic_admin)):
    """
    Register a patient under the caller's clinic.

    **Requires a clinic admin token.** Register a clinic first via
    `/auth/register-clinic`, then authorize with the `access_token` it
    returns.

    A patient must belong to a clinic, and that clinic is read from the
    admin's own verified token rather than the request body — otherwise
    anyone could create a patient inside someone else's clinic.
    """
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

    # Insert through the ADMIN's own client, not the service role. The
    # patients_admin_write RLS policy already allows a clinic admin to
    # write patient rows for their own clinic_id — routing through it
    # instead of admin_client() means this insert is subject to the same
    # policy every other write in the app is, not a special case.
    patient = admin.db.table("patients").insert({
        "clinic_id": admin.clinic_id,
        "auth_id": user.user.id,
        "name": payload.name,
        "age": payload.age,
        "phone": payload.phone,
    }).execute().data[0]

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
        role=metadata.get("role", ""),
        clinic_id=metadata.get("clinic_id", ""),
    )
