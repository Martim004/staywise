"""PDF and editable Excel report generation."""

from __future__ import annotations

from io import BytesIO
from typing import Any
from datetime import date, timedelta
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


NAVY = "17324D"
TEAL = "1D7A78"
PALE = "EAF3F2"


def _money(value: float) -> str:
    return f"€{value:,.2f}"


def _excel_safe(value: Any) -> Any:
    """Keep untrusted text literal when opened in spreadsheet software."""
    if isinstance(value, str):
        value = value.replace("\x00", "")
        if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
            return "'" + value
    return value


def _safe_paragraph(value: Any) -> str:
    return escape(str(value or ""))


def build_excel_report(property_name: str, report: dict[str, Any], comparables: list[dict[str, Any]], settings: dict[str, Any]) -> bytes:
    wb = Workbook()
    summary = wb.active
    summary.title = "Annual Summary"
    summary.append(["StayWise | Annual rental report"])
    summary.append([property_name])
    summary.append([f"Year: {report['year']}"])
    summary.append([])
    summary.append(["Metric", "Value", "Notes"])
    summary.append(["Gross revenue", report["gross_revenue"], "Confirmed bookings + estimated unbooked nights"])
    summary.append(["Platform fees", report["platform_fees"], f"{report['assumptions']['platform_fee_percent']:.1f}% of gross revenue"])
    summary.append(["Operating costs", report["operating_costs"], "Monthly estimate x 12"])
    summary.append(["Estimated net", report["estimated_net"], "Taxes excluded"])
    summary.append(["Booked nights", report["booked_nights"], "Confirmed or completed reservations"])
    summary.append(["Additional forecast nights", report["forecast_nights"], "Monthly occupancy target less confirmed nights"])
    summary.append([])
    summary.append(["Forecast assumptions"])
    summary.append(["Monthly operating cost", float(settings.get("monthly_operating_cost", 0))])
    summary.append(["Platform fee percent", float(settings.get("platform_fee_percent", 0))])
    summary.append(["Tax", "Not included"])

    monthly = wb.create_sheet("Monthly Forecast")
    monthly.append(["Month", "Days", "Booked nights", "Blocked nights", "Estimated nights", "Target occupancy %", "Forecast rate (€)", "Booked revenue (€)", "Forecast revenue (€)", "Gross revenue (€)"])
    for row in report["months"]:
        monthly.append([row["month_name"], row["days"], row["booked_nights"], row["blocked_nights"], row["forecast_nights"],
                        row["assumed_occupancy_percent"], row["assumed_nightly_rate"], row["booked_revenue"], row["forecast_revenue"], row["gross_revenue"]])

    bookings = wb.create_sheet("Reservations")
    bookings.append(["ID", "Guest", "Email", "Phone", "Check-in", "Check-out", "Guests", "Nightly rate (€)", "Status", "Source", "Nights in year", "Revenue in year (€)", "Notes"])
    by_id = {r.get("id"): r for r in report.get("reservation_details", [])}
    # report reservations include revenue/year details; look up contact fields from the full input list below.
    for row in report["reservations"]:
        details = by_id.get(row.get("id"), {})
        bookings.append([row.get("id"), row.get("guest_name"), details.get("email", ""), details.get("phone", ""),
                         row.get("checkin"), row.get("checkout"), details.get("guests", ""), row.get("nightly_rate"), row.get("status"),
                         details.get("source", ""), row.get("nights_in_year"), row.get("revenue_in_year"), details.get("notes", "")])

    market = wb.create_sheet("Competitors")
    market.append(["Listing", "Area", "Bedrooms", "Capacity", "Distance (km)", "Nightly rate (€)", "Observed date", "URL", "Included", "Notes"])
    for c in comparables:
        market.append([c.get("name"),c.get("area"),c.get("bedrooms"),c.get("capacity"),c.get("distance_km"),c.get("nightly_rate"),c.get("observed_date"),c.get("url"),"Yes" if c.get("selected",1) else "No",c.get("notes")])

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.value = _excel_safe(cell.value)
        ws.freeze_panes = "A2"
        ws.sheet_view.showGridLines = False
        ws.auto_filter.ref = ws.dimensions if ws.max_row > 5 else "A1:C1"
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor=NAVY)
            cell.font = Font(color="FFFFFF", bold=True, size=11)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if cell.row % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F3F7F8")
                if isinstance(cell.value, float):
                    cell.number_format = '€#,##0.00;[Red]-€#,##0.00'
        for column in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in column), default=8)
            ws.column_dimensions[get_column_letter(column[0].column)].width = min(max(max_len + 2, 12), 42)
    for cell in summary[5]:
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.font = Font(color="FFFFFF", bold=True)
    for cell in summary[1]:
        cell.font = Font(size=18, color=NAVY, bold=True)
    summary.column_dimensions["A"].width = 30
    summary.column_dimensions["B"].width = 24
    summary.column_dimensions["C"].width = 58
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def build_revenue_workbook(property_name: str, year: int, reservations: list[dict[str, Any]], as_of: date) -> bytes:
    """Build an editable actuals workbook with formula-driven revenue dashboards."""
    from openpyxl.chart import AreaChart, BarChart, DoughnutChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"

    dashboard = wb.active
    dashboard.title = "Revenue Dashboard"
    monthly_ws = wb.create_sheet("Monthly Summary")
    channels_ws = wb.create_sheet("Channel Summary")
    ledger = wb.create_sheet("Daily Ledger")
    detail = wb.create_sheet("Reservations")

    start = date(year, 1, 1)
    end = min(as_of, date(year, 12, 31))
    end_exclusive = end + timedelta(days=1)
    stays = []
    for reservation in reservations:
        try:
            checkin = date.fromisoformat(str(reservation["checkin"]))
            checkout = date.fromisoformat(str(reservation["checkout"]))
            clipped_start = max(checkin, start)
            clipped_end = min(checkout, end_exclusive)
            nights = max(0, (clipped_end - clipped_start).days)
        except (KeyError, TypeError, ValueError):
            continue
        if nights:
            stays.append((reservation, nights))

    # Precompute report values for consistent rendering across spreadsheet apps.
    active_statuses = {"confirmed", "completed"}
    daily_revenue = {start + timedelta(days=i): 0.0 for i in range((end_exclusive - start).days)}
    daily_status = {night: "Not booked" for night in daily_revenue}
    channel_totals: dict[str, dict[str, float]] = {}
    active_stays = 0
    for reservation, _ in stays:
        status = str(reservation.get("status") or "").lower()
        checkin = date.fromisoformat(str(reservation["checkin"]))
        checkout = date.fromisoformat(str(reservation["checkout"]))
        rate = float(reservation.get("nightly_rate") or 0)
        source = str(reservation.get("source") or "Other").strip() or "Other"
        channel = channel_totals.setdefault(source, {"stays": 0, "revenue": 0.0})
        clipped_start, clipped_end = max(checkin, start), min(checkout, end_exclusive)
        overlap = max(0, (clipped_end - clipped_start).days)
        if status in active_statuses:
            active_stays += 1
            channel["stays"] += 1
            channel["revenue"] += overlap * rate
        for night in daily_revenue:
            if checkin <= night < checkout:
                if status in active_statuses:
                    daily_revenue[night] += rate
                    daily_status[night] = "Booked"
                elif status == "cancelled" and daily_status[night] == "Not booked":
                    daily_status[night] = "Cancelled"
    gross_revenue = sum(daily_revenue.values())
    booked_nights = sum(status == "Booked" for status in daily_status.values())

    # The main sheet is a compact, visual output. KPI cells link to supporting schedules.
    dashboard.merge_cells("A1:P1")
    dashboard["A1"] = "STAYWISE  |  REVENUE DASHBOARD"
    dashboard.merge_cells("A2:P2")
    dashboard["A2"] = property_name
    dashboard.merge_cells("A3:P3")
    period_kind = "year to date" if year == as_of.year else "full year"
    dashboard["A3"] = f"{year} {period_kind} · through {end.isoformat()} · EUR · confirmed and completed stays"
    cards = [
        ("A5:D5", "A6:D7", "Gross revenue", gross_revenue, "€#,##0.00;[Red]-€#,##0.00"),
        ("E5:H5", "E6:H7", "Booked nights", booked_nights, "#,##0"),
        ("I5:L5", "I6:L7", "Active stays", active_stays, "#,##0"),
        ("M5:P5", "M6:P7", "Average revenue per booked night", gross_revenue / booked_nights if booked_nights else 0, "€#,##0.00;[Red]-€#,##0.00"),
    ]
    for label_range, value_range, label, formula, number_format in cards:
        dashboard.merge_cells(label_range)
        dashboard.merge_cells(value_range)
        label_cell = dashboard[label_range.split(":")[0]]
        value_cell = dashboard[value_range.split(":")[0]]
        label_cell.value = label
        label_cell.alignment = Alignment(horizontal="center", vertical="center")
        label_cell.font = Font(color=NAVY, bold=True, size=11)
        label_cell.fill = PatternFill("solid", fgColor=PALE)
        value_cell.value = formula
        value_cell.number_format = number_format
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        value_cell.font = Font(color=NAVY, bold=True, size=20)
        value_cell.fill = PatternFill("solid", fgColor="F5F8FA")

    dashboard.merge_cells("A9:P9")
    dashboard["A9"] = "This is a point-in-time report. Download again after changing bookings in StayWise or to report a different year."
    dashboard["A9"].font = Font(italic=True, color="526676", size=10)
    dashboard["A9"].alignment = Alignment(wrap_text=True, vertical="center")
    dashboard.row_dimensions[9].height = 30

    # Reservation rows include period nights and revenue calculated for this report.
    reservation_headers = [
        "Booking ID", "Guest", "Email", "Phone", "Check-in", "Check-out",
        "Nights in period", "Guests", "Nightly rate (€)", "Revenue in period (€)",
        "Status", "Source", "Notes",
    ]
    detail.append(reservation_headers)
    for reservation, _ in stays:
        row_number = detail.max_row + 1
        detail.append([
            reservation.get("id"), reservation.get("guest_name"), reservation.get("email"), reservation.get("phone"),
            date.fromisoformat(str(reservation["checkin"])), date.fromisoformat(str(reservation["checkout"])),
            max(0, (min(date.fromisoformat(str(reservation["checkout"])), end_exclusive) - max(date.fromisoformat(str(reservation["checkin"])), start)).days),
            reservation.get("guests"), float(reservation.get("nightly_rate") or 0),
            (max(0, (min(date.fromisoformat(str(reservation["checkout"])), end_exclusive) - max(date.fromisoformat(str(reservation["checkin"])), start)).days) * float(reservation.get("nightly_rate") or 0)
             if str(reservation.get("status") or "").lower() in active_statuses else 0),
            str(reservation.get("status") or "").lower(), reservation.get("source") or "Other", reservation.get("notes"),
        ])
    if detail.max_row == 1:
        detail.append([None, "No reservations in this reporting period", None, None, None, None, 0, None, 0, 0, "cancelled", None, None])
    reservation_table = Table(displayName="ReservationsTable", ref=f"A1:M{detail.max_row}")
    reservation_table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
    detail.add_table(reservation_table)
    # Keep ordinary cell references compatible across Excel, locale, and spreadsheet clients.
    reservation_last_row = max(5001, detail.max_row + 1000)

    # One row per calendar night keeps zero-revenue dates visible.
    ledger.append(["Night", "Weekday", "Gross revenue (€)", "Status"])
    day_count = (end_exclusive - start).days
    for offset in range(day_count):
        night = start + timedelta(days=offset)
        ledger.append([night, night.strftime("%A"), daily_revenue[night], daily_status[night]])
    ledger_table = Table(displayName="DailyLedgerTable", ref=f"A1:D{ledger.max_row}")
    ledger_table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
    ledger.add_table(ledger_table)

    # Monthly totals are calculated and stored as numeric values.
    monthly_ws.append(["Month", "Month start", "Next month", "Calendar nights in period", "Booked nights", "Gross revenue (€)", "Average nightly rate (€)", "Occupancy"])
    for month in range(1, 13):
        month_start = date(year, month, 1)
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        period_nights = max(0, (min(next_month, end_exclusive) - month_start).days)
        days = [month_start + timedelta(days=i) for i in range(period_nights)]
        month_booked = sum(daily_status.get(day) == "Booked" for day in days)
        month_revenue = sum(daily_revenue.get(day, 0.0) for day in days)
        monthly_ws.append([
            month_start.strftime("%B"), month_start, next_month, period_nights,
            month_booked, month_revenue, month_revenue / month_booked if month_booked else 0,
            month_booked / period_nights if period_nights else 0,
        ])
    monthly_table = Table(displayName="MonthlySummaryTable", ref="A1:H13")
    monthly_table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
    monthly_ws.add_table(monthly_table)

    # Channel totals are precomputed numeric values.
    channels_ws.append(["Booking source", "Active stays", "Gross revenue (€)"])
    standard_channels = ["Airbnb", "Booking.com", "Direct", "Other"]
    observed_channels = {str(r.get("source") or "Other").strip() or "Other" for r, _ in stays}
    channel_names = standard_channels + sorted(observed_channels - set(standard_channels), key=str.casefold)
    for channel in channel_names:
        row_number = channels_ws.max_row + 1
        channels_ws.append([
            channel,
            int(channel_totals.get(channel, {}).get("stays", 0)),
            float(channel_totals.get(channel, {}).get("revenue", 0.0)),
        ])
    channel_table = Table(displayName="ChannelSummaryTable", ref=f"A1:C{channels_ws.max_row}")
    channel_table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
    channels_ws.add_table(channel_table)

    # Charts visualize precomputed summary values consistently across spreadsheet apps.
    revenue_chart = AreaChart()
    revenue_chart.title = f"Monthly revenue · {year}"
    revenue_chart.style = 13
    revenue_chart.y_axis.title = "EUR"
    revenue_chart.x_axis.title = "Month"
    revenue_chart.height, revenue_chart.width = 8.5, 17
    revenue_chart.add_data(Reference(monthly_ws, min_col=6, min_row=1, max_row=13), titles_from_data=True)
    revenue_chart.set_categories(Reference(monthly_ws, min_col=1, min_row=2, max_row=13))
    revenue_chart.series[0].graphicalProperties.solidFill = TEAL
    revenue_chart.series[0].graphicalProperties.line.solidFill = TEAL
    dashboard.add_chart(revenue_chart, "A11")

    nights_chart = BarChart()
    nights_chart.type = "col"
    nights_chart.style = 10
    nights_chart.title = "Booked nights by month"
    nights_chart.y_axis.title = "Nights"
    nights_chart.x_axis.title = "Month"
    nights_chart.height, nights_chart.width = 8.5, 17
    nights_chart.add_data(Reference(monthly_ws, min_col=5, min_row=1, max_row=13), titles_from_data=True)
    nights_chart.set_categories(Reference(monthly_ws, min_col=1, min_row=2, max_row=13))
    nights_chart.series[0].graphicalProperties.solidFill = "E79447"
    dashboard.add_chart(nights_chart, "I11")

    channel_chart = DoughnutChart()
    channel_chart.title = "Revenue by booking source"
    channel_chart.style = 10
    channel_chart.holeSize = 58
    channel_chart.height, channel_chart.width = 8.5, 17
    channel_chart.add_data(Reference(channels_ws, min_col=3, min_row=1, max_row=channels_ws.max_row), titles_from_data=True)
    channel_chart.set_categories(Reference(channels_ws, min_col=1, min_row=2, max_row=channels_ws.max_row))
    channel_chart.dataLabels = DataLabelList()
    channel_chart.dataLabels.showPercent = True
    channel_chart.dataLabels.showLeaderLines = True
    dashboard.add_chart(channel_chart, "A28")

    # Consistent visual styling and readable supporting sheets.
    navy_fill = PatternFill("solid", fgColor=NAVY)
    teal_fill = PatternFill("solid", fgColor=TEAL)
    pale_fill = PatternFill("solid", fgColor=PALE)
    thin_border = Border(bottom=Side(style="thin", color="D6E2E7"))
    for ws in (monthly_ws, channels_ws, ledger, detail):
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.sheet_properties.tabColor = TEAL if ws is monthly_ws else NAVY
        for cell in ws[1]:
            cell.fill = navy_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.border = thin_border
                if cell.row % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F3F7F8")
        for cells in ws.columns:
            column_letter = get_column_letter(cells[0].column)
            max_len = max((len(str(cell.value or "")) for cell in cells[:100] if cell.value is not None and not (isinstance(cell.value, str) and cell.value.startswith("="))), default=10)
            ws.column_dimensions[column_letter].width = min(max(max_len + 2, 13), 36)

    dashboard.sheet_view.showGridLines = False
    dashboard.freeze_panes = "A5"
    dashboard.sheet_properties.tabColor = TEAL
    dashboard.sheet_view.zoomScale = 85
    dashboard.merge_cells("A1:P1")
    dashboard.merge_cells("A2:P2")
    dashboard.merge_cells("A3:P3")
    dashboard["A1"].font = Font(color="FFFFFF", bold=True, size=20)
    dashboard["A1"].fill = navy_fill
    dashboard["A1"].alignment = Alignment(vertical="center")
    dashboard["A2"].font = Font(color=NAVY, bold=True, size=16)
    dashboard["A3"].font = Font(color="526676", italic=True, size=10)
    dashboard.row_dimensions[1].height = 36
    dashboard.row_dimensions[2].height = 28
    dashboard.row_dimensions[3].height = 24
    dashboard.row_dimensions[5].height = 25
    dashboard.row_dimensions[6].height = 24
    dashboard.row_dimensions[7].height = 24
    for column in range(1, 17):
        dashboard.column_dimensions[get_column_letter(column)].width = 13
    for cell in dashboard[1]:
        cell.fill = navy_fill
    for cell in dashboard[2]:
        cell.fill = pale_fill
    dashboard.column_dimensions["A"].width = 18
    dashboard.column_dimensions["E"].width = 18
    dashboard.column_dimensions["I"].width = 18
    dashboard.column_dimensions["M"].width = 18
    dashboard.print_options.horizontalCentered = True
    dashboard.sheet_properties.pageSetUpPr.fitToPage = True
    dashboard.page_setup.fitToWidth = 1
    dashboard.page_setup.fitToHeight = 1
    dashboard.page_setup.orientation = "landscape"

    for row in monthly_ws.iter_rows(min_row=2):
        row[1].number_format = "dd mmm yyyy"
        row[2].number_format = "dd mmm yyyy"
        row[5].number_format = '€#,##0.00;[Red]-€#,##0.00'
        row[6].number_format = '€#,##0.00;[Red]-€#,##0.00'
        row[7].number_format = "0.0%"
    for row in channels_ws.iter_rows(min_row=2, min_col=3, max_col=3):
        row[0].number_format = '€#,##0.00;[Red]-€#,##0.00'
    for row in ledger.iter_rows(min_row=2):
        row[0].number_format = "dd mmm yyyy"
        row[2].number_format = '€#,##0.00;[Red]-€#,##0.00'
    for row in detail.iter_rows(min_row=2):
        row[4].number_format = "dd mmm yyyy"
        row[5].number_format = "dd mmm yyyy"
        row[6].number_format = "#,##0"
        row[8].number_format = '€#,##0.00;[Red]-€#,##0.00'
        row[9].number_format = '€#,##0.00;[Red]-€#,##0.00'

    output = BytesIO()
    wb.save(output)
    return output.getvalue()

