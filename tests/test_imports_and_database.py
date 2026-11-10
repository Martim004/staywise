import csv
import io
import os
import tempfile
import unittest
from pathlib import Path

from staywise import database
from staywise.imports import CSV_FIELDS, parse_booking_csv, template_csv


class ImportAndDatabaseTests(unittest.TestCase):
    def test_csv_import_accepts_valid_rows_and_rejects_invalid_and_overlapping_rows(self):
        data = ("guest_name,email,phone,checkin,checkout,guests,nightly_rate,status,source,notes\n"
                "Sam,sam@example.test,123,2026-07-01,2026-07-04,2,140,confirmed,Airbnb,ok\n"
                "Bad,bad@example.test,123,2026-07-03,2026-07-05,2,140,confirmed,Direct,overlap\n"
                "Wrong,,,,2026-08-01,0,-1,unknown,Direct,bad input\n").encode()
        accepted, errors = parse_booking_csv(data, [], [])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["guests"], 2)
        self.assertEqual(len(errors), 2)
        self.assertIn("overlap", errors[0].lower())
        self.assertIn("Status", errors[1])

    def test_csv_import_requires_documented_header(self):
        accepted, errors = parse_booking_csv(b"name,date\nA,2026-01-01\n", [], [])
        self.assertEqual(accepted, [])
        self.assertIn("Missing required columns", errors[0])

    def test_csv_template_includes_all_fields(self):
        rows = list(csv.DictReader(io.StringIO(template_csv().decode())))
        self.assertTrue(rows)
        self.assertEqual(list(rows[0]), CSV_FIELDS)

    def test_database_persists_and_reads_records(self):
        previous_path = os.environ.get("STAYWISE_DB_PATH")
        previous_demo = os.environ.pop("STAYWISE_DEMO", None)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.environ["STAYWISE_DB_PATH"] = str(Path(temp_dir) / "staywise.sqlite3")
                database.init_db()
                rid = database.add_reservation({"guest_name":"Demo","email":"x@example.test","phone":"123","checkin":"2026-08-01","checkout":"2026-08-03","guests":2,"nightly_rate":99,"status":"confirmed","source":"Direct","notes":"test"})
                self.assertEqual(database.get_reservations()[0]["id"], rid)
                database.add_blocked_dates("2026-09-01","2026-09-02","maintenance")
                self.assertEqual(database.get_blocked_dates()[0]["reason"], "maintenance")
        finally:
            if previous_path is None:
                os.environ.pop("STAYWISE_DB_PATH", None)
            else:
                os.environ["STAYWISE_DB_PATH"] = previous_path
            if previous_demo is not None:
                os.environ["STAYWISE_DEMO"] = previous_demo
