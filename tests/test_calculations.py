import unittest
from datetime import date

from staywise.calculations import (calculate_forecast, competitor_summary,
                                   date_ranges_overlap, validate_reservation)


def reservation(**updates):
    item = {"id":1,"guest_name":"Alex","checkin":"2026-06-10","checkout":"2026-06-13",
            "guests":2,"nightly_rate":120,"status":"confirmed"}
    item.update(updates)
    return item


class CalculationTests(unittest.TestCase):
    def test_checkout_date_is_exclusive_for_overlap(self):
        self.assertFalse(date_ranges_overlap(date(2026,6,10), date(2026,6,13), date(2026,6,13), date(2026,6,15)))
        self.assertTrue(date_ranges_overlap(date(2026,6,10), date(2026,6,14), date(2026,6,13), date(2026,6,15)))

    def test_reservation_validation_rejects_bad_dates_rates_and_overlaps(self):
        current = reservation()
        self.assertIn("Dates overlap with reservation #1.", validate_reservation(reservation(id=2), [current]))
        self.assertTrue(any("check-out" in e.lower() for e in validate_reservation(reservation(checkout="2026-06-10"))))
        self.assertIn("Nightly rate cannot be negative.", validate_reservation(reservation(nightly_rate=-1)))
        self.assertIn("Guest count must be at least 1.", validate_reservation(reservation(guests=0)))

    def test_cancelled_reservation_does_not_block_dates(self):
        self.assertEqual(validate_reservation(reservation(id=2), [reservation(status="cancelled")]), [])

    def test_reservation_validation_rejects_blocked_dates(self):
        block = {"start_date":"2026-06-12","end_date":"2026-06-15"}
        self.assertIn("Dates overlap with blocked dates.", validate_reservation(reservation(), [], [block]))

    def test_forecast_counts_booked_nights_once_and_handles_leap_year(self):
        assumptions = {m:{"occupancy_percent":0,"nightly_rate":100} for m in range(1,13)}
        assumptions[2] = {"occupancy_percent":50,"nightly_rate":100}
        assumptions[3] = {"occupancy_percent":25,"nightly_rate":200}
        bookings = [
            {"id":1,"guest_name":"A","checkin":"2024-02-28","checkout":"2024-03-01","nightly_rate":100,"status":"confirmed"},
            {"id":2,"guest_name":"B","checkin":"2024-03-10","checkout":"2024-03-12","nightly_rate":100,"status":"confirmed"},
            {"id":3,"guest_name":"C","checkin":"2024-04-01","checkout":"2024-04-05","nightly_rate":500,"status":"cancelled"},
        ]
        blocks = [{"start_date":"2024-02-10","end_date":"2024-02-12"}]
        result = calculate_forecast(2024, bookings, blocks, assumptions, 10, 50)
        feb, mar = result["months"][1], result["months"][2]
        self.assertEqual(feb["days"], 29)
        self.assertEqual((feb["booked_nights"],feb["blocked_nights"],feb["forecast_nights"]),(2,2,12))
        self.assertEqual((mar["booked_nights"],mar["forecast_nights"]),(2,6))
        self.assertEqual((result["booked_nights"],result["forecast_nights"]),(4,18))
        self.assertEqual((result["gross_revenue"],result["platform_fees"],result["operating_costs"],result["estimated_net"]),(2800,280,600,1920))
        self.assertFalse(result["assumptions"]["taxes_included"])
        self.assertEqual(len(result["reservations"]),2)

    def test_forecast_rejects_invalid_cost_parameters(self):
        with self.assertRaises(ValueError):
            calculate_forecast(2026, [], [], {}, 101, 0)
        with self.assertRaises(ValueError):
            calculate_forecast(2026, [], [], {}, 0, -1)

    def test_competitor_median_and_adjustment_use_selected_listings_only(self):
        comps = [{"nightly_rate":100,"selected":True},{"nightly_rate":140,"selected":True},{"nightly_rate":1000,"selected":False}]
        result = competitor_summary(comps, 10)
        self.assertEqual(result, {"count":2,"median_rate":120,"suggested_rate":132})
        self.assertIsNone(competitor_summary([], 0)["suggested_rate"])
