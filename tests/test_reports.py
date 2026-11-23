import unittest
from io import BytesIO
from zipfile import ZipFile

from staywise.calculations import calculate_forecast, competitor_summary

try:
    from staywise.reports import build_excel_report, build_pdf_report
    REPORT_DEPS_AVAILABLE = True
except ModuleNotFoundError:
    REPORT_DEPS_AVAILABLE = False


@unittest.skipUnless(REPORT_DEPS_AVAILABLE, "Install requirements.txt to test PDF and Excel exports")
class ReportTests(unittest.TestCase):
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
