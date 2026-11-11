"""SQLite persistence and fictional demo data for StayWise."""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def is_demo_mode() -> bool:
    configured = os.getenv("STAYWISE_DEMO", "").strip().lower()
    if configured in {"1", "true", "yes"}:
        return True
    try:
        import streamlit as st
        configured = str(st.secrets.get("STAYWISE_DEMO", "")).strip().lower()
    except Exception:
        configured = ""
    return configured in {"1", "true", "yes"}


def database_path() -> Path:
    if is_demo_mode():
        return Path(os.getenv("STAYWISE_DB_PATH", "/tmp/staywise-demo.sqlite3"))
    return Path(os.getenv("STAYWISE_DB_PATH", "data/staywise.sqlite3"))


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            checkin TEXT NOT NULL, checkout TEXT NOT NULL, guests INTEGER NOT NULL,
            nightly_rate REAL NOT NULL, status TEXT NOT NULL DEFAULT 'confirmed',
            source TEXT NOT NULL DEFAULT 'Direct', notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS blocked_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, reason TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS comparables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, area TEXT NOT NULL DEFAULT '', bedrooms INTEGER NOT NULL DEFAULT 1,
            capacity INTEGER NOT NULL DEFAULT 1, distance_km REAL NOT NULL DEFAULT 0,
            nightly_rate REAL NOT NULL, observed_date TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', selected INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_assumptions (
            month INTEGER PRIMARY KEY, occupancy_percent REAL NOT NULL, nightly_rate REAL NOT NULL
        );
        """)


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_reservations() -> list[dict[str, Any]]:
    return _rows("SELECT * FROM reservations ORDER BY checkin, id")


def add_reservation(item: dict[str, Any]) -> int:
    with connect() as conn:
        cur = conn.execute("""INSERT INTO reservations
            (guest_name,email,phone,checkin,checkout,guests,nightly_rate,status,source,notes)
            VALUES (:guest_name,:email,:phone,:checkin,:checkout,:guests,:nightly_rate,:status,:source,:notes)""", item)
        return int(cur.lastrowid)


def delete_reservation(reservation_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM reservations WHERE id=?", (reservation_id,))


def add_blocked_dates(start_date: str, end_date: str, reason: str = "") -> int:
    with connect() as conn:
        cur = conn.execute("INSERT INTO blocked_dates(start_date,end_date,reason) VALUES(?,?,?)", (start_date,end_date,reason))
        return int(cur.lastrowid)


def get_blocked_dates() -> list[dict[str, Any]]:
    return _rows("SELECT * FROM blocked_dates ORDER BY start_date")


def delete_blocked_dates(block_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM blocked_dates WHERE id=?", (block_id,))


def add_comparable(item: dict[str, Any]) -> int:
    with connect() as conn:
        cur = conn.execute("""INSERT INTO comparables
            (name,area,bedrooms,capacity,distance_km,nightly_rate,observed_date,url,notes,selected)
            VALUES (:name,:area,:bedrooms,:capacity,:distance_km,:nightly_rate,:observed_date,:url,:notes,:selected)""", item)
        return int(cur.lastrowid)


def get_comparables() -> list[dict[str, Any]]:
    return _rows("SELECT * FROM comparables ORDER BY observed_date DESC, id")


def set_comparable_selected(comparable_id: int, selected: bool) -> None:
    with connect() as conn:
        conn.execute("UPDATE comparables SET selected=? WHERE id=?", (int(selected), comparable_id))


def delete_comparable(comparable_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM comparables WHERE id=?", (comparable_id,))


DEFAULTS = {
    "property_name": "My Rental", "property_area": "", "bedrooms": "2", "capacity": "4",
    "latitude": "38.719", "longitude": "-9.165",
}


def get_settings() -> dict[str, str]:
    settings = DEFAULTS.copy()
    for row in _rows("SELECT key,value FROM settings"):
        settings[row["key"]] = row["value"]
    return settings


def save_settings(values: dict[str, Any]) -> None:
    with connect() as conn:
        conn.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         [(key, str(value)) for key, value in values.items()])


def get_monthly_assumptions() -> dict[int, dict[str, float]]:
    rows = _rows("SELECT month,occupancy_percent,nightly_rate FROM monthly_assumptions")
    if rows:
        return {int(r["month"]): {"occupancy_percent": float(r["occupancy_percent"]), "nightly_rate": float(r["nightly_rate"])} for r in rows}
    return {month: {"occupancy_percent": 55.0, "nightly_rate": 110.0} for month in range(1, 13)}


def save_monthly_assumptions(values: dict[int, dict[str, float]]) -> None:
    with connect() as conn:
        conn.executemany("""INSERT INTO monthly_assumptions(month,occupancy_percent,nightly_rate) VALUES(?,?,?)
            ON CONFLICT(month) DO UPDATE SET occupancy_percent=excluded.occupancy_percent,nightly_rate=excluded.nightly_rate""",
                         [(month, float(v["occupancy_percent"]), float(v["nightly_rate"])) for month,v in values.items()])


def seed_demo_data() -> None:
    with connect() as conn:
        reservation_count = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
    if reservation_count:
        return
    today = date.today()
    current_year = today.year
    future_checkin = today + timedelta(days=35)
    reservations = [
        {"guest_name":"Alex Example","email":"alex@example.test","phone":"+351 900 000 101","checkin":f"{current_year}-02-14","checkout":f"{current_year}-02-18","guests":2,"nightly_rate":104,"status":"completed","source":"Airbnb (sample)","notes":"Fictional demo guest"},
        {"guest_name":"Jamie Sample","email":"jamie@example.test","phone":"+351 900 000 202","checkin":f"{current_year}-05-09","checkout":f"{current_year}-05-14","guests":3,"nightly_rate":128,"status":"completed","source":"Booking.com (sample)","notes":"Fictional demo guest"},
        {"guest_name":"Taylor Demo","email":"taylor@example.test","phone":"+351 900 000 303","checkin":future_checkin.isoformat(),"checkout":(future_checkin + timedelta(days=7)).isoformat(),"guests":4,"nightly_rate":176,"status":"confirmed","source":"Direct","notes":"Fictional demo guest"},
    ]
    for item in reservations:
        add_reservation(item)
    for item in [
        {"name":"Sample apartment near the river","area":"Central district","bedrooms":2,"capacity":4,"distance_km":0.4,"nightly_rate":145,"observed_date":today.isoformat(),"url":"https://example.test/listing-a","notes":"Fictional comparison listing","selected":1},
        {"name":"Demo flat with balcony","area":"Central district","bedrooms":2,"capacity":4,"distance_km":0.7,"nightly_rate":159,"observed_date":today.isoformat(),"url":"https://example.test/listing-b","notes":"Fictional comparison listing","selected":1},
        {"name":"Example studio","area":"Central district","bedrooms":1,"capacity":2,"distance_km":0.2,"nightly_rate":102,"observed_date":today.isoformat(),"url":"https://example.test/listing-c","notes":"Fictional comparison listing","selected":1},
    ]:
        add_comparable(item)
    blocked_start = today + timedelta(days=70)
    add_blocked_dates(blocked_start.isoformat(), (blocked_start + timedelta(days=4)).isoformat(), "Owner stay (sample)")
    save_settings({"property_name":"Casa do Miradouro (sample)","property_area":"Central district","bedrooms":"2","capacity":"4",
                   "platform_fee_percent":"14","monthly_operating_cost":"250"})
    save_monthly_assumptions({month: {"occupancy_percent": min(85, 42 + (month in [6,7,8,9]) * 22),
                                      "nightly_rate": (178 if month in [6,7,8,9] else 118 if month in [4,5,10] else 96)} for month in range(1,13)})
