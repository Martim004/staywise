"""Validate StayWise property-import workbooks before any private records are saved."""

from __future__ import annotations

from datetime import date, datetime, time
from io import BytesIO
import math
import re
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024
MAX_ROWS = 1000

HEADERS = {
    "Property": ["property_name", "city", "neighborhood", "bedrooms", "guest_capacity", "latitude", "longitude", "airbnb_url", "booking_url", "check_in_time", "check_out_time"],
    "Bookings": ["guest_name", "email", "phone", "check_in", "check_out", "guests", "nightly_rate_eur", "booking_source", "status", "notes"],
    "Blocked Dates": ["start_date", "end_date", "reason"],
    "Comparables": ["listing_name", "area", "bedrooms", "guest_capacity", "distance_km", "latitude", "longitude", "nightly_rate_eur", "observed_date", "listing_url", "notes", "selected"],
}


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value, label: str, row: int, errors: list[str], *, required=False, max_length=2000) -> str:
    if _blank(value):
        if required:
            errors.append(f"{label} row {row}: {label.replace('_', ' ')} is required.")
        return ""
    result = str(value).strip()
    if len(result) > max_length:
        errors.append(f"{label} row {row}: text must be {max_length} characters or fewer.")
    return result


def _number(value, label: str, row: int, errors: list[str], *, minimum: float, maximum: float, integer=False):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        errors.append(f"{label} row {row}: enter a valid number.")
        return None
    if not math.isfinite(number) or number < minimum or number > maximum or (integer and not number.is_integer()):
        errors.append(f"{label} row {row}: value must be between {minimum:g} and {maximum:g}{' and a whole number' if integer else ''}.")
        return None
    return int(number) if integer else number


def _date(value, label: str, row: int, errors: list[str]) -> str | None:
    try:
        if isinstance(value, datetime):
            result = value.date()
        elif isinstance(value, date):
            result = value
        elif isinstance(value, str):
            result = date.fromisoformat(value.strip())
        else:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        errors.append(f"{label} row {row}: use an Excel date or YYYY-MM-DD.")
        return None
    return result.isoformat()


def _clock(value, label: str, row: int, errors: list[str]) -> str | None:
    if _blank(value):
        return None
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0).isoformat(timespec="minutes")
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    try:
        return time.fromisoformat(str(value).strip()).replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except (TypeError, ValueError):
        errors.append(f"Property row {row}: {label.replace('_', ' ')} must use HH:MM.")
        return None


def _url(value, label: str, row: int, errors: list[str], allowed_hosts: tuple[str, ...]) -> str:
    result = _text(value, label, row, errors, max_length=2000)
    if not result:
        return ""
    parsed = urlparse(result)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == domain or host.endswith("." + domain) for domain in allowed_hosts):
        errors.append(f"{label} row {row}: use an HTTPS link from the matching platform.")
        return ""
    return result


def _sheet_rows(workbook, sheet_name: str, errors: list[str]) -> list[tuple[int, dict]]:
    if sheet_name not in workbook.sheetnames:
        if sheet_name == "Property":
            errors.append("Property sheet is missing.")
        return []
    sheet = workbook[sheet_name]
    if sheet.max_row > MAX_ROWS + 4 or sheet.max_column > len(HEADERS[sheet_name]):
        errors.append(f"{sheet_name}: the sheet is larger than the supported template size.")
        return []
    expected = HEADERS[sheet_name]
    actual = [str(sheet.cell(row=4, column=col).value or "").strip() for col in range(1, len(expected) + 1)]
    if actual != expected:
        errors.append(f"{sheet_name}: use the downloaded template headers without renaming or moving columns.")
        return []
    rows = []
    for row_no in range(5, sheet.max_row + 1):
        cells = [sheet.cell(row=row_no, column=col) for col in range(1, len(expected) + 1)]
        if any(cell.data_type == "f" for cell in cells):
            errors.append(f"{sheet_name} row {row_no}: formulas are not accepted; paste values into the template.")
            continue
        values = {key: cell.value for key, cell in zip(expected, cells)}
        if all(_blank(value) for value in values.values()):
            continue
        rows.append((row_no, values))
    return rows


