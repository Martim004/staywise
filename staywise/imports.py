"""CSV import/export helpers for the documented StayWise booking template."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from .calculations import validate_reservation


CSV_FIELDS = ["guest_name", "email", "phone", "checkin", "checkout", "guests", "nightly_rate", "status", "source", "notes"]
VALID_STATUSES = {"confirmed", "completed", "cancelled"}


def template_csv() -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerow({"guest_name":"Example Guest","email":"guest@example.test","phone":"+351 900 000 000",
                     "checkin":"2026-06-12","checkout":"2026-06-15","guests":"2","nightly_rate":"120",
                     "status":"confirmed","source":"Airbnb","notes":"Replace this sample row"})
    return out.getvalue().encode("utf-8")


def export_csv(reservations: list[dict[str, Any]]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(reservations)
    return out.getvalue().encode("utf-8-sig")


def parse_booking_csv(data: bytes, existing: list[dict[str, Any]], blocked_dates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    accepted: list[dict[str, Any]] = []
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except UnicodeDecodeError:
        return [], ["File must be encoded as UTF-8."]
    if reader.fieldnames is None:
        return [], ["CSV file has no header row."]
    missing = [name for name in CSV_FIELDS if name not in reader.fieldnames]
    if missing:
        return [], ["Missing required columns: " + ", ".join(missing)]

    context = list(existing)
    for line, raw in enumerate(reader, start=2):
        item = {field: (raw.get(field) or "").strip() for field in CSV_FIELDS}
        item["status"] = item["status"].lower() or "confirmed"
        row_errors: list[str] = []
        if item["status"] not in VALID_STATUSES:
            row_errors.append("Status must be confirmed, completed, or cancelled.")
        try:
            item["guests"] = int(item["guests"])
        except (TypeError, ValueError):
            item["guests"] = 0
        try:
            item["nightly_rate"] = float(item["nightly_rate"])
        except (TypeError, ValueError):
            item["nightly_rate"] = -1
        row_errors.extend(validate_reservation(item, context, blocked_dates))
        if row_errors:
            errors.append(f"Line {line}: " + " ".join(dict.fromkeys(row_errors)))
        else:
            accepted.append(item)
            context.append(item)
    return accepted, errors


def reservation_template_row() -> dict[str, Any]:
    return {"guest_name":"", "email":"", "phone":"", "checkin":date.today().isoformat(), "checkout":"",
            "guests":2, "nightly_rate":0.0, "status":"confirmed", "source":"Direct", "notes":""}
