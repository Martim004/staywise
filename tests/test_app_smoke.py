import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class AppSmokeTests(unittest.TestCase):
    def test_pages_render_and_demo_write_controls_are_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {
            "STAYWISE_DEMO":"1", "STAYWISE_DB_PATH":str(Path(temp_dir)/"demo.sqlite3")
        }, clear=False):
            app = AppTest.from_file("app.py").run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            for page in ["Bookings", "Calendar", "Market"]:
                app.sidebar.radio[0].set_value(page)
                app.run(timeout=30)
                self.assertEqual(len(app.exception), 0, f"{page} page raised: {[e.message for e in app.exception]}")
                if page in {"Bookings", "Market"}:
                    self.assertTrue(all(button.disabled for button in app.button if button.label in {
                        "Save booking", "Block dates", "Remove", "Delete selected booking",
                        "Save property settings", "Add comparison", "Delete"
                    }))
            app.sidebar.radio[0].set_value("Bookings")
            app.run(timeout=30)
            self.assertEqual(len(app.get("file_uploader")), 0, "Public demo must not accept booking CSV uploads")
