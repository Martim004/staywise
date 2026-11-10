"""Pure business rules for bookings, market comparisons, and forecasts."""

from __future__ import annotations

import calendar
from datetime import date
from statistics import median
from typing import Any, Iterable


ACTIVE_STATUSES = {"confirmed", "completed"}


def nights_between(start: date, end: date) -> int:
    """Return stay nights for a half-open [check-in, check-out) interval."""
    if end <= start:
        raise ValueError("Check-out must be after check-in.")
    return (end - start).days


def date_ranges_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    """Whether two half-open date ranges overlap."""
    return start_a < end_b and start_b < end_a


def validate_reservation(
    reservation: dict[str, Any],
    reservations: Iterable[dict[str, Any]] = (),
    blocked_dates: Iterable[dict[str, Any]] = (),
    exclude_id: int | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        checkin = date.fromisoformat(str(reservation["checkin"]))
        checkout = date.fromisoformat(str(reservation["checkout"]))
        nights_between(checkin, checkout)
    except (KeyError, TypeError, ValueError):
        return ["Enter valid check-in and check-out dates; check-out must be later."]

    if not str(reservation.get("guest_name", "")).strip():
        errors.append("Guest name is required.")
    try:
        if int(reservation.get("guests", 0)) < 1:
            errors.append("Guest count must be at least 1.")
    except (TypeError, ValueError):
        errors.append("Guest count must be a whole number.")
    try:
        if float(reservation.get("nightly_rate", 0)) < 0:
            errors.append("Nightly rate cannot be negative.")
    except (TypeError, ValueError):
        errors.append("Nightly rate must be a number.")

    status = str(reservation.get("status", "confirmed")).lower()
    if status in ACTIVE_STATUSES:
        for other in reservations:
            if (exclude_id is not None and other.get("id") == exclude_id) or str(other.get("status", "")).lower() not in ACTIVE_STATUSES:
                continue
            other_start = date.fromisoformat(str(other["checkin"]))
            other_end = date.fromisoformat(str(other["checkout"]))
            if date_ranges_overlap(checkin, checkout, other_start, other_end):
                errors.append(f"Dates overlap with reservation #{other.get('id', '?')}.")
                break
        for block in blocked_dates:
            block_start = date.fromisoformat(str(block["start_date"]))
            block_end = date.fromisoformat(str(block["end_date"]))
            if date_ranges_overlap(checkin, checkout, block_start, block_end):
                errors.append("Dates overlap with blocked dates.")
                break
    return errors


def _overlap_days(start: date, end: date, year_start: date, year_end: date) -> int:
    left, right = max(start, year_start), min(end, year_end)
    return max(0, (right - left).days)


def calculate_forecast(
    year: int,
    reservations: Iterable[dict[str, Any]],
    blocked_dates: Iterable[dict[str, Any]],
    monthly_assumptions: dict[int, dict[str, float]],
    platform_fee_percent: float = 0,
    monthly_operating_cost: float = 0,
) -> dict[str, Any]:
    """Forecast confirmed income plus occupancy-target nights not yet booked.

    Assumed occupancy is a target for the full calendar month. Confirmed nights
    count toward that target; blocked nights are excluded from future demand.
    Tax is deliberately outside this estimate.
    """
    if not 0 <= platform_fee_percent <= 100:
        raise ValueError("Platform fee must be between 0 and 100 percent.")
    if monthly_operating_cost < 0:
        raise ValueError("Monthly operating cost cannot be negative.")

    year_start, year_end = date(year, 1, 1), date(year + 1, 1, 1)
    month_rows: list[dict[str, Any]] = []
    reservation_totals: dict[Any, dict[str, Any]] = {}
    active = [r for r in reservations if str(r.get("status", "")).lower() in ACTIVE_STATUSES]
    blocks = list(blocked_dates)

    for month in range(1, 13):
        month_start = date(year, month, 1)
        month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        days = calendar.monthrange(year, month)[1]
        booked_nights = 0
        booked_revenue = 0.0
        for reservation in active:
            start = date.fromisoformat(str(reservation["checkin"]))
            end = date.fromisoformat(str(reservation["checkout"]))
            nights = _overlap_days(start, end, month_start, month_end)
            if nights:
                revenue = nights * float(reservation["nightly_rate"])
                booked_nights += nights
                booked_revenue += revenue
                reservation_id = reservation.get("id", f"{reservation.get('guest_name')}:{reservation.get('checkin')}:{reservation.get('checkout')}")
                total = reservation_totals.setdefault(reservation_id, {
                    "id": reservation.get("id"), "guest_name": reservation.get("guest_name", ""),
                    "checkin": reservation["checkin"], "checkout": reservation["checkout"],
                    "nights_in_year": 0, "nightly_rate": float(reservation["nightly_rate"]),
                    "revenue_in_year": 0.0, "status": reservation["status"]})
                total["nights_in_year"] += nights
                total["revenue_in_year"] += revenue

        blocked_nights = 0
        for block in blocks:
            start = date.fromisoformat(str(block["start_date"]))
            end = date.fromisoformat(str(block["end_date"]))
            blocked_nights += _overlap_days(start, end, month_start, month_end)

        assumption = monthly_assumptions.get(month, {"occupancy_percent": 0, "nightly_rate": 0})
        occupancy = min(100.0, max(0.0, float(assumption.get("occupancy_percent", 0))))
        target_nights = round(days * occupancy / 100)
        forecast_nights = min(max(0, days - booked_nights - blocked_nights), max(0, target_nights - booked_nights))
        forecast_rate = max(0.0, float(assumption.get("nightly_rate", 0)))
        forecast_revenue = forecast_nights * forecast_rate
        month_rows.append({
            "month": month, "month_name": calendar.month_name[month], "days": days,
            "booked_nights": booked_nights, "blocked_nights": blocked_nights,
            "forecast_nights": forecast_nights, "assumed_occupancy_percent": occupancy,
            "assumed_nightly_rate": forecast_rate, "booked_revenue": booked_revenue,
            "forecast_revenue": forecast_revenue, "gross_revenue": booked_revenue + forecast_revenue,
        })

    gross = sum(row["gross_revenue"] for row in month_rows)
    fees = gross * platform_fee_percent / 100
    operating = monthly_operating_cost * 12
    return {
        "year": year, "months": month_rows, "reservations": list(reservation_totals.values()),
        "booked_nights": sum(r["booked_nights"] for r in month_rows),
        "forecast_nights": sum(r["forecast_nights"] for r in month_rows),
        "blocked_nights": sum(r["blocked_nights"] for r in month_rows),
        "gross_revenue": gross, "platform_fees": fees, "operating_costs": operating,
        "estimated_net": gross - fees - operating,
        "assumptions": {"platform_fee_percent": platform_fee_percent, "monthly_operating_cost": monthly_operating_cost,
                        "taxes_included": False},
    }


def competitor_summary(comparables: Iterable[dict[str, Any]], adjustment_percent: float = 0) -> dict[str, Any]:
    selected = [c for c in comparables if c.get("selected", True)]
    prices = [float(c["nightly_rate"]) for c in selected if float(c["nightly_rate"]) > 0]
    benchmark = median(prices) if prices else None
    return {"count": len(prices), "median_rate": benchmark,
            "suggested_rate": round(benchmark * (1 + adjustment_percent / 100), 2) if benchmark is not None else None}
