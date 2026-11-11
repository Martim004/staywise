from __future__ import annotations

import calendar
from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from staywise.calculations import competitor_summary, date_ranges_overlap, validate_reservation
from staywise.database import (add_blocked_dates, add_comparable, add_reservation,
                               delete_blocked_dates, delete_comparable, delete_reservation,
                               get_blocked_dates, get_comparables,
                               get_reservations, get_settings, init_db, is_demo_mode,
                               save_settings, seed_demo_data,
                               set_comparable_selected)
from staywise.imports import export_csv, parse_booking_csv, template_csv
from staywise.inside_airbnb import LISBON_LISTINGS_URL, SOURCE_PAGE, listings_within_radius


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


def money(value: float) -> str:
    return f"€{value:,.2f}"


with st.sidebar:
    st.markdown('<div class="brand">StayWise<span style="color:#1D7A78">.</span></div>', unsafe_allow_html=True)
    st.caption("Short-stay rental studio")
    st.divider()
    page = st.radio("Workspace", ["Overview", "Bookings", "Calendar", "Market"], label_visibility="collapsed")
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


if page == "Overview":
    st.markdown('<div class="eyebrow">Your rental at a glance</div>', unsafe_allow_html=True)
    st.title(f"{settings.get('property_name','My Rental')} overview")
    st.markdown('<p class="subtle">Your rental calendar and local market context in one calm workspace.</p>', unsafe_allow_html=True)
    market = competitor_summary(comps)
    cols = st.columns(2)
    cols[0].metric("Blocked date ranges", len(blocks))
    cols[1].metric("Manual comparable median", money(market["median_rate"]) if market["median_rate"] is not None else "—")
    st.info("Use the Calendar to see availability by day, or Market to compare nearby Lisbon Airbnb listings by radius.")


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
    st.markdown("<div class='legend'><span><i class='dot available'></i>Available</span><span><i class='dot booked'></i>Booked</span><span><i class='dot blocked'></i>Blocked</span></div>", unsafe_allow_html=True)
    st.markdown("""<style>
    .calendar-grid{display:grid;grid-template-columns:repeat(7,minmax(75px,1fr));gap:8px;margin-top:10px}
    .weekday{color:#647787;font-size:12px;font-weight:700;text-align:center;padding:6px}
    .day-card{min-height:76px;border:1px solid #e2e9eb;border-radius:12px;padding:9px;background:#fff;color:#17324d}
    .day-card.empty{background:transparent;border:0}.day-number{font-size:17px;font-weight:700}
    .day-state{font-size:11px;font-weight:700;margin-top:12px;display:inline-flex;padding:4px 8px;border-radius:20px}
    .day-card.available{background:#f2faf6;border-color:#d5eee1}.available .day-state{color:#216c4c;background:#dcf3e6}
    .day-card.booked{background:#f1f5ff;border-color:#dbe4ff}.booked .day-state{color:#3d58a4;background:#e2e9ff}
    .day-card.blocked{background:#fff7ed;border-color:#ffdfbd}.blocked .day-state{color:#9a571a;background:#ffead2}
    .legend{display:flex;gap:20px;color:#526676;font-size:13px}.legend span{display:flex;align-items:center;gap:7px}
    .dot{width:10px;height:10px;border-radius:50%;display:inline-block}.dot.available{background:#48a778}.dot.booked{background:#657bd0}.dot.blocked{background:#e59648}
    @media(max-width:700px){.calendar-grid{gap:4px}.day-card{min-height:58px;padding:5px}.day-state{font-size:9px;padding:3px 5px}}
    </style>""", unsafe_allow_html=True)
    html = ["<div class='calendar-grid'>"]
    html.extend(f"<div class='weekday'>{d}</div>" for d in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])
    matrix = calendar.monthcalendar(year, month)
    for week in matrix:
        for day in week:
            if day == 0:
                html.append("<div class='day-card empty'></div>")
                continue
            current = date(year,month,day)
            booking = next((r for r in reservations if r["status"] in {"confirmed","completed"} and date.fromisoformat(r["checkin"]) <= current < date.fromisoformat(r["checkout"])), None)
            blocked = next((b for b in blocks if date.fromisoformat(b["start_date"]) <= current < date.fromisoformat(b["end_date"])), None)
            status = "booked" if booking else "blocked" if blocked else "available"
            label = "Booked" if booking else "Blocked" if blocked else "Available"
            hint = escape(booking["guest_name"]) if booking else escape(blocked.get("reason") or "Unavailable") if blocked else "Open night"
            html.append(f"<div class='day-card {status}' title='{hint}'><div class='day-number'>{day}</div><span class='day-state'>{label}</span></div>")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption("Booked and blocked dates are exclusive of each checkout/end date. Use Bookings → Block dates to mark owner stays or maintenance.")


