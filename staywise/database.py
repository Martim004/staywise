"""SQLite persistence and fictional demo data for StayWise."""

from __future__ import annotations

import os
import sqlite3
import calendar
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
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, area TEXT NOT NULL DEFAULT '', bedrooms INTEGER NOT NULL DEFAULT 2,
            capacity INTEGER NOT NULL DEFAULT 4, latitude REAL NOT NULL DEFAULT 38.719,
            longitude REAL NOT NULL DEFAULT -9.165, airbnb_url TEXT NOT NULL DEFAULT '',
            booking_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            checkin TEXT NOT NULL, checkout TEXT NOT NULL, guests INTEGER NOT NULL,
            nightly_rate REAL NOT NULL, status TEXT NOT NULL DEFAULT 'confirmed',
            source TEXT NOT NULL DEFAULT 'Direct', notes TEXT NOT NULL DEFAULT '',
            property_id INTEGER REFERENCES properties(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS blocked_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
            property_id INTEGER REFERENCES properties(id)
        );
        CREATE TABLE IF NOT EXISTS comparables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, area TEXT NOT NULL DEFAULT '', bedrooms INTEGER NOT NULL DEFAULT 1,
            capacity INTEGER NOT NULL DEFAULT 1, distance_km REAL NOT NULL DEFAULT 0,
            nightly_rate REAL NOT NULL, observed_date TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', selected INTEGER NOT NULL DEFAULT 1,
            latitude REAL, longitude REAL, property_id INTEGER REFERENCES properties(id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_assumptions (
            month INTEGER PRIMARY KEY, occupancy_percent REAL NOT NULL, nightly_rate REAL NOT NULL
        );
        """)
        reservation_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reservations)")}
        if "property_id" not in reservation_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN property_id INTEGER REFERENCES properties(id)")
        block_columns = {row["name"] for row in conn.execute("PRAGMA table_info(blocked_dates)")}
        if "property_id" not in block_columns:
            conn.execute("ALTER TABLE blocked_dates ADD COLUMN property_id INTEGER REFERENCES properties(id)")
        comp_columns = {row["name"] for row in conn.execute("PRAGMA table_info(comparables)")}
        if "latitude" not in comp_columns:
            conn.execute("ALTER TABLE comparables ADD COLUMN latitude REAL")
        if "longitude" not in comp_columns:
            conn.execute("ALTER TABLE comparables ADD COLUMN longitude REAL")
        if "property_id" not in comp_columns:
            conn.execute("ALTER TABLE comparables ADD COLUMN property_id INTEGER REFERENCES properties(id)")
        legacy = {row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM settings")}
        first = conn.execute("SELECT id FROM properties ORDER BY id LIMIT 1").fetchone()
        if first is None:
            cursor = conn.execute("""INSERT INTO properties(name,area,bedrooms,capacity,latitude,longitude)
                VALUES(?,?,?,?,?,?)""", (
                legacy.get("property_name", DEFAULTS["property_name"]),
                legacy.get("property_area", DEFAULTS["property_area"]),
                int(legacy.get("bedrooms", DEFAULTS["bedrooms"])),
                int(legacy.get("capacity", DEFAULTS["capacity"])),
                float(legacy.get("latitude", DEFAULTS["latitude"])),
                float(legacy.get("longitude", DEFAULTS["longitude"])),
            ))
            first_id = int(cursor.lastrowid)
        else:
            first_id = int(first["id"])
        conn.execute("UPDATE reservations SET property_id=? WHERE property_id IS NULL", (first_id,))
        conn.execute("UPDATE blocked_dates SET property_id=? WHERE property_id IS NULL", (first_id,))
        conn.execute("UPDATE comparables SET property_id=? WHERE property_id IS NULL", (first_id,))


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_properties() -> list[dict[str, Any]]:
    return _rows("SELECT * FROM properties ORDER BY id")


def add_property(item: dict[str, Any]) -> int:
    with connect() as conn:
        cur = conn.execute("""INSERT INTO properties
            (name,area,bedrooms,capacity,latitude,longitude,airbnb_url,booking_url)
            VALUES (:name,:area,:bedrooms,:capacity,:latitude,:longitude,:airbnb_url,:booking_url)""", item)
        return int(cur.lastrowid)


def update_property(property_id: int, item: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute("""UPDATE properties SET name=:name,area=:area,bedrooms=:bedrooms,capacity=:capacity,
            latitude=:latitude,longitude=:longitude,airbnb_url=:airbnb_url,booking_url=:booking_url WHERE id=:id""",
            {**item, "id": property_id})


def get_reservations(property_id: int | None = None) -> list[dict[str, Any]]:
    if property_id is None:
        return _rows("SELECT * FROM reservations ORDER BY checkin, id")
    return _rows("SELECT * FROM reservations WHERE property_id=? ORDER BY checkin, id", (property_id,))


def add_reservation(item: dict[str, Any]) -> int:
    property_id = item.get("property_id") or get_properties()[0]["id"]
    with connect() as conn:
        cur = conn.execute("""INSERT INTO reservations
            (guest_name,email,phone,checkin,checkout,guests,nightly_rate,status,source,notes,property_id)
            VALUES (:guest_name,:email,:phone,:checkin,:checkout,:guests,:nightly_rate,:status,:source,:notes,:property_id)""",
            {**item, "property_id": property_id})
        return int(cur.lastrowid)


def delete_reservation(reservation_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM reservations WHERE id=?", (reservation_id,))


def add_blocked_dates(start_date: str, end_date: str, reason: str = "", property_id: int | None = None) -> int:
    fallback = property_id or get_properties()[0]["id"]
    with connect() as conn:
        cur = conn.execute("INSERT INTO blocked_dates(start_date,end_date,reason,property_id) VALUES(?,?,?,?)", (start_date,end_date,reason,fallback))
        return int(cur.lastrowid)


def get_blocked_dates(property_id: int | None = None) -> list[dict[str, Any]]:
    if property_id is None:
        return _rows("SELECT * FROM blocked_dates ORDER BY start_date")
    return _rows("SELECT * FROM blocked_dates WHERE property_id=? ORDER BY start_date", (property_id,))


def delete_blocked_dates(block_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM blocked_dates WHERE id=?", (block_id,))


def add_comparable(item: dict[str, Any]) -> int:
    values = {"latitude": None, "longitude": None, "property_id": get_properties()[0]["id"], **item}
    with connect() as conn:
        cur = conn.execute("""INSERT INTO comparables
            (name,area,bedrooms,capacity,distance_km,nightly_rate,observed_date,url,notes,selected,latitude,longitude,property_id)
            VALUES (:name,:area,:bedrooms,:capacity,:distance_km,:nightly_rate,:observed_date,:url,:notes,:selected,:latitude,:longitude,:property_id)""", values)
        return int(cur.lastrowid)


def get_comparables(property_id: int | None = None) -> list[dict[str, Any]]:
    if property_id is None:
        return _rows("SELECT * FROM comparables ORDER BY observed_date DESC, id")
    return _rows("SELECT * FROM comparables WHERE property_id=? ORDER BY observed_date DESC, id", (property_id,))


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
    today = date.today()
    current_year = today.year
    properties = get_properties()
    demo_property = {"name":"Campo de Ourique T2 (demo)","area":"Campo de Ourique, Lisbon","bedrooms":2,"capacity":4,
                    "latitude":38.719,"longitude":-9.165,"airbnb_url":"","booking_url":""}
    update_property(properties[0]["id"], demo_property)
    with connect() as conn:
        reservation_count = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        comparable_count = conn.execute("SELECT COUNT(*) FROM comparables").fetchone()[0]
    if not reservation_count:
        if not comparable_count:
            for item in [
                {"name":"Sample apartment near the river","area":"Central Lisbon","bedrooms":2,"capacity":4,"distance_km":0.4,"nightly_rate":145,"observed_date":today.isoformat(),"url":"https://example.test/listing-a","notes":"Fictional comparison listing","selected":1},
                {"name":"Demo flat with balcony","area":"Central Lisbon","bedrooms":2,"capacity":4,"distance_km":0.7,"nightly_rate":159,"observed_date":today.isoformat(),"url":"https://example.test/listing-b","notes":"Fictional comparison listing","selected":1},
                {"name":"Example studio","area":"Central Lisbon","bedrooms":1,"capacity":2,"distance_km":0.2,"nightly_rate":102,"observed_date":today.isoformat(),"url":"https://example.test/listing-c","notes":"Fictional comparison listing","selected":1},
            ]:
                add_comparable(item)
        blocked_start = today + timedelta(days=70)
        if not get_blocked_dates():
            add_blocked_dates(blocked_start.isoformat(), (blocked_start + timedelta(days=4)).isoformat(), "Owner stay (sample)")
        save_settings({"property_name":demo_property["name"],"property_area":demo_property["area"],"bedrooms":"2","capacity":"4",
                       "latitude":"38.719","longitude":"-9.165"})
    # Fill the fictional calendar to a 60% target, preserving any sample records already present.
    bookings = get_reservations(properties[0]["id"])
    guest_names = ["Alex Example", "Jamie Sample", "Taylor Demo", "Morgan Fiction", "Riley Sample"]
    for month in range(1, 13):
        days = __import__("calendar").monthrange(current_year, month)[1]
        target = round(days * 0.60)
        start_month = date(current_year, month, 1)
        month_end = date(current_year + 1, 1, 1) if month == 12 else date(current_year, month + 1, 1)
        def occupied_nights() -> set[date]:
            occupied: set[date] = set()
            for booking in bookings:
                if booking["status"] not in {"confirmed", "completed"}:
                    continue
                start, end = date.fromisoformat(booking["checkin"]), date.fromisoformat(booking["checkout"])
                cursor = max(start, start_month)
                while cursor < min(end, month_end):
                    occupied.add(cursor)
                    cursor += timedelta(days=1)
            return occupied
        stay_number = 0
        for offset in range(0, days, 5):
            occupied = occupied_nights()
            needed = target - len(occupied)
            if needed <= 0:
                break
            start = start_month + timedelta(days=offset)
            duration = min(3, needed, (month_end - start).days)
            end = start + timedelta(days=duration)
            if any(start <= night < end for night in occupied):
                continue
            stay_number += 1
            item = {"guest_name":guest_names[(month + stay_number) % len(guest_names)],"email":"guest@example.test",
                    "phone":"+351 900 000 000","checkin":start.isoformat(),"checkout":end.isoformat(),"guests":2,
                    "nightly_rate":(150 if month in [6,7,8,9] else 112),
                    "status":"completed" if end <= today else "confirmed","source":"Airbnb (sample)",
                    "notes":"Fictional demo guest; seeded for 60% sample occupancy","property_id":properties[0]["id"]}
            add_reservation(item)
            bookings.append(item)
    save_monthly_assumptions({month: {"occupancy_percent": min(85, 42 + (month in [6,7,8,9]) * 22),
                                      "nightly_rate": (178 if month in [6,7,8,9] else 118 if month in [4,5,10] else 96)} for month in range(1,13)})
