import unittest
from io import BytesIO
from zipfile import ZipFile
from datetime import date
from openpyxl import load_workbook

from staywise.calculations import calculate_forecast, competitor_summary

try:
    from staywise.reports import build_excel_report, build_pdf_report, build_revenue_workbook
    REPORT_DEPS_AVAILABLE = True
except ModuleNotFoundError:
    REPORT_DEPS_AVAILABLE = False


@unittest.skipUnless(REPORT_DEPS_AVAILABLE, "Install requirements.txt to test PDF and Excel exports")
class ReportTests(unittest.TestCase):
    def test_revenue_workbook_channel_summary_is_airbnb_only(self):
        bookings = [
            {"id":1,"guest_name":"Airbnb guest","checkin":"2026-05-10","checkout":"2026-05-12",
             "nightly_rate":100,"status":"confirmed","source":"Airbnb"},
            {"id":2,"guest_name":"Direct guest","checkin":"2026-06-10","checkout":"2026-06-12",
             "nightly_rate":120,"status":"completed","source":"Direct"},
            {"id":3,"guest_name":"Legacy guest","checkin":"2026-07-10","checkout":"2026-07-12",
             "nightly_rate":130,"status":"confirmed","source":"Booking.com"},
        ]
        payload = build_revenue_workbook("Example home", 2026, bookings, date(2026, 12, 31))
        workbook = load_workbook(BytesIO(payload), data_only=True)
        channel = workbook["Channel Summary"]
        self.assertEqual([channel.cell(row, 1).value for row in range(1, channel.max_row + 1)],
                         ["Channel", "Airbnb"])
        self.assertFalse(any("Booking.com" in str(cell.value) for row in channel.iter_rows() for cell in row))
        dashboard_values = [cell.value for row in workbook["Revenue Dashboard"].iter_rows() for cell in row]
        self.assertFalse(any("Booking.com" in str(value) for value in dashboard_values))
        self.assertEqual(channel["C2"].value, 200)

    def test_excel_and_pdf_exports_include_report_sections(self):
        assumptions = {m:{"occupancy_percent":0,"nightly_rate":100} for m in range(1,13)}
        reservations = [{"id":1,"guest_name":"Alex Example","email":"alex@example.test","phone":"+351 900 000 100",
                         "checkin":"2026-05-10","checkout":"2026-05-12","guests":2,"nightly_rate":120,
                         "status":"confirmed","source":"Direct","notes":"Fictional"}]
        result = calculate_forecast(2026,reservations,[],assumptions,10,25)
        result["reservation_details"] = reservations
        comps = [{"name":"Nearby flat","area":"Central","bedrooms":2,"capacity":4,"distance_km":0.5,"nightly_rate":150,
                  "observed_date":"2026-01-01","url":"https://example.test","notes":"sample","selected":1}]
        settings = {"platform_fee_percent":"10","monthly_operating_cost":"25"}
        excel = build_excel_report("Example home",result,comps,settings)
        pdf = build_pdf_report("Example home",result,comps,settings,competitor_summary(comps))
        with ZipFile(BytesIO(excel)) as archive:
            workbook_xml = archive.read("xl/workbook.xml").decode()
            self.assertIn("Annual Summary", workbook_xml)
            self.assertIn("Monthly Forecast", workbook_xml)
            self.assertIn("Reservations", workbook_xml)
            self.assertIn("Competitors", workbook_xml)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)
