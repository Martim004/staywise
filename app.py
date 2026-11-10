from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from staywise.calculations import calculate_forecast, competitor_summary, date_ranges_overlap, validate_reservation
from staywise.database import (add_blocked_dates, add_comparable, add_reservation, database_path,
                               delete_blocked_dates, delete_comparable, delete_reservation,
                               get_blocked_dates, get_comparables, get_monthly_assumptions,
                               get_reservations, get_settings, init_db, is_demo_mode,
                               save_monthly_assumptions, save_settings, seed_demo_data,
                               set_comparable_selected)
from staywise.imports import export_csv, parse_booking_csv, template_csv
from staywise.reports import build_excel_report, build_pdf_report


st.set_page_config(page_title="StayWise | Rental studio", page_icon="🏡", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
html, body, [class*="css"] {font-family:'DM Sans',sans-serif;}
h1,h2,h3 {font-family:'Manrope',sans-serif; color:#17324D;}
.stApp {background:#F6F8F8;}
div[data-testid="stMetric"] {background:#fff;border:1px solid #E3EAED;padding:16px 18px;border-radius:14px;box-shadow:0 4px 14px #17324d08;}
div[data-testid="stMetricLabel"] {color:#526676;}
.brand {font-family:Manrope,sans-serif;font-size:24px;font-weight:800;color:#17324D;letter-spacing:-.7px;}
.eyebrow {text-transform:uppercase;letter-spacing:1.5px;font-size:11px;font-weight:700;color:#1D7A78;margin-bottom:4px;}
.subtle {color:#657987;font-size:14px;}
div[data-testid="stForm"] {background:white;padding:18px;border:1px solid #E3EAED;border-radius:14px;}
</style>
""", unsafe_allow_html=True)

init_db()
if is_demo_mode():
    seed_demo_data()
READ_ONLY = is_demo_mode()

settings = get_settings()
reservations = get_reservations()
blocks = get_blocked_dates()
comps = get_comparables()
assumptions = get_monthly_assumptions()


def forecast_for(year: int):
    details = [r for r in reservations if r["status"] in {"confirmed", "completed"}]
    result = calculate_forecast(year, reservations, blocks, assumptions,
                                float(settings.get("platform_fee_percent", 0)),
                                float(settings.get("monthly_operating_cost", 0)))
    result["reservation_details"] = details
    return result


def money(value: float) -> str:
    return f"€{value:,.2f}"


with st.sidebar:
    st.markdown('<div class="brand">StayWise<span style="color:#1D7A78">.</span></div>', unsafe_allow_html=True)
    st.caption("Short-stay rental studio")
    st.divider()
    page = st.radio("Workspace", ["Overview", "Bookings", "Calendar", "Market", "Forecast", "Reports"], label_visibility="collapsed")
    st.divider()
    st.markdown(f"**{settings.get('property_name','My Rental')}**")
    st.caption(settings.get("property_area") or "Add a location in Market settings")
    if is_demo_mode():
        st.info("Public demo · fictional records only · read-only", icon="🧪")
    else:
        st.caption("Private local database")
    st.caption("EUR · English")

if READ_ONLY:
    st.warning("This public demo is read-only and contains fictional records. Run StayWise locally to add or import real guest details.", icon="🔒")


year_default = date.today().year
if page == "Overview":
    st.markdown('<div class="eyebrow">Your rental at a glance</div>', unsafe_allow_html=True)
    st.title(f"{settings.get('property_name','My Rental')} overview")
    st.markdown('<p class="subtle">Booking activity, forward revenue, and pricing context in one calm workspace.</p>', unsafe_allow_html=True)
    year = st.selectbox("Report year", list(range(year_default - 1, year_default + 4)), index=1, key="overview_year")
    forecast = forecast_for(year)
    current_bookings = [r for r in reservations if r["status"] == "confirmed"]
    market = competitor_summary(comps)
    cols = st.columns(4)
    cols[0].metric("Gross revenue outlook", money(forecast["gross_revenue"]), help="Booked revenue plus estimated future bookings")
    cols[1].metric("Estimated net", money(forecast["estimated_net"]), help="After entered fees and operating costs; taxes excluded")
    cols[2].metric("Confirmed stays", f"{len(current_bookings)}", help="Reservations currently marked confirmed")
    cols[3].metric("Comparable median", money(market["median_rate"]) if market["median_rate"] is not None else "—", help="Selected, user-entered listing observations")
    left, right = st.columns([1.65,1])
    with left:
        st.subheader("Revenue outlook")
        chart = pd.DataFrame([{"Month":r["month_name"],"Booked":r["booked_revenue"],"Estimated":r["forecast_revenue"]} for r in forecast["months"]]).set_index("Month")
        st.bar_chart(chart, color=["#1D7A78", "#B9D9D2"], height=300)
    with right:
        st.subheader("Coming up")
        upcoming = sorted([r for r in reservations if r["status"] == "confirmed" and r["checkout"] >= date.today().isoformat()], key=lambda r:r["checkin"])[:5]
        if upcoming:
            for r in upcoming:
                st.markdown(f"**{r['guest_name']}** · {r['checkin']} → {r['checkout']}  \n{r['guests']} guests · {money(float(r['nightly_rate']))}/night")
                st.divider()
        else:
            st.caption("No upcoming confirmed stays yet.")
    st.caption(f"Forecast uses monthly occupancy and rate assumptions. Taxes are excluded. Database: `{database_path()}`")


elif page == "Bookings":
    st.markdown('<div class="eyebrow">Guest and stay records</div>', unsafe_allow_html=True)
    st.title("Bookings")
    st.markdown('<p class="subtle">Keep reservations, contact details, and owner-blocked dates together. Dates are check-in inclusive and check-out exclusive.</p>', unsafe_allow_html=True)
    tab_add, tab_import, tab_block, tab_list = st.tabs(["Add booking", "Import CSV", "Block dates", "All bookings"])
    with tab_add:
        with st.form("new_booking", clear_on_submit=True):
            c1,c2,c3 = st.columns(3)
            name = c1.text_input("Guest name *")
            email = c2.text_input("Email")
            phone = c3.text_input("Phone")
            c1,c2,c3,c4 = st.columns(4)
            checkin = c1.date_input("Check-in", value=date.today()+timedelta(days=14))
            checkout = c2.date_input("Check-out", value=date.today()+timedelta(days=17))
            guests = c3.number_input("Guests", min_value=1, max_value=30, value=2)
            rate = c4.number_input("Nightly rate (€)", min_value=0.0, value=120.0, step=5.0)
            c1,c2 = st.columns(2)
            source = c1.selectbox("Booking source", ["Airbnb", "Booking.com", "Direct", "Other"])
            status = c2.selectbox("Status", ["confirmed", "completed", "cancelled"])
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Save booking", type="primary", disabled=READ_ONLY)
        if submitted:
            item = {"guest_name":name,"email":email,"phone":phone,"checkin":checkin.isoformat(),"checkout":checkout.isoformat(),
                    "guests":int(guests),"nightly_rate":float(rate),"status":status,"source":source,"notes":notes}
            errors = validate_reservation(item, reservations, blocks)
            if errors:
                for error in errors: st.error(error)
            else:
                add_reservation(item)
                st.success("Booking saved.")
                st.rerun()
    with tab_import:
        st.download_button("Download CSV template", template_csv(), "staywise-bookings-template.csv", "text/csv")
        if READ_ONLY:
            st.info("CSV uploads are disabled in the public demo so guest contact data cannot be submitted to the shared app.")
            upload = None
        else:
            st.caption("Use ISO dates (YYYY-MM-DD). Each row must include all template columns. Rows with errors are skipped; overlaps with existing or earlier imported bookings are rejected.")
            upload = st.file_uploader("Upload booking CSV", type=["csv"])
        if upload:
            accepted, errors = parse_booking_csv(upload.getvalue(), reservations, blocks)
            st.write(f"Valid rows: **{len(accepted)}** · Rows with errors: **{len(errors)}**")
            if accepted:
                st.dataframe(pd.DataFrame(accepted), width="stretch", hide_index=True)
                if st.button(f"Import {len(accepted)} valid booking(s)", type="primary", disabled=READ_ONLY):
                    for item in accepted: add_reservation(item)
                    st.success(f"Imported {len(accepted)} booking(s).")
                    st.rerun()
            if errors:
                with st.expander("Review import errors", expanded=True):
                    for error in errors: st.error(error)
    with tab_block:
        st.write("Block owner stays, maintenance, or other unavailable nights.")
        with st.form("block_dates", clear_on_submit=True):
            c1,c2,c3 = st.columns([1,1,2])
            block_start = c1.date_input("Start date", key="block_start")
            block_end = c2.date_input("End date (checkout)", value=date.today()+timedelta(days=1), key="block_end")
            reason = c3.text_input("Reason")
            block_submit = st.form_submit_button("Block dates", disabled=READ_ONLY)
        if block_submit:
            if block_end <= block_start:
                st.error("End date must be after the start date.")
            elif any(date_ranges_overlap(block_start, block_end, date.fromisoformat(r["checkin"]), date.fromisoformat(r["checkout"])) for r in reservations if r["status"] in {"confirmed","completed"}):
                st.error("These dates overlap an active reservation.")
            elif any(date_ranges_overlap(block_start, block_end, date.fromisoformat(b["start_date"]), date.fromisoformat(b["end_date"])) for b in blocks):
                st.error("These dates overlap an existing blocked period.")
            else:
                add_blocked_dates(block_start.isoformat(),block_end.isoformat(),reason)
                st.success("Dates blocked.")
                st.rerun()
        if blocks:
            for b in blocks:
                c1,c2 = st.columns([5,1])
                c1.write(f"{b['start_date']} → {b['end_date']} · {b['reason'] or 'Unavailable'}")
                if c2.button("Remove", key=f"del_block_{b['id']}", disabled=READ_ONLY):
                    delete_blocked_dates(b["id"]); st.rerun()
    with tab_list:
        if reservations:
            st.download_button("Export bookings CSV", export_csv(reservations), "staywise-bookings.csv", "text/csv")
            table = pd.DataFrame(reservations)
            st.dataframe(table[["id","guest_name","email","phone","checkin","checkout","guests","nightly_rate","status","source","notes"]], width="stretch", hide_index=True)
            delete_id = st.selectbox("Delete booking", [r["id"] for r in reservations], format_func=lambda rid: next(f"#{r['id']} · {r['guest_name']} · {r['checkin']}" for r in reservations if r["id"]==rid))
            if st.button("Delete selected booking", type="secondary", disabled=READ_ONLY):
                delete_reservation(delete_id); st.rerun()
        else:
            st.info("No bookings yet. Add one or import the CSV template.")


elif page == "Calendar":
    st.markdown('<div class="eyebrow">Availability at a glance</div>', unsafe_allow_html=True)
    st.title("Calendar")
    now = date.today()
    c1,c2 = st.columns(2)
    month = c1.selectbox("Month", range(1,13), index=now.month-1, format_func=lambda m:calendar.month_name[m])
    year = c2.selectbox("Year", range(now.year-1,now.year+4), index=1)
    matrix = calendar.monthcalendar(year, month)
    display = []
    for week in matrix:
        row=[]
        for day in week:
            if day == 0:
                row.append("")
                continue
            current = date(year,month,day)
            mark = ""
            for r in reservations:
                if r["status"] in {"confirmed","completed"} and date.fromisoformat(r["checkin"]) <= current < date.fromisoformat(r["checkout"]):
                    mark = "BOOKED"
                    break
            if not mark:
                for b in blocks:
                    if date.fromisoformat(b["start_date"]) <= current < date.fromisoformat(b["end_date"]):
                        mark = "BLOCKED"
                        break
            row.append(f"{day}" + (f"\n{mark}" if mark else "\nAvailable"))
        display.append(row)
    st.dataframe(pd.DataFrame(display, columns=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]), width="stretch", hide_index=True, height=250)
    st.caption("Booked and blocked dates are exclusive of each checkout/end date. Use Bookings → Block dates to mark owner stays or maintenance.")


elif page == "Market":
    st.markdown('<div class="eyebrow">Know your neighborhood</div>', unsafe_allow_html=True)
    st.title("Market & property")
    st.markdown('<p class="subtle">Record comparable homes you have checked. StayWise does not scrape Airbnb or Booking.com.</p>', unsafe_allow_html=True)
    with st.expander("Property and cost settings", expanded=not settings.get("property_area")):
        with st.form("property_settings"):
            c1,c2,c3 = st.columns(3)
            property_name = c1.text_input("Property name", settings.get("property_name","My Rental"))
            area = c2.text_input("Area / neighborhood", settings.get("property_area",""))
            bedrooms = c3.number_input("Bedrooms", min_value=0, max_value=30, value=int(settings.get("bedrooms",2)))
            c1,c2,c3 = st.columns(3)
            capacity = c1.number_input("Guest capacity", min_value=1, max_value=100, value=int(settings.get("capacity",4)))
            fee = c2.number_input("Platform fee (%)", min_value=0.0, max_value=100.0, value=float(settings.get("platform_fee_percent",14)), step=0.5)
            costs = c3.number_input("Operating costs per month (€)", min_value=0.0, value=float(settings.get("monthly_operating_cost",250)), step=25.0)
            if st.form_submit_button("Save property settings", type="primary", disabled=READ_ONLY):
                save_settings({"property_name":property_name,"property_area":area,"bedrooms":bedrooms,"capacity":capacity,
                               "platform_fee_percent":fee,"monthly_operating_cost":costs})
                st.success("Property settings saved."); st.rerun()
    st.subheader("Add a comparable listing")
    with st.form("add_comp", clear_on_submit=True):
        c1,c2,c3 = st.columns(3)
        comp_name = c1.text_input("Listing label *")
        comp_area = c2.text_input("Area")
        observed = c3.date_input("Date observed", value=date.today())
        c1,c2,c3,c4 = st.columns(4)
        comp_beds = c1.number_input("Bedrooms", min_value=0, max_value=30, value=max(1,int(settings.get("bedrooms",2))))
        comp_capacity = c2.number_input("Capacity", min_value=1, max_value=100, value=max(1,int(settings.get("capacity",4))))
        distance = c3.number_input("Distance from your home (km)", min_value=0.0, value=0.5, step=0.1)
        comp_rate = c4.number_input("Observed nightly rate (€)", min_value=0.0, value=140.0, step=5.0)
        url = st.text_input("Listing URL (optional)")
        comp_notes = st.text_input("Notes: amenities, size, or other differences")
        comp_submit = st.form_submit_button("Add comparison", type="primary", disabled=READ_ONLY)
    if comp_submit:
        if not comp_name.strip() or comp_rate <= 0:
            st.error("Enter a listing label and a price above zero.")
        else:
            add_comparable({"name":comp_name.strip(),"area":comp_area.strip(),"bedrooms":int(comp_beds),"capacity":int(comp_capacity),
                            "distance_km":float(distance),"nightly_rate":float(comp_rate),"observed_date":observed.isoformat(),
                            "url":url.strip(),"notes":comp_notes,"selected":1})
            st.success("Comparable saved."); st.rerun()
    st.subheader("Selected price benchmark")
    adjust = st.slider("Suggested rate adjustment", min_value=-30, max_value=30, value=0, step=1, format="%d%%")
    market = competitor_summary(comps, adjust)
    c1,c2,c3 = st.columns(3)
    c1.metric("Selected listings", market["count"])
    c2.metric("Median observed rate", money(market["median_rate"]) if market["median_rate"] is not None else "—")
    c3.metric("Suggested rate", money(market["suggested_rate"]) if market["suggested_rate"] is not None else "—", help="Median × (1 + your selected adjustment)")
    if comps:
        for c in comps:
            left,right = st.columns([7,1])
            selected = left.checkbox(f"**{c['name']}** · {c['area']} · {c['bedrooms']} bed · {money(float(c['nightly_rate']))}/night · observed {c['observed_date']}", value=bool(c["selected"]), key=f"comp_{c['id']}", disabled=READ_ONLY)
            if selected != bool(c["selected"]):
                set_comparable_selected(c["id"],selected); st.rerun()
            if right.button("Delete", key=f"del_comp_{c['id']}", disabled=READ_ONLY):
                delete_comparable(c["id"]); st.rerun()
            if c.get("notes"): st.caption(c["notes"])
    else:
        st.info("Add a few nearby homes with similar bedrooms and capacity to create a useful benchmark.")


elif page == "Forecast":
    st.markdown('<div class="eyebrow">Plan the year ahead</div>', unsafe_allow_html=True)
    st.title("Revenue forecast")
    st.markdown('<p class="subtle">Confirmed stays are counted first. Monthly occupancy targets fill only the remaining available nights.</p>', unsafe_allow_html=True)
    year = st.selectbox("Forecast year", list(range(year_default - 1, year_default + 5)), index=1, key="forecast_year")
    st.subheader("Monthly assumptions")
    months_table = pd.DataFrame([{"Month":calendar.month_name[m],"Occupancy target (%)":assumptions[m]["occupancy_percent"],"Expected rate (€)":assumptions[m]["nightly_rate"]} for m in range(1,13)])
    edited = st.data_editor(months_table, hide_index=True, width="stretch", num_rows="fixed",
                            column_config={"Occupancy target (%)":st.column_config.NumberColumn(min_value=0,max_value=100,step=1),
                                           "Expected rate (€)":st.column_config.NumberColumn(min_value=0,step=5,format="€%.2f")})
    if st.button("Save monthly assumptions", type="primary", disabled=READ_ONLY):
        values = {m+1:{"occupancy_percent":float(edited.iloc[m]["Occupancy target (%)"]),"nightly_rate":float(edited.iloc[m]["Expected rate (€)"])} for m in range(12)}
        if any(not 0 <= v["occupancy_percent"] <= 100 or v["nightly_rate"] < 0 for v in values.values()):
            st.error("Occupancy must be 0–100% and rates cannot be negative.")
        else:
            save_monthly_assumptions(values); st.success("Assumptions saved."); st.rerun()
    forecast = forecast_for(year)
    st.subheader(f"{year} estimate")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Gross revenue",money(forecast["gross_revenue"]))
    c2.metric("Platform fees",money(forecast["platform_fees"]))
    c3.metric("Operating costs",money(forecast["operating_costs"]))
    c4.metric("Estimated net",money(forecast["estimated_net"]))
    st.caption(f"{forecast['booked_nights']} booked nights + {forecast['forecast_nights']} estimated nights · {forecast['blocked_nights']} blocked nights excluded. Taxes are not included.")
    st.dataframe(pd.DataFrame(forecast["months"])[["month_name","days","booked_nights","blocked_nights","forecast_nights","assumed_occupancy_percent","assumed_nightly_rate","booked_revenue","forecast_revenue","gross_revenue"]], width="stretch", hide_index=True,
                 column_config={"booked_revenue":st.column_config.NumberColumn("Booked revenue",format="€%.2f"),"forecast_revenue":st.column_config.NumberColumn("Future estimate",format="€%.2f"),"gross_revenue":st.column_config.NumberColumn("Gross total",format="€%.2f"),"assumed_nightly_rate":st.column_config.NumberColumn("Assumed rate",format="€%.2f")})


elif page == "Reports":
    st.markdown('<div class="eyebrow">Beautiful, useful exports</div>', unsafe_allow_html=True)
    st.title("Reports")
    st.markdown('<p class="subtle">Create a year-specific report for planning, accounting discussions, or a property review.</p>', unsafe_allow_html=True)
    year = st.selectbox("Report year", list(range(year_default - 1, year_default + 5)), index=1, key="report_year")
    adjustment = st.slider("Pricing suggestion adjustment", -30, 30, 0, 1, format="%d%%", key="report_adjust")
    forecast = forecast_for(year)
    market = competitor_summary(comps,adjustment)
    st.markdown(f"### {settings.get('property_name','My Rental')} · {year}")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Gross",money(forecast["gross_revenue"]))
    c2.metric("Estimated net",money(forecast["estimated_net"]))
    c3.metric("Booked nights",forecast["booked_nights"])
    c4.metric("Future estimate nights",forecast["forecast_nights"])
    detail = [r for r in reservations if r["status"] in {"confirmed","completed"}]
    forecast["reservation_details"] = detail
    excel = build_excel_report(settings.get("property_name","My Rental"),forecast,comps,settings)
    pdf = build_pdf_report(settings.get("property_name","My Rental"),forecast,comps,settings,market)
    c1,c2 = st.columns(2)
    c1.download_button("Download Excel workbook",excel,f"staywise-{year}-report.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",type="primary",width="stretch")
    c2.download_button("Download polished PDF",pdf,f"staywise-{year}-report.pdf","application/pdf",width="stretch")
    with st.expander("What the forecast includes"):
        st.write("Gross revenue combines confirmed or completed reservation revenue with estimated nights based on your monthly occupancy and rate assumptions. Confirmed nights count toward the occupancy target, and owner-blocked nights are removed from future availability. Estimated net subtracts your entered platform fee percentage and monthly operating cost. Taxes are excluded. Competitor rates are observations you enter manually; they are not live prices.")
