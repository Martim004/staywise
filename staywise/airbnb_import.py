"""Parse Airbnb earnings exports into validated StayWise reservation rows."""

from __future__ import annotations

import csv
from datetime import date, datetime
from io import BytesIO, StringIO
import math
import re
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024
MAX_ROWS = 2000

REQUIRED_COLUMNS = {
    "type", "confirmation code", "start date", "end date", "nights", "guest",
    "listing", "currency", "gross earnings",
}
OPTIONAL_COLUMNS = {
    "booking status", "contact", "adults", "children", "infants", "amount",
    "paid out", "service fee", "fast pay fee", "cleaning fee", "pet fee",
    "airbnb remitted tax", "date", "booking date", "earnings year", "details",
}


def _clean_header(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _date_value(value, field: str, row_number: int, errors: list[str]) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw, pattern).date()
            except ValueError:
                continue
    errors.append(f"Row {row_number}: {field} must be an Excel date or a date such as 2026-06-15.")
    return None


def _number(value, field: str, row_number: int, errors: list[str], *, default=None, whole=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, str):
        raw = value.strip().replace("€", "").replace("$", "").replace("£", "").replace(" ", "")
        if "," in raw and "." in raw:
            raw = raw.replace(",", "") if raw.rfind(".") > raw.rfind(",") else raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        value = raw
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        errors.append(f"Row {row_number}: {field} must be a number.")
        return None
    if not math.isfinite(result) or abs(result) > 1_000_000_000 or (whole and not result.is_integer()):
        errors.append(f"Row {row_number}: {field} is outside the supported range.")
        return None
    return int(result) if whole else result


def _contact(value) -> tuple[str, str]:
    raw = str(value or "").strip()
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", raw, re.I)
    email = email_match.group(0)[:254] if email_match else ""
    phone_match = re.search(r"\+?\d[\d() .-]{5,}\d", raw)
    phone = phone_match.group(0).strip()[:40] if phone_match else ""
    return email, phone


def _rows_from_xlsx(data: bytes) -> tuple[list[dict] | None, list[str]]:
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                return None, ["The workbook expands beyond the 30 MB safety limit."]
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except (BadZipFile, OSError, ValueError, KeyError):
        return None, ["This is not a readable .xlsx workbook. Upload an Airbnb earnings export."]
    if not workbook.worksheets:
        workbook.close()
        return None, ["The workbook has no worksheet."]
    sheet = workbook.active
    if sheet.max_row > MAX_ROWS + 1 or sheet.max_column > 60:
        workbook.close()
        return None, ["The Airbnb export exceeds StayWise's 2,000-row or 60-column limit."]
    header_row = None
    headers = []
    for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 10), values_only=True), 1):
        candidates = [_clean_header(value) for value in row]
        if REQUIRED_COLUMNS.issubset(set(candidates)):
            header_row = row_number
            headers = candidates
            break
    if header_row is None:
        workbook.close()
        return None, ["Required Airbnb earnings columns were not found. Upload the Airbnb earnings export format shown in the template."]
    if len(headers) != len(set(headers)):
        workbook.close()
        return None, ["The Airbnb export has duplicate column headings."]
    rows = []
    for row_number, values in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
        if row_number > MAX_ROWS + header_row:
            break
        rows.append({header: value for header, value in zip(headers, values)})
    workbook.close()
    return rows, []


