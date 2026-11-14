"""PostgreSQL storage for Inside Airbnb listing snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import pandas as pd


SUPABASE_LIMIT_BYTES = 500 * 1024 * 1024
RETENTION_NOTE = "Only the latest Lisbon listing snapshot is retained."


def _secret(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value.strip()
    try:
        import streamlit as st
        value = st.secrets.get(name, "")
        return str(value).strip() if value else ""
    except Exception:
        return ""


def database_urls() -> dict[str, str]:
    """Read provider URLs from environment variables or Streamlit secrets."""
    return {
        "supabase": _secret("SUPABASE_DATABASE_URL"),
        "layerbase": _secret("LAYERBASE_DATABASE_URL"),
    }


def postgres_configured() -> bool:
    return any(database_urls().values())


def _connect(url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install the psycopg[binary] dependency to use PostgreSQL storage.") from exc
    return psycopg.connect(url, connect_timeout=12, sslmode="require")


def _ensure_schema(url: str) -> None:
    with _connect(url) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS staywise_inside_airbnb_snapshots (
                id BIGSERIAL PRIMARY KEY,
                city TEXT NOT NULL,
                source_url TEXT NOT NULL,
                downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                source_sha256 TEXT NOT NULL,
                listing_count INTEGER NOT NULL,
                payload_bytes BIGINT NOT NULL,
                database_bytes BIGINT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS staywise_inside_airbnb_listings (
                snapshot_id BIGINT NOT NULL REFERENCES staywise_inside_airbnb_snapshots(id) ON DELETE CASCADE,
                listing_id TEXT NOT NULL,
                payload JSONB NOT NULL,
                PRIMARY KEY (snapshot_id, listing_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS staywise_airbnb_listing_snapshot_idx
            ON staywise_inside_airbnb_listings(snapshot_id)
        """)


def _table_bytes(url: str) -> tuple[int, int]:
    _ensure_schema(url)
    with _connect(url) as conn:
        database_size = int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])
        table_size = int(conn.execute("""
            SELECT COALESCE(pg_total_relation_size('staywise_inside_airbnb_listings'),0)
                 + COALESCE(pg_total_relation_size('staywise_inside_airbnb_snapshots'),0)
        """).fetchone()[0])
    return database_size, table_size


def _jsonable_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        if value is None or pd.isna(value):
            cleaned[str(key)] = None
        elif hasattr(value, "item"):
            cleaned[str(key)] = value.item()
        else:
            cleaned[str(key)] = value
    return cleaned


def _frame_payload(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], int, str]:
    records = [_jsonable_record(record) for record in frame.to_dict(orient="records")]
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return records, len(encoded), hashlib.sha256(encoded).hexdigest()


def _provider_for(projected_payload_bytes: int) -> tuple[str, str, int]:
    urls = database_urls()
    supabase_url, layerbase_url = urls["supabase"], urls["layerbase"]
    if supabase_url:
        database_size, listing_tables_size = _table_bytes(supabase_url)
        projected = database_size - listing_tables_size + int(projected_payload_bytes * 1.5) + 8_000_000
        if projected < SUPABASE_LIMIT_BYTES:
            return "Supabase", supabase_url, projected
    else:
        projected = int(projected_payload_bytes * 1.5) + 8_000_000

    if projected_bytes >= SUPABASE_LIMIT_BYTES and layerbase_url:
        return "Layerbase", layerbase_url, projected
    if not supabase_url:
        raise RuntimeError(
            "This snapshot is below the 500 MiB threshold, so StayWise requires SUPABASE_DATABASE_URL. "
            "Add the Supabase connection URL to Streamlit Secrets."
        )
    raise RuntimeError(
        f"The estimated Supabase database size is {projected / (1024**2):.1f} MiB, over the 500 MiB free-tier limit. "
        "Add LAYERBASE_DATABASE_URL to Streamlit Secrets to store this snapshot on Layerbase."
    )


def save_latest_snapshot(frame: pd.DataFrame, source_url: str, city: str = "Lisbon") -> dict[str, Any]:
    """Replace the stored city snapshot and route it by projected PostgreSQL size."""
    records, payload_bytes, digest = _frame_payload(frame)
    provider, url, projected_bytes = _provider_for(payload_bytes)
    _ensure_schema(url)
    from psycopg.types.json import Jsonb

    with _connect(url) as conn:
        conn.execute("DELETE FROM staywise_inside_airbnb_snapshots WHERE city=%s", (city,))
        snapshot_id = conn.execute("""
            INSERT INTO staywise_inside_airbnb_snapshots
                (city, source_url, source_sha256, listing_count, payload_bytes)
            VALUES (%s,%s,%s,%s,%s)
            RETURNING id
        """, (city, source_url, digest, len(records), payload_bytes)).fetchone()[0]
        with conn.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO staywise_inside_airbnb_listings(snapshot_id, listing_id, payload)
                VALUES (%s,%s,%s)
            """, [
                (snapshot_id, str(record.get("id", "")), Jsonb(record, dumps=lambda value: json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), default=str)))
                for record in records if record.get("id") not in (None, "")
            ])
        database_bytes = int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])
        conn.execute("UPDATE staywise_inside_airbnb_snapshots SET database_bytes=%s WHERE id=%s",
                     (database_bytes, snapshot_id))
    return {
        "provider": provider,
        "snapshot_id": int(snapshot_id),
        "listing_count": len(records),
        "payload_bytes": payload_bytes,
        "database_bytes": database_bytes,
        "projected_bytes": projected_bytes,
        "source_sha256": digest,
    }


def _latest_on_url(url: str) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    _ensure_schema(url)
    with _connect(url) as conn:
        meta = conn.execute("""
            SELECT id, city, source_url, downloaded_at, source_sha256, listing_count,
                   payload_bytes, database_bytes
            FROM staywise_inside_airbnb_snapshots ORDER BY downloaded_at DESC LIMIT 1
        """).fetchone()
        if not meta:
            return None
        rows = conn.execute("""
            SELECT payload FROM staywise_inside_airbnb_listings
            WHERE snapshot_id=%s ORDER BY listing_id
        """, (meta[0],)).fetchall()
    frame = pd.DataFrame([row[0] for row in rows])
    metadata = {
        "snapshot_id": int(meta[0]), "city": meta[1], "source_url": meta[2],
        "downloaded_at": meta[3], "source_sha256": meta[4], "listing_count": int(meta[5]),
        "payload_bytes": int(meta[6]), "database_bytes": int(meta[7]) if meta[7] is not None else None,
    }
    return frame, metadata


def load_latest_snapshot() -> tuple[pd.DataFrame, dict[str, Any]] | None:
    """Read the newest saved snapshot from the configured provider(s)."""
    candidates = []
    errors = []
    for provider, url in database_urls().items():
        if not url:
            continue
        try:
            result = _latest_on_url(url)
            if result:
                frame, metadata = result
                metadata["provider"] = provider.capitalize()
                candidates.append((metadata["downloaded_at"], frame, metadata))
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    if candidates:
        _, frame, metadata = max(candidates, key=lambda item: item[0])
        return frame, metadata
    if errors:
        raise RuntimeError("Could not read the configured PostgreSQL snapshot. " + " | ".join(errors))
    return None
