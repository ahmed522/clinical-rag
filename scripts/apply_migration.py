"""Apply one reviewed SQL migration to the configured Supabase database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("migration", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.environ.get("SUPABASE_DB_URL")
    if not database_url:
        raise SystemExit("SUPABASE_DB_URL is not configured")

    migration = args.migration.resolve()
    if PROJECT_ROOT not in migration.parents:
        raise SystemExit("Migration must be inside this project")
    sql = migration.read_text(encoding="utf-8")

    parsed = urlparse(database_url)
    print(f"Target: {parsed.hostname}/{(parsed.path or '').lstrip('/')}")
    print(f"Migration: {migration.name}")

    connection = psycopg2.connect(database_url, connect_timeout=15)
    try:
        with connection.cursor() as cursor:
            cursor.execute("select current_database(), current_user")
            print(f"Connected: {cursor.fetchone()}")
            cursor.execute(
                """
                select exists (
                    select 1
                    from information_schema.columns
                    where table_schema = 'public'
                      and table_name = 'clinics'
                      and column_name = 'owner_email'
                )
                """
            )
            print(f"owner_email already present: {cursor.fetchone()[0]}")

            if not args.apply:
                connection.rollback()
                print("Check only; no changes applied.")
                return 0

            cursor.execute(sql)
        connection.commit()
        print("Migration applied successfully.")
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