def build_pdf_report(property_name: str, report: dict[str, Any], comparables: list[dict[str, Any]], settings: dict[str, Any], market: dict[str, Any]) -> bytes:
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=17*mm, leftMargin=17*mm, topMargin=17*mm, bottomMargin=17*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="BrandTitle", parent=styles["Title"], textColor=colors.HexColor("#17324D"), fontSize=24, leading=28, alignment=TA_LEFT, spaceAfter=4))
    styles.add(ParagraphStyle(name="Subtle", parent=styles["Normal"], textColor=colors.HexColor("#526676"), fontSize=9, leading=13))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#1D7A78"), fontSize=13, leading=17, spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle(name="Foot", parent=styles["Normal"], textColor=colors.HexColor("#526676"), fontSize=8, leading=11))
    story = [Paragraph("StayWise", styles["BrandTitle"]), Paragraph(f"Annual rental performance | {report['year']}", styles["Subtle"]),
             Spacer(1, 5*mm), Paragraph(_safe_paragraph(property_name), styles["Heading1"]),
             Paragraph("A clear view of bookings, market observations, and expected revenue.", styles["Subtle"]), Spacer(1, 6*mm)]

    kpis = [["Gross revenue", "Estimated net", "Confirmed nights", "Future estimate nights"],
            [_money(report["gross_revenue"]), _money(report["estimated_net"]), str(report["booked_nights"]), str(report["forecast_nights"])] ]
    kpi_table = Table(kpis, colWidths=[43*mm]*4, rowHeights=[9*mm, 14*mm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17324D")), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"), ("FONTSIZE",(0,0),(-1,0),8),
        ("BACKGROUND",(0,1),(-1,1),colors.HexColor("#EAF3F2")), ("TEXTCOLOR",(0,1),(-1,1),colors.HexColor("#17324D")),
        ("FONTNAME",(0,1),(-1,1),"Helvetica-Bold"), ("FONTSIZE",(0,1),(-1,1),12),
        ("ALIGN",(0,0),(-1,-1),"LEFT"), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#D6E2E7")),
    ]))
    story.extend([kpi_table, Paragraph("Revenue outlook by month", styles["Section"])])
    rows = [["Month", "Booked", "Forecast", "Gross", "Booked nights", "Estimate nights"]]
    for row in report["months"]:
        rows.append([row["month_name"],_money(row["booked_revenue"]),_money(row["forecast_revenue"]),_money(row["gross_revenue"]),str(row["booked_nights"]),str(row["forecast_nights"])])
    table = Table(rows, repeatRows=1, colWidths=[27*mm,28*mm,28*mm,28*mm,31*mm,32*mm])
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1D7A78")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F3F7F8")]),
        ("ALIGN",(1,1),(-1,-1),"RIGHT"),("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#D6E2E7")),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story.append(table)

    story.append(Paragraph("Pricing context", styles["Section"]))
    if market.get("median_rate") is None:
        story.append(Paragraph("No comparable listings are selected. Add observations to calculate a benchmark.", styles["Subtle"]))
    else:
        story.append(Paragraph(_safe_paragraph(f"Selected listings: {market['count']} | Median observed rate: {_money(market['median_rate'])} | Suggested rate after adjustment: {_money(market['suggested_rate'])}."), styles["Normal"]))
    comp_rows = [["Comparable", "Area", "Beds", "Nightly rate", "Observed"]]
    for c in comparables:
        if c.get("selected", 1):
            comp_rows.append([_safe_paragraph(str(c.get("name",""))[:34]),_safe_paragraph(str(c.get("area",""))[:24]),str(c.get("bedrooms","")),_money(float(c.get("nightly_rate",0))),str(c.get("observed_date",""))])
    if len(comp_rows) > 1:
        ct = Table(comp_rows, repeatRows=1, colWidths=[59*mm,41*mm,14*mm,30*mm,29*mm])
        ct.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EAF3F2")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#17324D")),
                                ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
                                ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#D6E2E7")),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        story.append(ct)

    story.extend([Paragraph("Reservations in this report year", styles["Section"])])
    booking_rows = [["Guest", "Dates", "Guests", "Rate", "Status", "Contact"]]
    details = {r.get("id"):r for r in report.get("reservation_details", [])}
    for r in report["reservations"]:
        d = details.get(r.get("id"), {})
        booking_rows.append([_safe_paragraph(str(r.get("guest_name",""))[:24]), _safe_paragraph(f"{r.get('checkin')} to {r.get('checkout')}"), str(d.get("guests","")), _money(r["nightly_rate"]), _safe_paragraph(str(r.get("status",""))), _safe_paragraph(str(d.get("email") or d.get("phone") or "")[:26])])
    if len(booking_rows) == 1:
        booking_rows.append(["No confirmed reservations for this year", "", "", "", "", ""])
    bt = Table(booking_rows, repeatRows=1, colWidths=[34*mm,43*mm,15*mm,23*mm,23*mm,35*mm])
    bt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17324D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F3F7F8")]),
        ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#D6E2E7")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(bt)
    story.append(Spacer(1,4*mm))
    assumptions = (f"Assumptions: monthly occupancy targets and nightly rates estimate unbooked nights. Confirmed nights count toward each target; "
                   f"owner-blocked dates are excluded. Estimated net subtracts platform fees ({float(settings.get('platform_fee_percent',0)):.1f}%) "
                   f"and operating costs ({_money(float(settings.get('monthly_operating_cost',0)))}/month). Taxes are not included. "
                   f"Competitor prices are user-entered observations, not live marketplace data.")
    story.append(Paragraph(assumptions, styles["Foot"]))

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D6E2E7"))
        canvas.line(17*mm, 12*mm, A4[0]-17*mm, 12*mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526676"))
        canvas.drawString(17*mm, 8*mm, "StayWise - Private rental report")
        canvas.drawRightString(A4[0]-17*mm, 8*mm, f"Page {_doc.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
