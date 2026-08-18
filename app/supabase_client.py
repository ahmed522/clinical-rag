"""
Supabase clients.

Two shapes, and the distinction between them IS the safety property of
this module — mixing them up is how RLS silently becomes decorative.

  admin_client()   Service role. Bypasses Row Level Security entirely.
                    Used ONLY for the handful of operations an ordinary
                    user cannot be authorized to do at all: minting an
                    Auth user and setting its app_metadata (clinic_id,
                    role) during registration. Never used to read or
                    write clinic data.

  client_for(jwt)   Anon key + the caller's own access token, forwarded
                    onto both Postgrest and Storage. Every tenant-scoped
                    read or write in this app goes through a client built
                    this way, so it is Postgres' RLS policies deciding
                    what the caller can see — not this code, and not a
                    WHERE clause someone could forget to write.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache
def admin_client() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


@lru_cache
def _anon_client_for_verification() -> Client:
    """
    Shared, memoized. Safe to share ONLY because verify_token() always
    passes its token explicitly to get_user(jwt) rather than relying on a
    stored session — that call is a stateless lookup, not a sign-in.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


def anon_client() -> Client:
    """
    A FRESH anon-key client — deliberately NOT memoized. sign_in_with_
    password() stores the resulting session on the client instance it is
    called on; sharing one cached client across concurrent requests would
    let one caller's session bleed into another's. Every caller of this
    function gets its own.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


def verify_token(access_token: str):
    """
    Validate a bearer token against Supabase Auth itself and return its
    user, or None if it is missing, garbage, or expired.

    Deliberately not decoded locally: Supabase signs tokens with either a
    shared secret (older projects) or rotating asymmetric keys (newer
    ones), and asking Auth avoids this service ever needing to know which,
    or holding a signing secret at all.
    """
    try:
        response = _anon_client_for_verification().auth.get_user(access_token)
    except Exception:
        return None
    return response.user if response else None


def client_for(access_token: str) -> Client:
    """A client that acts as the caller, and only as the caller."""
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    client.postgrest.auth(access_token)

    # supabase-py has no public setter for the storage client's auth header
    # (unlike postgrest.auth()), so the private attribute is set directly.
    # Note it is storage._headers, NOT storage._client.headers — storage3's
    # SyncBucketActionsMixin._request() builds each request's headers from
    # self._headers explicitly (headers.update(self._headers)), which
    # overrides anything set on the shared httpx.Client's own default
    # headers. Setting the wrong one is silent: no error, just every
    # storage call authenticating as anon regardless, and the
    # guidelines-bucket policies (which key off auth_clinic_id()) then see
    # no clinic at all and reject the insert as an RLS violation.
    client.storage._headers["Authorization"] = f"Bearer {access_token}"

    return client