def parse_property_import_workbook(data: bytes) -> tuple[dict | None, list[str]]:
    """Return one property and optional related records, or errors without saving anything."""
    errors: list[str] = []
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_UPLOAD_BYTES:
        return None, ["Upload an .xlsx workbook smaller than 5 MB."]
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                return None, ["The workbook expands beyond the 30 MB safety limit."]
        workbook = load_workbook(BytesIO(data), data_only=False, read_only=True)
    except (BadZipFile, OSError, ValueError, KeyError):
        return None, ["This file is not a readable .xlsx workbook. Download a fresh StayWise template and try again."]

    allowed_sheets = {"Start Here", *HEADERS.keys()}
    if set(workbook.sheetnames) - allowed_sheets:
        errors.append("The workbook contains unexpected sheets. Upload the unmodified StayWise template.")
    property_rows = _sheet_rows(workbook, "Property", errors)
    booking_rows = _sheet_rows(workbook, "Bookings", errors)
    block_rows = _sheet_rows(workbook, "Blocked Dates", errors)
    comparable_rows = _sheet_rows(workbook, "Comparables", errors)
    if len(property_rows) != 1:
        errors.append("Property sheet: enter exactly one property row.")
    if len(booking_rows) > 500:
        errors.append("Bookings sheet: import up to 500 reservations at a time.")
    if len(block_rows) > 200:
        errors.append("Blocked Dates sheet: import up to 200 date ranges at a time.")
    if len(comparable_rows) > 500:
        errors.append("Comparables sheet: import up to 500 listings at a time.")
    if len(property_rows) != 1:
        return None, errors

    property_row, prop = property_rows[0]
    property_data = {
        "name": _text(prop["property_name"], "Property", property_row, errors, required=True, max_length=120),
        "city": _text(prop["city"], "Property", property_row, errors, required=True, max_length=20).title(),
        "neighborhood": _text(prop["neighborhood"], "Property", property_row, errors, required=True, max_length=180),
        "bedrooms": _number(prop["bedrooms"], "Property", property_row, errors, minimum=0, maximum=30, integer=True),
        "capacity": _number(prop["guest_capacity"], "Property", property_row, errors, minimum=1, maximum=100, integer=True),
        "latitude": _number(prop["latitude"], "Property", property_row, errors, minimum=-90, maximum=90),
        "longitude": _number(prop["longitude"], "Property", property_row, errors, minimum=-180, maximum=180),
        "airbnb_url": _url(prop["airbnb_url"], "Property", property_row, errors, ("airbnb.com", "airbnb.pt")),
        "booking_url": _url(prop["booking_url"], "Property", property_row, errors, ("booking.com",)),
        "check_in_time": _clock(prop["check_in_time"], "check_in_time", property_row, errors),
        "check_out_time": _clock(prop["check_out_time"], "check_out_time", property_row, errors),
    }
    if property_data["city"] not in {"Lisbon", "Porto"}:
        errors.append(f"Property row {property_row}: city must be Lisbon or Porto.")

    bookings = []
    for row_no, raw in booking_rows:
        source = _text(raw["booking_source"], "Bookings", row_no, errors, required=True, max_length=40)
        status = _text(raw["status"], "Bookings", row_no, errors, required=True, max_length=20).lower()
        item = {
            "guest_name": _text(raw["guest_name"], "Bookings", row_no, errors, required=True, max_length=120),
            "email": _text(raw["email"], "Bookings", row_no, errors, max_length=254),
            "phone": _text(raw["phone"], "Bookings", row_no, errors, max_length=40),
            "checkin": _date(raw["check_in"], "Bookings", row_no, errors),
            "checkout": _date(raw["check_out"], "Bookings", row_no, errors),
            "guests": _number(raw["guests"], "Bookings", row_no, errors, minimum=1, maximum=100, integer=True),
            "nightly_rate": _number(raw["nightly_rate_eur"], "Bookings", row_no, errors, minimum=0.01, maximum=1_000_000),
            "source": source,
            "status": status,
            "notes": _text(raw["notes"], "Bookings", row_no, errors, max_length=2000),
            "_row": row_no,
        }
        if source not in {"Airbnb", "Booking.com", "Direct", "Other"}:
            errors.append(f"Bookings row {row_no}: booking_source must be Airbnb, Booking.com, Direct, or Other.")
        if status not in {"confirmed", "completed", "cancelled"}:
            errors.append(f"Bookings row {row_no}: status must be confirmed, completed, or cancelled.")
        if item["checkin"] and item["checkout"] and item["checkout"] <= item["checkin"]:
            errors.append(f"Bookings row {row_no}: check_out must be after check_in.")
        if item["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", item["email"]):
            errors.append(f"Bookings row {row_no}: enter a valid email address or leave it blank.")
        bookings.append(item)

    blocks = []
    for row_no, raw in block_rows:
        start = _date(raw["start_date"], "Blocked Dates", row_no, errors)
        end = _date(raw["end_date"], "Blocked Dates", row_no, errors)
        if start and end and end <= start:
            errors.append(f"Blocked Dates row {row_no}: end_date must be after start_date.")
        blocks.append({"start_date": start, "end_date": end,
                       "reason": _text(raw["reason"], "Blocked Dates", row_no, errors, max_length=2000), "_row": row_no})

    active_bookings = [b for b in bookings if b["status"] in {"confirmed", "completed"} and b["checkin"] and b["checkout"]]
    for index, booking in enumerate(active_bookings):
        for other in active_bookings[index + 1:]:
            if booking["checkin"] < other["checkout"] and other["checkin"] < booking["checkout"]:
                errors.append(f"Bookings rows {booking['_row']} and {other['_row']}: active reservations overlap.")
        for block in blocks:
            if block["start_date"] and block["end_date"] and booking["checkin"] < block["end_date"] and block["start_date"] < booking["checkout"]:
                errors.append(f"Bookings row {booking['_row']} overlaps blocked dates row {block['_row']}.")

    for index, block in enumerate(blocks):
        for other in blocks[index + 1:]:
            if block["start_date"] and block["end_date"] and other["start_date"] and other["end_date"] and block["start_date"] < other["end_date"] and other["start_date"] < block["end_date"]:
                errors.append(f"Blocked Dates rows {block['_row']} and {other['_row']}: date ranges overlap.")

    comparables = []
    for row_no, raw in comparable_rows:
        selected_text = _text(raw["selected"], "Comparables", row_no, errors, max_length=5).title() or "Yes"
        item = {
            "name": _text(raw["listing_name"], "Comparables", row_no, errors, required=True, max_length=160),
            "area": _text(raw["area"], "Comparables", row_no, errors, max_length=200),
            "bedrooms": _number(raw["bedrooms"], "Comparables", row_no, errors, minimum=0, maximum=30, integer=True),
            "capacity": _number(raw["guest_capacity"], "Comparables", row_no, errors, minimum=1, maximum=100, integer=True),
            "distance_km": _number(raw["distance_km"], "Comparables", row_no, errors, minimum=0, maximum=1000),
            "nightly_rate": _number(raw["nightly_rate_eur"], "Comparables", row_no, errors, minimum=0.01, maximum=1_000_000),
            "latitude": None if _blank(raw["latitude"]) else _number(raw["latitude"], "Comparables", row_no, errors, minimum=-90, maximum=90),
            "longitude": None if _blank(raw["longitude"]) else _number(raw["longitude"], "Comparables", row_no, errors, minimum=-180, maximum=180),
            "observed_date": _date(raw["observed_date"], "Comparables", row_no, errors),
            "url": _url(raw["listing_url"], "Comparables", row_no, errors, ("airbnb.com", "airbnb.pt", "booking.com")),
            "notes": _text(raw["notes"], "Comparables", row_no, errors, max_length=2000),
            "selected": int(selected_text == "Yes"),
            "_row": row_no,
        }
        if selected_text not in {"Yes", "No"}:
            errors.append(f"Comparables row {row_no}: selected must be Yes or No.")
        if (item["latitude"] is None) != (item["longitude"] is None):
            errors.append(f"Comparables row {row_no}: provide both coordinates or leave both blank.")
        comparables.append(item)

    for row in [*bookings, *blocks, *comparables]:
        row.pop("_row", None)
    workbook.close()
    if errors:
        return None, errors
    return {"property": property_data, "bookings": bookings, "blocked_dates": blocks, "comparables": comparables}, []
