import json
import logging
import os

import psycopg
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

# Bundled preset shipped in the repo — seeded into the table once so a fresh
# database starts with the same default mapping the app has always shipped.
_DEFAULT_MAPPING_NAME = "electra_default"
_DEFAULT_MAPPING_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "mappings", f"{_DEFAULT_MAPPING_NAME}.json"
)

# Set once per process (e.g. once per warm serverless container) so the
# schema/seed check doesn't run on every single request.
_schema_ready = False


def _connect():
    """
    Opens a fresh connection per call — the right pattern for serverless,
    where the process itself is short-lived and DATABASE_URL is expected to
    point at a pooled (e.g. PgBouncer) connection string. Used as a context
    manager, the connection commits and closes automatically on exit.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set — saved-mapping storage is not configured. "
            "Set it to your Postgres connection string (see the Vercel Postgres/Neon "
            "integration's connection details)."
        )
    conn = psycopg.connect(database_url)
    global _schema_ready
    if not _schema_ready:
        _ensure_schema(conn)
        _schema_ready = True
    return conn


def _ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS mappings (
                name TEXT PRIMARY KEY,
                config JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()
    _seed_default_mapping(conn)


def _seed_default_mapping(conn):
    if not os.path.isfile(_DEFAULT_MAPPING_PATH):
        return
    with open(_DEFAULT_MAPPING_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO mappings (name, config) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
            (_DEFAULT_MAPPING_NAME, Jsonb(config)),
        )
    conn.commit()
    logger.info(
        "MAPPING STORE: ensured bundled default mapping '%s' exists (no-op if already present)",
        _DEFAULT_MAPPING_NAME,
    )


def list_mapping_names():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM mappings ORDER BY name")
            return [row[0] for row in cur.fetchall()]


def get_mapping(name):
    """Returns the mapping's config dict, or None if no mapping exists under that name."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT config FROM mappings WHERE name = %s", (name,))
            row = cur.fetchone()
            return row[0] if row else None


def save_mapping(name, config):
    """Inserts or overwrites (upsert) the mapping under the given name."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mappings (name, config, updated_at) VALUES (%s, %s, now())
                ON CONFLICT (name) DO UPDATE SET config = EXCLUDED.config, updated_at = now()
                """,
                (name, Jsonb(config)),
            )


def delete_mapping(name):
    """Deletes a mapping by name. Returns True if a row was deleted, False if it didn't exist."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mappings WHERE name = %s", (name,))
            return cur.rowcount > 0


def delete_all_mappings(except_name):
    """Deletes every saved mapping except the given (protected) name."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mappings WHERE name != %s", (except_name,))
