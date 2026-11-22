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
    """Build a polished actual-revenue dashboard without spreadsheet formulas or tables."""
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    dashboard = wb.active
    dashboard.title = "Revenue Dashboard"
    monthly_ws = wb.create_sheet("Monthly Summary")
    channel_ws = wb.create_sheet("Channel Summary")
    daily_ws = wb.create_sheet("Daily Ledger")
    reservations_ws = wb.create_sheet("Reservations")

    start = date(year, 1, 1)
    cutoff = min(as_of, date(year, 12, 31))
    end_exclusive = cutoff + timedelta(days=1)
    active_statuses = {"confirmed", "completed"}
    days = [start + timedelta(days=i) for i in range(max(0, (end_exclusive - start).days))]
    daily_revenue = {day: 0.0 for day in days}
    daily_status = {day: "Available" for day in days}
    channel_totals: dict[str, dict[str, float]] = {}
    included = []
    active_stays = 0

    for item in reservations:
        try:
            checkin = date.fromisoformat(str(item["checkin"]))
            checkout = date.fromisoformat(str(item["checkout"]))
            rate = float(item.get("nightly_rate") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        clipped_start = max(checkin, start)
        clipped_end = min(checkout, end_exclusive)
        nights = max(0, (clipped_end - clipped_start).days)
        if nights <= 0:
            continue
        status = str(item.get("status") or "").strip().lower()
        source = str(item.get("source") or "Other").strip() or "Other"
        earned = nights * rate if status in active_statuses else 0.0
        included.append((item, checkin, checkout, nights, rate, status, source, earned))
        totals = channel_totals.setdefault(source, {"stays": 0, "revenue": 0.0})
        if status in active_statuses:
            active_stays += 1
            totals["stays"] += 1
            totals["revenue"] += earned
        for day in days:
            if checkin <= day < checkout:
                if status in active_statuses:
                    daily_revenue[day] += rate
                    daily_status[day] = "Booked"
                elif status == "cancelled" and daily_status[day] == "Available":
                    daily_status[day] = "Cancelled"

    monthly = []
    for month in range(1, 13):
        month_days = [day for day in days if day.month == month]
        booked = sum(daily_status[day] == "Booked" for day in month_days)
        revenue = sum(daily_revenue[day] for day in month_days)
        monthly.append((month_days, booked, revenue, revenue / booked if booked else 0,
                        booked / len(month_days) if month_days else 0))
    gross = sum(row[2] for row in monthly)
    booked_nights = sum(row[1] for row in monthly)
    avg_rate = gross / booked_nights if booked_nights else 0

    navy, teal, pale, stripe, muted = NAVY, TEAL, "EAF3F2", "F3F7F8", "526676"
    white, gold = "FFFFFF", "D89B43"
    thin_white = Side(style="thin", color=white)
    card_border = Border(bottom=Side(style="medium", color="D6E2E7"))

    # Dashboard cover: KPI cards are saved values, and both charts read plain numeric cells.
    dashboard.sheet_view.showGridLines = False
    dashboard.merge_cells("A1:L1")
    dashboard["A1"] = "STAYWISE  |  REVENUE DASHBOARD"
    dashboard["A1"].fill = PatternFill("solid", fgColor=navy)
    dashboard["A1"].font = Font(name="Aptos Display", size=20, bold=True, color=white)
    dashboard["A1"].alignment = Alignment(vertical="center")
    dashboard.row_dimensions[1].height = 38
    dashboard.merge_cells("A2:L2")
    dashboard["A2"] = _excel_safe(property_name)
    dashboard["A2"].font = Font(name="Aptos Display", size=15, bold=True, color=teal)
    dashboard["A2"].alignment = Alignment(vertical="center")
    dashboard.row_dimensions[2].height = 28
    dashboard.merge_cells("A3:L3")
    period = f"{year} year to date through {cutoff.isoformat()}" if year == as_of.year else f"Full year {year}"
    dashboard["A3"] = f"{period}  ·  EUR  ·  confirmed and completed stays"
    dashboard["A3"].font = Font(name="Aptos", size=10, italic=True, color=muted)
    dashboard["A3"].alignment = Alignment(vertical="center")
    dashboard.row_dimensions[3].height = 22

    cards = [
        ("A5:C5", "A6:C7", "GROSS REVENUE", gross, "Confirmed and completed nights"),
        ("D5:F5", "D6:F7", "BOOKED NIGHTS", booked_nights, "Unique nights with a stay"),
        ("G5:I5", "G6:I7", "ACTIVE STAYS", active_stays, "Reservations in the selected period"),
        ("J5:L5", "J6:L7", "AVERAGE NIGHTLY REVENUE", avg_rate, "Gross revenue per booked night"),
    ]
    for label_range, value_range, label, value, note in cards:
        dashboard.merge_cells(label_range)
        dashboard.merge_cells(value_range)
        label_cell = dashboard[label_range.split(":")[0]]
        value_cell = dashboard[value_range.split(":")[0]]
        label_cell.value = label
        value_cell.value = value
        for row in dashboard[label_range.split(":")[0]].row, dashboard[value_range.split(":")[0]].row:
            for col in range(dashboard[label_range.split(":")[0]].column,
                             dashboard[label_range.split(":")[1]].column + 1):
                cell = dashboard.cell(row=row, column=col)
                cell.fill = PatternFill("solid", fgColor=teal if label == "GROSS REVENUE" else pale)
                cell.border = card_border if label != "GROSS REVENUE" else Border()
        label_cell.font = Font(name="Aptos", size=9, bold=True, color=white if label == "GROSS REVENUE" else muted)
        label_cell.alignment = Alignment(vertical="center")
        value_cell.font = Font(name="Aptos Display", size=21, bold=True, color=white if label == "GROSS REVENUE" else navy)
        value_cell.alignment = Alignment(vertical="center")
        value_cell.number_format = '€#,##0.00;[Red]-€#,##0.00' if "REVENUE" in label else "0"
    dashboard.row_dimensions[5].height = 23
    dashboard.row_dimensions[6].height = 25
    dashboard.row_dimensions[7].height = 22
    dashboard.merge_cells("A8:L8")
    dashboard["A8"] = "Monthly revenue and booking channel mix"
    dashboard["A8"].font = Font(name="Aptos", size=11, bold=True, color=navy)
    dashboard["A8"].alignment = Alignment(vertical="center")
    dashboard.row_dimensions[8].height = 25
    for col in range(1, 13):
        dashboard.column_dimensions[get_column_letter(col)].width = 12

    monthly_ws.append(["Month", "Calendar nights", "Booked nights", "Gross revenue (€)", "Average nightly revenue (€)", "Occupancy"])
    for month, (month_days, nights, revenue, nightly, occupancy) in enumerate(monthly, start=1):
        monthly_ws.append([date(year, month, 1).strftime("%B"), len(month_days), nights, revenue, nightly, occupancy])

    channel_ws.append(["Booking source", "Active stays", "Gross revenue (€)", "Share of revenue"])
    sources = sorted(channel_totals, key=lambda name: (-channel_totals[name]["revenue"], name.casefold()))
    if not sources:
        sources = ["No recorded revenue"]
    for source in sources:
        totals = channel_totals.get(source, {"stays": 0, "revenue": 0.0})
        revenue = totals["revenue"]
        channel_ws.append([_excel_safe(source), int(totals["stays"]), revenue, revenue / gross if gross else 0])

    daily_ws.append(["Night", "Weekday", "Gross revenue (€)", "Status"])
    for day in days:
        daily_ws.append([day, day.strftime("%A"), daily_revenue[day], daily_status[day]])

    reservations_ws.append([
        "Booking ID", "Guest", "Email", "Phone", "Check-in", "Check-out",
        "Nights in selected year", "Guests", "Nightly rate (€)", "Revenue in selected year (€)",
        "Status", "Booking source", "Notes",
    ])
    for item, checkin, checkout, nights, rate, status, source, earned in included:
        reservations_ws.append([
            _excel_safe(item.get("id")), _excel_safe(item.get("guest_name")),
            _excel_safe(item.get("email")), _excel_safe(item.get("phone")),
            checkin, checkout, nights, item.get("guests"), rate, earned,
            _excel_safe(status.title()), _excel_safe(source), _excel_safe(item.get("notes")),
        ])
    if reservations_ws.max_row == 1:
        reservations_ws.append(["", "No stays overlap this reporting period"])

    # Native, formula-free Excel charts use the saved numeric values above.
    monthly_chart = BarChart()
    monthly_chart.type = "col"
    monthly_chart.style = 10
    monthly_chart.title = f"Gross revenue by month · {year}"
    monthly_chart.y_axis.title = "EUR"
    monthly_chart.x_axis.title = "Month"
    monthly_chart.height, monthly_chart.width = 8, 13
    monthly_chart.add_data(Reference(monthly_ws, min_col=4, min_row=1, max_row=13), titles_from_data=True)
    monthly_chart.set_categories(Reference(monthly_ws, min_col=1, min_row=2, max_row=13))
    monthly_chart.series[0].graphicalProperties.solidFill = teal
    dashboard.add_chart(monthly_chart, "A10")

    channel_chart = BarChart()
    channel_chart.type = "bar"
    channel_chart.style = 11
    channel_chart.title = "Revenue by booking source"
    channel_chart.x_axis.title = "EUR"
    channel_chart.y_axis.title = "Source"
    channel_chart.height, channel_chart.width = 8, 13
    channel_chart.add_data(
        Reference(channel_ws, min_col=3, min_row=1, max_row=channel_ws.max_row),
        titles_from_data=True,
    )
    channel_chart.set_categories(
        Reference(channel_ws, min_col=1, min_row=2, max_row=channel_ws.max_row)
    )
    channel_chart.series[0].graphicalProperties.solidFill = gold
    dashboard.add_chart(channel_chart, "G10")
    dashboard.freeze_panes = "A5"
    dashboard.sheet_properties.tabColor = teal
    dashboard.merge_cells("A27:L27")
    dashboard["A27"] = "Revenue totals below are saved as values for this download; re-download after changing the selected year or bookings."
    dashboard["A27"].font = Font(name="Aptos", size=9, italic=True, color=muted)
    dashboard["A27"].alignment = Alignment(wrap_text=True, vertical="center")
    dashboard.row_dimensions[27].height = 28

    # Format the clear, filter-friendly detail sheets without Excel table objects.
    for ws in (monthly_ws, channel_ws, daily_ws, reservations_ws):
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = "A2"
        ws.sheet_properties.tabColor = navy
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.font = Font(name="Aptos", color=white, bold=True)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30
        for row in ws.iter_rows(min_row=2):
            if row[0].row % 2 == 0:
                for cell in row:
                    cell.fill = PatternFill("solid", fgColor=stripe)
        for col_idx in range(1, ws.max_column + 1):
            cells = [ws.cell(row=r, column=col_idx) for r in range(1, min(ws.max_row, 500) + 1)]
            max_len = max((len(str(cell.value or "")) for cell in cells), default=12)
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 14), 38)

    for row in monthly_ws.iter_rows(min_row=2):
        row[3].number_format = '€#,##0.00;[Red]-€#,##0.00'
        row[4].number_format = '€#,##0.00;[Red]-€#,##0.00'
        row[5].number_format = "0.0%"
    for row in channel_ws.iter_rows(min_row=2):
        row[2].number_format = '€#,##0.00;[Red]-€#,##0.00'
        row[3].number_format = "0.0%"
    for row in daily_ws.iter_rows(min_row=2):
        row[0].number_format = "dd mmm yyyy"
        row[2].number_format = '€#,##0.00;[Red]-€#,##0.00'
    for row in reservations_ws.iter_rows(min_row=2):
        row[4].number_format = "dd mmm yyyy"
        row[5].number_format = "dd mmm yyyy"
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