def _rows_from_csv(data: bytes) -> tuple[list[dict] | None, list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, ["CSV exports must be encoded as UTF-8."]
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        return None, ["The Airbnb CSV has no header row."]
    headers = [_clean_header(value) for value in reader.fieldnames]
    if REQUIRED_COLUMNS - set(headers):
        return None, ["Required Airbnb earnings columns were not found. Upload the Airbnb earnings export format shown in the template."]
    if len(headers) != len(set(headers)):
        return None, ["The Airbnb CSV has duplicate column headings."]
    rows = []
    for row_number, raw in enumerate(reader, 2):
        if row_number > MAX_ROWS + 1:
            return None, ["The Airbnb CSV exceeds StayWise's 2,000-row limit."]
        rows.append({_clean_header(key): value for key, value in raw.items() if key is not None})
    return rows, []


def parse_airbnb_earnings_export(data: bytes, file_name: str = "") -> tuple[dict | None, list[str]]:
    """Read an Airbnb earnings export without saving data; return listing rows and validation errors."""
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_UPLOAD_BYTES:
        return None, ["Upload an Airbnb .xlsx or .csv file smaller than 5 MB."]
    if file_name.casefold().endswith(".csv"):
        raw_rows, errors = _rows_from_csv(bytes(data))
    else:
        raw_rows, errors = _rows_from_xlsx(bytes(data))
    if errors or raw_rows is None:
        return None, errors

    errors = []
    listings: dict[str, list[dict]] = {}
    seen_codes: set[tuple[str, str]] = set()
    currencies: set[str] = set()
    for index, raw in enumerate(raw_rows, 2):
        if not any(value is not None and str(value).strip() for value in raw.values()):
            continue
        transaction_type = str(raw.get("type") or "").strip().casefold()
        if transaction_type != "reservation":
            continue
        listing = str(raw.get("listing") or "").strip()
        code = str(raw.get("confirmation code") or "").strip()
        status_raw = str(raw.get("booking status") or "").strip().casefold()
        if not listing:
            errors.append(f"Row {index}: Listing is required for a Reservation.")
            continue
        if not code:
            errors.append(f"Row {index}: Confirmation code is required for a Reservation.")
            continue
        duplicate_key = (listing.casefold(), code.casefold())
        if duplicate_key in seen_codes:
            errors.append(f"Row {index}: confirmation code {code} appears more than once for this listing.")
            continue
        seen_codes.add(duplicate_key)

        start_date = _date_value(raw.get("start date"), "Start date", index, errors)
        end_date = _date_value(raw.get("end date"), "End date", index, errors)
        nights = _number(raw.get("nights"), "Nights", index, errors, whole=True)
        if start_date and end_date and end_date <= start_date:
            errors.append(f"Row {index}: End date must be after Start date.")
        if start_date and end_date and nights is not None and nights != (end_date - start_date).days:
            errors.append(f"Row {index}: Nights does not match the Start date and End date range.")
        elif nights is None and start_date and end_date:
            nights = (end_date - start_date).days
        if nights is None or nights <= 0:
            errors.append(f"Row {index}: Nights must be greater than zero.")

        currency = str(raw.get("currency") or "").strip().upper()
        if currency:
            currencies.add(currency)
        gross = _number(raw.get("gross earnings"), "Gross earnings", index, errors)
        if gross is None:
            gross = _number(raw.get("amount"), "Amount", index, errors)
        if gross is None or gross <= 0:
            errors.append(f"Row {index}: Gross earnings (or Amount) must be greater than zero for a reservation.")

        adults = _number(raw.get("adults"), "Adults", index, errors, default=0, whole=True) or 0
        children = _number(raw.get("children"), "Children", index, errors, default=0, whole=True) or 0
        infants = _number(raw.get("infants"), "Infants", index, errors, default=0, whole=True) or 0
        guests = max(1, adults + children + infants)
        guest_name = str(raw.get("guest") or "Airbnb guest").strip()[:120]
        email, phone = _contact(raw.get("contact"))

        if status_raw in {"cancelled", "canceled"}:
            status = "cancelled"
        elif status_raw in {"completed", "checked out", "checked-out"}:
            status = "completed"
        elif status_raw in {"confirmed", "accepted", "booked", ""}:
            status = "completed" if end_date and end_date <= date.today() else "confirmed"
        else:
            errors.append(f"Row {index}: unsupported Booking status '{status_raw}'.")
            status = "confirmed"

        service_fee = _number(raw.get("service fee"), "Service fee", index, errors, default=0) or 0
        fast_pay_fee = _number(raw.get("fast pay fee"), "Fast pay fee", index, errors, default=0) or 0
        cleaning_fee = _number(raw.get("cleaning fee"), "Cleaning fee", index, errors, default=0) or 0
        pet_fee = _number(raw.get("pet fee"), "Pet fee", index, errors, default=0) or 0
        paid_out = _number(raw.get("paid out"), "Paid out", index, errors, default=0) or 0
        remitted_tax = _number(raw.get("airbnb remitted tax"), "Airbnb remitted tax", index, errors, default=0) or 0
        note_parts = [f"Imported from Airbnb earnings export; confirmation code {code}",
                      f"gross earnings {currency or 'unknown currency'} {gross:.2f}"]
        if paid_out:
            note_parts.append(f"paid out {paid_out:.2f}")
        if service_fee or fast_pay_fee:
            note_parts.append(f"platform fees {service_fee + fast_pay_fee:.2f}")
        if cleaning_fee or pet_fee:
            note_parts.append(f"cleaning/pet fees {cleaning_fee + pet_fee:.2f}")
        if remitted_tax:
            note_parts.append(f"Airbnb-remitted tax {remitted_tax:.2f}")
        reservation = {
            "guest_name": guest_name or "Airbnb guest",
            "email": email,
            "phone": phone,
            "checkin": start_date.isoformat() if start_date else None,
            "checkout": end_date.isoformat() if end_date else None,
            "guests": guests,
            "nightly_rate": round(gross / nights, 2) if gross and nights else 0,
            "status": status,
            "source": "Airbnb",
            "notes": "; ".join(note_parts)[:2000],
            "_row": index,
        }
        listings.setdefault(listing, []).append(reservation)

    if currencies - {"EUR"}:
        errors.append("This StayWise workspace reports revenue in EUR. Convert every Airbnb reservation row to EUR before importing; mixed or non-EUR reports are not converted automatically.")
    if len(listings) > 1:
        errors.append("This export contains more than one listing. Filter the Airbnb report to one listing and upload it again so StayWise can create one correctly configured property.")
    if not listings and not errors:
        errors.append("No Reservation rows with booking data were found. The attached template is blank; upload the populated export downloaded from your Airbnb account.")
    for reservations in listings.values():
        active = [r for r in reservations if r["status"] in {"confirmed", "completed"}]
        for i, item in enumerate(active):
            for other in active[i + 1:]:
                if item["checkin"] < other["checkout"] and other["checkin"] < item["checkout"]:
                    errors.append(f"Rows {item['_row']} and {other['_row']}: active Airbnb reservations overlap.")
    for reservations in listings.values():
        for reservation in reservations:
            reservation.pop("_row", None)
    if errors:
        return None, errors
    listing_name, bookings = next(iter(listings.items()))
    return {"listing_name": listing_name, "bookings": bookings, "currency": "EUR"}, []
