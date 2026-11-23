import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from staywise import database

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppSmokeTests(unittest.TestCase):
    def test_local_workspace_pages_and_calendar_navigation(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {
            "STAYWISE_LOCAL_MODE": "1", "STAYWISE_DEMO": "0",
            "STAYWISE_DB_PATH": str(Path(temp_dir) / "workspace.sqlite3"),
        }), patch("staywise.auth.auth_is_configured", return_value=False), patch(
            "pandas.read_csv", side_effect=OSError("Offline test")
        ):
            database.set_authenticated_user(None)
            database.init_db()
            pid = database.add_property(dict(name="Review home", area="Test area, Lisbon",
                bedrooms=2, capacity=4, latitude=38.719, longitude=-9.165,
                airbnb_url="", sample_data_enabled=False))
            rid = database.add_reservation(dict(property_id=pid, guest_name="Review Guest", email="",
                phone="", checkin=date.today().isoformat(),
                checkout=(date.today()+timedelta(days=2)).isoformat(), guests=2,
                nightly_rate=100, status="confirmed", source="Direct", notes=""))
            app = AppTest.from_file(str(APP_PATH))
            app.session_state["selected_property_id"] = pid
            app.run(timeout=30)
            for page, title in [("Overview", "Review home overview"), ("Bookings", "Bookings"),
                                ("Calendar", "Calendar"), ("Market", "Market"), ("Revenue", "Revenue")]:
                app.session_state["workspace_page"] = page
                app.run(timeout=30)
                self.assertEqual(len(app.exception), 0, f"{page}: {[e.message for e in app.exception]}")
                self.assertIn(title, [t.value for t in app.title], f"Did not reach {page}")
                if page == "Bookings":
                    self.assertFalse(next(b for b in app.button if b.label == "Save booking").disabled)
                    self.assertTrue(any(t.value == "Review Guest" for t in app.text))
            app.session_state["workspace_page"] = "Calendar"
            app.session_state["calendar_target_date"] = date(2026, 12, 1)
            app.run(timeout=30)
            app.button(key="calendar_next").click().run(timeout=30)
            self.assertEqual(app.selectbox(key="calendar_month").value, 1)
            self.assertEqual(app.selectbox(key="calendar_year").value, 2027)
            app.button(key="calendar_today").click().run(timeout=30)
            self.assertEqual(app.selectbox(key="calendar_month").value, date.today().month)
            self.assertEqual(app.selectbox(key="calendar_year").value, date.today().year)
            self.assertEqual(len(app.exception), 0)

            database.delete_reservation(rid)
            for page in ["Overview", "Bookings", "Revenue"]:
                app.session_state["workspace_page"] = page
                app.run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertTrue(any(b.label == "Add a booking" for b in app.button), page)
            app.button(key="empty_add_Revenue").click().run(timeout=30)
            self.assertEqual(app.session_state["workspace_page"], "Bookings")
            self.assertEqual(len(app.exception), 0)

    def test_deployment_without_auth_fails_closed(self):
        with patch.dict(os.environ, {"STAYWISE_LOCAL_MODE": "0"}), patch(
            "staywise.auth.auth_is_configured", return_value=False
        ), patch("staywise.database.get_workspace_bootstrap") as bootstrap:
            app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Sign-in is temporarily unavailable", [t.value for t in app.title])
            bootstrap.assert_not_called()
