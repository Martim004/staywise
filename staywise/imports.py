"""CSV import/export helpers for the documented StayWise booking template."""

from __future__ import annotations

import csv
import io
import math
from datetime import date
from typing import Any

from .calculations import validate_reservation


CSV_FIELDS = ["guest_name", "email", "phone", "checkin", "checkout", "guests", "nightly_rate", "status", "source", "notes"]
VALID_STATUSES = {"confirmed", "completed", "cancelled"}
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 1000
MAX_FIELD_LENGTHS = {
    "guest_name": 120, "email": 254, "phone": 40, "source": 80, "notes": 2000,
}


def _safe_spreadsheet_text(value: Any) -> Any:
    """Prefix formula-like CSV text so spreadsheet apps display it literally."""
    if not isinstance(value, str):
        return value
    text = value.replace("\x00", "")
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


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
    writer.writerows({key: _safe_spreadsheet_text(value) for key, value in row.items()} for row in reservations)
    return out.getvalue().encode("utf-8-sig")


def parse_booking_csv(data: bytes, existing: list[dict[str, Any]], blocked_dates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(data, bytes) or len(data) > MAX_CSV_BYTES:
        return [], [f"CSV file must be no larger than {MAX_CSV_BYTES // (1024 * 1024)} MiB."]
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
    except (UnicodeDecodeError, csv.Error):
        return [], ["File must be a valid UTF-8 CSV."]
    if reader.fieldnames is None:
        return [], ["CSV file has no header row."]
    headers = [name.strip() if name else "" for name in reader.fieldnames]
    if len(headers) != len(set(headers)):
        return [], ["CSV header contains duplicate column names."]
    missing = [name for name in CSV_FIELDS if name not in headers]
    if missing:
        return [], ["Missing required columns: " + ", ".join(missing)]
    if any(name not in CSV_FIELDS for name in headers):
        return [], ["CSV contains unsupported columns. Download the StayWise template and use its headers."]
    reader.fieldnames = headers

    errors: list[str] = []
    accepted: list[dict[str, Any]] = []
    context = list(existing)
    try:
        for line, raw in enumerate(reader, start=2):
            if line > MAX_CSV_ROWS + 1:
                return accepted, errors + [f"CSV exceeds the {MAX_CSV_ROWS}-row import limit."]
            if None in raw:
                errors.append(f"Line {line}: row has more values than the header.")
                continue
            item = {field: (raw.get(field) or "").strip() for field in CSV_FIELDS}
            if any(len(item[field]) > limit for field, limit in MAX_FIELD_LENGTHS.items()):
                errors.append(f"Line {line}: one or more text fields exceed their allowed length.")
                continue
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
    except csv.Error:
        return accepted, errors + ["CSV file is malformed."]
    return accepted, errors


def reservation_template_row() -> dict[str, Any]:
    return {"guest_name":"", "email":"", "phone":"", "checkin":date.today().isoformat(), "checkout":"",
            "guests":2, "nightly_rate":0.0, "status":"confirmed", "source":"Direct", "notes":""}
