"""
The one deliberately public read in this API.

The patient login page lives at /clinic/{slug} and needs to show which
clinic that is before the visitor has authenticated at all — and after
they do log in, the frontend needs the slug's real clinic_id to check it
against the token's own clinic_id (a patient landing on the wrong
clinic's link should get a clear rejection, not a silent cross-tenant
mix-up).

This does NOT loosen the "anon is granted nothing" rule in
supabase/migrations/0001_schema_and_rls.sql: there is no anon-readable
RLS policy on `clinics`. This is a narrow, server-side lookup via the
service-role client, returning only {id, name, slug} — no clinical data,
nothing else on the clinics row, nothing from any other table.
"""

from fastapi import APIRouter, HTTPException, status

from app.schemas import ClinicPublicOut
from app.supabase_client import admin_client

router = APIRouter(prefix="/clinics", tags=["clinics"])


@router.get("/by-slug/{slug}", response_model=ClinicPublicOut)
def get_clinic_by_slug(slug: str):
    if slug == "__internal__":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clinic not found",
        )
    result = (
        admin_client()
        .table("clinics")
        .select("id, name, slug")
        .eq("slug", slug)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinic not found")
    return result.data[0]
