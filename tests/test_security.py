import unittest

from staywise.calculations import validate_reservation
from staywise.imports import MAX_CSV_BYTES, export_csv, parse_booking_csv


class SecurityInputTests(unittest.TestCase):
    def valid_booking(self, **updates):
        item = {
            "guest_name": "Demo Guest",
            "email": "demo@example.test",
            "phone": "",
            "checkin": "2026-07-01",
            "checkout": "2026-07-03",
            "guests": 2,
            "nightly_rate": 120,
            "status": "confirmed",
            "source": "Direct",
            "notes": "",
        }
        item.update(updates)
        return item

    def test_rejects_non_finite_rates_and_unknown_status(self):
        for rate in (float("nan"), float("inf"), float("-inf")):
            self.assertTrue(validate_reservation(self.valid_booking(nightly_rate=rate)))
        self.assertTrue(validate_reservation(self.valid_booking(status="pending")))

    def test_rejects_overlong_text_and_bad_email(self):
        self.assertTrue(validate_reservation(self.valid_booking(guest_name="x" * 121)))
        self.assertTrue(validate_reservation(self.valid_booking(email="invalid address")))

    def test_csv_import_enforces_upload_and_header_limits(self):
        accepted, errors = parse_booking_csv(b"x" * (MAX_CSV_BYTES + 1), [], [])
        self.assertEqual(accepted, [])
        self.assertIn("no larger", errors[0])
        duplicate = b"guest_name,guest_name\nA,B\n"
        accepted, errors = parse_booking_csv(duplicate, [], [])
        self.assertEqual(accepted, [])
        self.assertIn("duplicate", errors[0].lower())

    def test_csv_export_neutralizes_spreadsheet_formulas(self):
        payload = export_csv([self.valid_booking(guest_name="=HYPERLINK(\"https://attacker.invalid\")")])
        self.assertIn(b"'=HYPERLINK", payload)


if __name__ == "__main__":
    unittest.main()
