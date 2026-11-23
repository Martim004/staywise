import csv
import io
import os
import tempfile
import unittest
from datetime import date, time, timedelta
from pathlib import Path
from unittest.mock import patch

from staywise import database
from staywise.airbnb_import import parse_airbnb_earnings_export, REQUIRED_COLUMNS


class FinalRegressionTests(unittest.TestCase):
    def test_airbnb_duplicate_codes_currency_and_gross_revenue(self):
        row = {key: "" for key in REQUIRED_COLUMNS}
        row.update({"type":"Reservation", "confirmation code":"REVIEW123", "listing":"Review Home",
                    "start date":"2026-07-01", "end date":"2026-07-04", "nights":"3",
                    "guest":"Review Guest", "currency":"EUR", "gross earnings":"300",
                    "booking status":"completed"})
        def payload(rows):
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=list(row))
            writer.writeheader(); writer.writerows(rows)
            return text.getvalue().encode()
        report, errors = parse_airbnb_earnings_export(payload([row]), "review.csv")
        self.assertEqual(errors, [])
        self.assertEqual(report["bookings"][0]["nightly_rate"], 100)
        report, errors = parse_airbnb_earnings_export(payload([row, row]), "review.csv")
        self.assertTrue(errors)
        report, errors = parse_airbnb_earnings_export(payload([{**row, "currency":"USD"}]), "review.csv")
        self.assertTrue(any("EUR" in error for error in errors))

    def test_batch_failure_is_atomic_and_cleaning_is_property_scoped(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "STAYWISE_DB_PATH": str(Path(folder)/"review.sqlite3"), "STAYWISE_DEMO":"0",
        }):
            database.set_authenticated_user(None)
            database.init_db()
            def property_item(name):
                return dict(name=name, area="Lisbon", bedrooms=1, capacity=2, latitude=38.7,
                            longitude=-9.1, airbnb_url="", sample_data_enabled=False)
            first = database.add_property(property_item("First"))
            second = database.add_property(property_item("Second"))
            start = date.today()+timedelta(days=2)
            item = dict(property_id=first, guest_name="Review", email="", phone="",
                        checkin=start.isoformat(), checkout=(start+timedelta(days=2)).isoformat(),
                        guests=2, nightly_rate=100, status="confirmed", source="Direct", notes="")
            with self.assertRaises(ValueError):
                database.add_reservations_batch([item, item])
            self.assertEqual(database.get_reservations(first), [])
            rid = database.add_reservation(item)
            self.assertFalse(database.schedule_checkout_cleaning(second, rid, time(12)))
            self.assertTrue(database.schedule_checkout_cleaning(first, rid, time(12)))
            self.assertFalse(database.schedule_checkout_cleaning(first, rid, time(13)))
            self.assertFalse(database.cancel_checkout_cleaning(second, rid))
            database.complete_checkout_cleaning(second, rid)
            self.assertFalse(database.get_checkout_cleanings(first)[0]["completed"])
            database.delete_reservation(rid)
            self.assertEqual(database.get_checkout_cleanings(first), [])