elif page == "Market":
    st.markdown('<div class="eyebrow">Know your neighborhood</div>', unsafe_allow_html=True)
    st.title("Market & property")
    st.markdown('<p class="subtle">Compare nearby Lisbon Airbnb listings from Inside Airbnb, filtered by your chosen radius and property size. You can also add manually observed Booking.com or other listings.</p>', unsafe_allow_html=True)
    with st.expander("Property and search location", expanded=not settings.get("property_area")):
        with st.form("property_settings"):
            c1,c2,c3 = st.columns(3)
            property_name = c1.text_input("Property name", settings.get("property_name","My Rental"))
            area = c2.text_input("Area / neighborhood", settings.get("property_area",""))
            bedrooms = c3.number_input("Bedrooms", min_value=0, max_value=30, value=int(settings.get("bedrooms",2)))
            c1,c2,c3 = st.columns(3)
            capacity = c1.number_input("Guest capacity", min_value=1, max_value=100, value=int(settings.get("capacity",4)))
            latitude = c2.number_input("Latitude", min_value=-90.0, max_value=90.0, value=float(settings.get("latitude",38.719)), format="%.6f")
            longitude = c3.number_input("Longitude", min_value=-180.0, max_value=180.0, value=float(settings.get("longitude",-9.165)), format="%.6f")
            st.caption("The default map point is approximate for Campo de Ourique. Set your home's coordinates for the most accurate radius search.")
            if st.form_submit_button("Save property settings", type="primary", disabled=READ_ONLY):
                save_settings({"property_name":property_name,"property_area":area,"bedrooms":bedrooms,"capacity":capacity,
                               "latitude":latitude,"longitude":longitude})
                st.success("Property settings saved."); st.rerun()

    st.subheader("Nearby Airbnb market · Inside Airbnb")
    radius_km = st.slider("Search radius", min_value=0.2, max_value=10.0, value=2.0, step=0.2, format="%.1f km")
    bedrooms_only = st.checkbox("Match bedroom count", value=True)
    capacity_match = st.checkbox("Include listings that accommodate my guest capacity", value=False)
    airbnb_adjustment = st.slider("Suggested rate adjustment from local Airbnb median", -30, 30, 0, 1, format="%d%%", key="airbnb_adjust")
    @st.cache_data(ttl=86400, show_spinner=False)
    def load_inside_airbnb(url: str) -> pd.DataFrame:
        return pd.read_csv(url, compression="gzip", low_memory=False)
    load_requested = st.button("Load / refresh Airbnb comparables", type="primary")
    if load_requested:
        st.session_state["inside_airbnb_loaded"] = True
        load_inside_airbnb.clear()
    if st.session_state.get("inside_airbnb_loaded"):
        with st.spinner("Loading the latest configured Lisbon snapshot from Inside Airbnb…"):
            try:
                source_data = load_inside_airbnb(LISBON_LISTINGS_URL)
                nearby = listings_within_radius(
                    source_data, float(settings.get("latitude",38.719)), float(settings.get("longitude",-9.165)),
                    radius_km, int(settings.get("bedrooms",2)) if bedrooms_only else None,
                    int(settings.get("capacity",4)) if capacity_match else None,
                )
                st.caption(f"Source snapshot: 19 September 2026 · {len(nearby):,} matches · distances are straight-line from your saved coordinates. Prices and availability are source data, not live quotes.")
                if len(nearby):
                    m1,m2,m3,m4,m5 = st.columns(5)
                    m1.metric("Nearby listings", f"{len(nearby):,}")
                    m2.metric("Median nightly price", money(float(nearby["price"].median())))
                    m3.metric("25th–75th percentile", f"{money(float(nearby['price'].quantile(.25)))}–{money(float(nearby['price'].quantile(.75)))}")
                    rating_col = "review_scores_rating" if "review_scores_rating" in nearby else None
                    m4.metric("Median review score", f"{nearby[rating_col].median():.1f}/5" if rating_col and nearby[rating_col].notna().any() else "—")
                    suggested = float(nearby["price"].median()) * (1 + airbnb_adjustment / 100)
                    m5.metric("Suggested nightly rate", money(suggested), help="Filtered Airbnb median adjusted by your chosen percentage")
                    st.caption("Rate guide: the nearby median is a simple benchmark. It does not account for date-specific demand, quality, fees, or Booking.com inventory.")
                    price_frame = nearby["price"].dropna().clip(upper=nearby["price"].quantile(.95))
                    st.bar_chart(price_frame.value_counts(bins=12, sort=False).sort_index(), height=190, color="#1D7A78")
                    visible = [c for c in ["name","neighbourhood_cleansed","room_type","bedrooms","accommodates","price","review_scores_rating","number_of_reviews","availability_365","distance_km","listing_url"] if c in nearby]
                    st.dataframe(nearby[visible].rename(columns={"name":"Listing","neighbourhood_cleansed":"Neighborhood","room_type":"Room type","bedrooms":"Beds","accommodates":"Guests","price":"Nightly price (€)","review_scores_rating":"Rating","number_of_reviews":"Reviews","availability_365":"Available days / 365","distance_km":"Distance (km)","listing_url":"Listing URL"}).round(2), width="stretch", hide_index=True)
                    st.download_button("Download filtered Airbnb comparables CSV", nearby[visible].to_csv(index=False).encode("utf-8"), "staywise-lisbon-airbnb-comparables.csv", "text/csv")
                else:
                    st.info("No Airbnb listings matched this radius and property filter. Try a wider radius or turn off a size filter.")
            except Exception as exc:
                st.error(f"Could not load the Inside Airbnb Lisbon snapshot: {exc}")
                st.caption("Check the source page for current data files or try again later.")
    else:
        st.caption("Load the public listing snapshot when you want to refresh your comparison. The download is cached for 24 hours.")
    st.markdown(f"Data: [Inside Airbnb Lisbon listings]({SOURCE_PAGE}). This public dataset contains Airbnb listings only; Booking.com prices are not supplied.")
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
