"""PDF and editable Excel report generation."""

from __future__ import annotations

from io import BytesIO
from typing import Any
from datetime import date, timedelta

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
    """Create an owner-friendly, actuals-only revenue workbook for year-to-date."""
    wb = Workbook()
    dashboard = wb.active
    dashboard.title = "Revenue Dashboard"
    start, end = date(year, 1, 1), min(as_of, date(year, 12, 31))
    booked = [r for r in reservations if r.get("status") in {"confirmed", "completed"}]
    daily: dict[date, float] = {}
    stays = []
    for r in reservations:
        checkin, checkout = date.fromisoformat(r["checkin"]), date.fromisoformat(r["checkout"])
        clipped_start, clipped_end = max(checkin, start), min(checkout, end + timedelta(days=1))
        nights = max(0, (clipped_end - clipped_start).days)
        rate = float(r.get("nightly_rate") or 0)
        revenue = nights * rate if r.get("status") in {"confirmed", "completed"} else 0.0
        if nights:
            stays.append((r, nights, revenue))
        if revenue:
            for offset in range(nights):
                night = clipped_start + timedelta(days=offset)
                daily[night] = daily.get(night, 0.0) + rate
    monthly = [sum(value for day, value in daily.items() if day.month == month) for month in range(1, 13)]
    total = sum(monthly)
    booked_nights = sum(len([d for d in daily if d.month == month]) for month in range(1, 13))
    dashboard.append(["STAYWISE  |  REVENUE DASHBOARD"])
    dashboard.append([property_name])
    dashboard.append([f"{year} year to date · through {end.isoformat()} · EUR · actual booked nightly revenue"])
    dashboard.append([])
    dashboard.append(["Key measure", "Value", "Definition"])
    dashboard.append(["Gross revenue", total, "Confirmed or completed stay nights through the reporting date; cancelled stays excluded"])
    dashboard.append(["Booked nights", booked_nights, "Unique nights with an active reservation"])
    dashboard.append(["Active reservations", len([r for r in booked if date.fromisoformat(r["checkin"]) <= end and date.fromisoformat(r["checkout"]) > start]), "Confirmed or completed stays overlapping the reporting period"])
    dashboard.append(["Average revenue per booked night", total / booked_nights if booked_nights else 0, "Gross revenue divided by booked nights"])
    dashboard.append([])
    dashboard.append(["Month", "Gross revenue (€)"])
    for month in range(1, 13):
        dashboard.append([date(year, month, 1).strftime("%B"), monthly[month - 1]])
    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    chart.title = f"Monthly gross revenue · {year}"
    chart.y_axis.title = "EUR"
    chart.x_axis.title = "Month"
    chart.height, chart.width = 8, 17
    chart.add_data(Reference(dashboard, min_col=2, min_row=11, max_row=23), titles_from_data=True)
    chart.set_categories(Reference(dashboard, min_col=1, min_row=12, max_row=23))
    dashboard.add_chart(chart, "E5")
    dashboard.freeze_panes = "A5"
    dashboard.column_dimensions["A"].width = 34
    dashboard.column_dimensions["B"].width = 22
    dashboard.column_dimensions["C"].width = 92

    monthly_ws = wb.create_sheet("Monthly Summary")
    monthly_ws.append(["Month", "Calendar days to date", "Booked nights", "Gross revenue (€)", "Average nightly revenue (€)"])
    for month in range(1, 13):
        month_start = date(year, month, 1)
        month_end = date(year + (month == 12), month % 12 + 1, 1)
        period_end = min(month_end, end + timedelta(days=1))
        month_days = max(0, (period_end - month_start).days)
        month_nights = sorted(day for day in daily if day.month == month)
        revenue = monthly[month - 1]
        monthly_ws.append([month_start.strftime("%B"), month_days, len(month_nights), revenue, revenue / len(month_nights) if month_nights else 0])

    ledger = wb.create_sheet("Daily Ledger")
    ledger.append(["Night", "Weekday", "Gross revenue (€)", "Status"])
    for night in sorted(daily):
        ledger.append([night, night.strftime("%A"), daily[night], "Booked"])

    detail = wb.create_sheet("Reservations")
    detail.append(["Booking ID", "Guest", "Email", "Phone", "Check-in", "Check-out", "Nights in period", "Guests", "Nightly rate (€)", "Revenue in period (€)", "Status", "Source", "Notes"])
    for r, nights, revenue in stays:
        detail.append([r.get("id"), r.get("guest_name"), r.get("email"), r.get("phone"),
                       date.fromisoformat(r["checkin"]), date.fromisoformat(r["checkout"]), nights,
                       r.get("guests"), float(r.get("nightly_rate") or 0), revenue,
                       r.get("status"), r.get("source"), r.get("notes")])

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = "A2" if ws.title != "Revenue Dashboard" else "A5"
        ws.auto_filter.ref = ws.dimensions if ws.title != "Revenue Dashboard" and ws.max_row > 1 else None
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor=NAVY)
            cell.font = Font(color="FFFFFF", bold=True, size=11)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if cell.row % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F3F7F8")
                if isinstance(cell.value, (float, int)) and "revenue" in str(ws.cell(1, cell.column).value).lower():
                    cell.number_format = '€#,##0.00;[Red]-€#,##0.00'
        for col_cells in ws.columns:
            if not hasattr(col_cells[0], "column"):
                continue
            max_len = max((len(str(cell.value or "")) for cell in col_cells if not isinstance(cell, type(None))), default=10)
            ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(max(max_len + 2, 13), 38)
    for cell in dashboard[5]:
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.font = Font(color="FFFFFF", bold=True)
    dashboard[1][0].font = Font(size=20, color=NAVY, bold=True)
    dashboard[2][0].font = Font(size=15, color=TEAL, bold=True)
    dashboard[3][0].font = Font(italic=True, color="526676")
    dashboard.column_dimensions["A"].width = 35
    dashboard.column_dimensions["B"].width = 22
    dashboard.column_dimensions["C"].width = 92
    for ws in (monthly_ws, detail):
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if cell.is_date:
                    cell.number_format = "dd mmm yyyy"
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
             Spacer(1, 5*mm), Paragraph(property_name, styles["Heading1"]),
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
        story.append(Paragraph(f"Selected listings: {market['count']} | Median observed rate: {_money(market['median_rate'])} | Suggested rate after adjustment: {_money(market['suggested_rate'])}.", styles["Normal"]))
    comp_rows = [["Comparable", "Area", "Beds", "Nightly rate", "Observed"]]
    for c in comparables:
        if c.get("selected", 1):
            comp_rows.append([str(c.get("name",""))[:34],str(c.get("area",""))[:24],str(c.get("bedrooms","")),_money(float(c.get("nightly_rate",0))),str(c.get("observed_date",""))])
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
        booking_rows.append([str(r.get("guest_name",""))[:24], f"{r.get('checkin')} to {r.get('checkout')}", str(d.get("guests","")), _money(r["nightly_rate"]), str(r.get("status","")), str(d.get("email") or d.get("phone") or "")[:26]])
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
