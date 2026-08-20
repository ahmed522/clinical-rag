"""
Provision an internal IT account.

IT is not clinic staff and has no self-registration path — it is minted here
with the service role, exactly like the admin/doctor/patient accounts in
app/routers/auth.py, but pointed at the reserved sentinel clinic (see
migration 0008) so app/deps.py's "clinic_id + role required" invariant holds.
IT's cross-clinic reach comes only from its own RLS policies, never this
clinic_id.

Usage:
    python -m scripts.create_it_user --email it@ourcompany.com --password '...'

Run migration 0008 first (it seeds the sentinel clinic row this references).
"""

from __future__ import annotations

import argparse
import sys

from supabase_auth.errors import AuthApiError

from app.supabase_client import admin_client

IT_SENTINEL_CLINIC_ID = "00000000-0000-0000-0000-000000000000"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an internal IT account.")
    parser.add_argument("--email", required=True, help="Login email for the IT account")
    parser.add_argument(
        "--password",
        required=True,
        help="Initial password (min 8 chars); the account can change it after first login",
    )
    args = parser.parse_args()

    if len(args.password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        return 1

    admin = admin_client()

    # The sentinel clinic must already exist (seeded by migration 0008).
    # Fail loudly rather than mint an account whose clinic_id dangles.
    sentinel = admin.table("clinics").select("id").eq("id", IT_SENTINEL_CLINIC_ID).execute().data
    if not sentinel:
        print(
            "Sentinel clinic not found. Apply migration "
            "0008_receptionist_it_roles.sql before creating IT accounts.",
            file=sys.stderr,
        )
        return 1

    try:
        user = admin.auth.admin.create_user({
            "email": args.email,
            "password": args.password,
            "email_confirm": True,
            "app_metadata": {"clinic_id": IT_SENTINEL_CLINIC_ID, "role": "it"},
        })
    except AuthApiError as exc:
        print(f"Could not create IT account: {exc}", file=sys.stderr)
        return 1

    print(f"Created IT account {args.email} (user_id={user.user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
