from __future__ import annotations

import calendar
import math
from datetime import date, timedelta
from html import escape

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from staywise.calculations import competitor_summary, date_ranges_overlap, validate_reservation
from staywise.auth import auth_is_configured, current_user, sign_in, sign_out
from staywise.database import (add_blocked_dates, add_comparable, add_property, add_reservation,
                               delete_blocked_dates, delete_comparable, delete_property, delete_reservation,
                               get_blocked_dates, get_comparables,
                               get_properties, get_reservations, get_settings, init_db, is_demo_mode,
                               save_user_profile, set_authenticated_user, update_property,
                               set_comparable_selected)
from staywise.imports import export_csv, parse_booking_csv, template_csv
from staywise.inside_airbnb import LISBON_LISTINGS_URL, SOURCE_PAGE, listings_within_radius
from staywise.postgres_store import database_urls, load_latest_snapshot, save_latest_snapshot
from staywise.reports import build_revenue_workbook


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
.revenue-hero {position:relative;overflow:hidden;background:radial-gradient(circle at 88% 16%,#4b9c8c 0,transparent 28%),linear-gradient(120deg,#17324D,#145F5D);color:#fff;border-radius:24px;padding:28px 32px;margin:10px 0 18px;box-shadow:0 14px 34px #17324d20;}
.revenue-hero:after {content:'';position:absolute;width:210px;height:210px;border:1px solid #ffffff26;border-radius:50%;right:8%;top:-118px;box-shadow:0 0 0 28px #ffffff09,0 0 0 58px #ffffff07;pointer-events:none;}
.revenue-hero-label {font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#c4e6dc;}
.revenue-hero-value {font-family:Manrope,sans-serif;font-size:42px;font-weight:800;letter-spacing:-1.5px;line-height:1.2;margin:8px 0 2px;}
.revenue-hero-note {font-size:14px;color:#d3e6e3;}
.revenue-hero-badge {display:inline-block;padding:7px 11px;border-radius:999px;background:#ffffff18;border:1px solid #ffffff28;font-size:12px;color:#effaf6;margin-top:16px;}
.revenue-kpi {height:100%;min-height:112px;background:#fff;border:1px solid #e3eaed;border-radius:18px;padding:18px 20px;box-shadow:0 6px 20px #17324d08;}
.revenue-kpi-label {font-size:13px;font-weight:600;color:#657987;}
.revenue-kpi-value {font-family:Manrope,sans-serif;font-size:26px;font-weight:800;letter-spacing:-.5px;color:#17324d;margin-top:9px;}
.revenue-kpi-note {font-size:12px;color:#82919a;margin-top:3px;}
.revenue-chart-card {background:#fff;border:1px solid #e3eaed;border-radius:20px;padding:20px 22px 10px;box-shadow:0 6px 20px #17324d08;margin-top:18px;}
.revenue-chart-title {font-family:Manrope,sans-serif;font-size:17px;font-weight:700;color:#17324d;margin-bottom:2px;}
.revenue-chart-subtitle {font-size:12px;color:#82919a;margin-bottom:12px;}
.revenue-chart-svg {display:block;width:100%;height:auto;}
.revenue-section-title {font-family:Manrope,sans-serif;font-size:17px;font-weight:700;color:#17324d;margin:22px 0 4px;}
.revenue-empty {background:#fff;border:1px dashed #cbd8dc;border-radius:16px;padding:22px;color:#657987;text-align:center;}
</style>
""", unsafe_allow_html=True)

DEMO_PROPERTY_NAME = "Casa T2 do Campo de Ourique"
DEMO_PROPERTY_ALIASES = {
    DEMO_PROPERTY_NAME,
    "Campo de Ourique T2 · fictional example",
    "Campo de Ourique T2 (demo)",
}


def ensure_public_demo_example() -> None:
    """Create the fictional Campo example and its demo records in this session's DB."""
    homes = get_properties()
    sample = next((p for p in homes if p["name"] in DEMO_PROPERTY_ALIASES), None)
    if sample is None:
        sample_id = add_property({
            "name": DEMO_PROPERTY_NAME, "area": "Campo de Ourique, Lisbon · fictional sample area",
            "bedrooms": 2, "capacity": 4, "latitude": 38.719, "longitude": -9.165,
            "airbnb_url": "", "booking_url": "",
        })
        sample = next(p for p in get_properties() if p["id"] == sample_id)
    property_id = int(sample["id"])
    if sample["name"] != DEMO_PROPERTY_NAME:
        update_property(property_id, {**sample, "name": DEMO_PROPERTY_NAME,
                                       "area": "Campo de Ourique, Lisbon · fictional sample area",
                                       "bedrooms": 2, "capacity": 4})

    if not get_reservations(property_id):
        today = date.today()
        guest_names = ["Alex Example", "Jamie Sample", "Taylor Demo", "Morgan Fiction", "Riley Sample"]
        stay_number = 0
        for month in range(1, 13):
            month_start = date(today.year, month, 1)
            month_days = calendar.monthrange(today.year, month)[1]
            for offset in range(0, month_days, 5):
                checkin = month_start + timedelta(days=offset)
                checkout = checkin + timedelta(days=min(3, month_days - offset))
                stay_number += 1
                add_reservation({
                    "guest_name": guest_names[stay_number % len(guest_names)],
                    "email": f"guest{stay_number}@example.test", "phone": "+351 900 000 000",
                    "checkin": checkin.isoformat(), "checkout": checkout.isoformat(), "guests": 2,
                    "nightly_rate": 150 if month in {6, 7, 8, 9} else 112,
                    "status": "completed" if checkout <= today else "confirmed",
                    "source": "Airbnb (fictional sample)",
                    "notes": "Fictional sample booking for demonstration; not a real guest.",
                    "property_id": property_id,
                })

    if not get_blocked_dates(property_id):
        blocked_start = date.today() + timedelta(days=70)
        add_blocked_dates(blocked_start.isoformat(), (blocked_start + timedelta(days=3)).isoformat(),
                          "Sample owner stay · fictional", property_id)

    if not get_comparables(property_id):
        for name, distance, rate in [
            ("Fictional T2 with balcony", 0.4, 138),
            ("Fictional renovated T2", 0.8, 152),
            ("Fictional courtyard apartment", 1.1, 145),
        ]:
            add_comparable({
                "name": name, "area": "Campo de Ourique · fictional sample",
                "bedrooms": 2, "capacity": 4, "distance_km": distance,
                "nightly_rate": rate, "observed_date": date.today().isoformat(), "url": "",
                "notes": "Fictional comparison for demonstration; not a real listing.",
                "selected": 1, "property_id": property_id,
            })


auth_user = current_user() if auth_is_configured() else None
set_authenticated_user(auth_user["id"] if auth_user else None)
public_demo = is_demo_mode() and auth_user is None
if auth_is_configured() and not auth_user and not is_demo_mode():
    st.markdown('<div class="brand">StayWise<span style="color:#1D7A78">.</span></div>', unsafe_allow_html=True)
    st.title("Sign in to StayWise")
    st.write("Your rental portfolio is private to your account. Continue with Google to open it.")
    if st.button("Continue with Google", type="primary"):
        sign_in()
    st.stop()

try:
    init_db()
    if auth_user:
        save_user_profile(auth_user)
except Exception as exc:
    st.error("StayWise could not open its private Supabase data store. Check the Supabase database settings and apply the account migration.")
    st.caption(f"Details: {type(exc).__name__}")
    st.stop()

READ_ONLY = public_demo
if public_demo:
    ensure_public_demo_example()

settings = get_settings()
properties = get_properties()
if "pending_property_id" in st.session_state:
    st.session_state["selected_property_id"] = st.session_state.pop("pending_property_id")
if public_demo and not st.session_state.get("demo_sample_defaulted"):
    demo_home = next((p for p in properties if p["name"] == DEMO_PROPERTY_NAME), None)
    if demo_home:
        st.session_state["selected_property_id"] = demo_home["id"]
        st.session_state["demo_sample_defaulted"] = True

if not properties:
    st.markdown('<div class="brand">StayWise<span style="color:#1D7A78">.</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">Portfolio setup</div>', unsafe_allow_html=True)
    st.title("Add your first rental")
    intro = ("Start with a property profile, then explore its calendar, market map, and revenue workspace. "
             "This public walkthrough keeps fictional details in your browser session; guest records stay disabled." if public_demo
             else "Create your first rental profile to start a private portfolio. Your data is saved in your Supabase account.")
    st.markdown(f'<p class="subtle">{intro}</p>', unsafe_allow_html=True)
    with st.form("first_demo_property", clear_on_submit=True):
        p1, p2, p3 = st.columns(3)
        new_name = p1.text_input("Property name *", placeholder="e.g. Lisbon City Apartment")
        new_area = p2.text_input("Area / neighborhood", placeholder="e.g. Campo de Ourique, Lisbon")
        new_bedrooms = p3.number_input("Bedrooms", min_value=0, max_value=30, value=2)
        p1, p2, p3 = st.columns(3)
        new_capacity = p1.number_input("Guest capacity", min_value=1, max_value=100, value=4)
        new_lat = p2.number_input("Latitude", min_value=-90.0, max_value=90.0, value=38.719, format="%.6f")
        new_lon = p3.number_input("Longitude", min_value=-180.0, max_value=180.0, value=-9.165, format="%.6f")
        p1, p2 = st.columns(2)
        new_airbnb = p1.text_input("Airbnb listing URL")
        new_booking = p2.text_input("Booking.com listing URL")
        if st.form_submit_button("Add property", type="primary"):
            if not new_name.strip():
                st.error("Enter a name for this property.")
            else:
                new_id = add_property({"name":new_name.strip(),"area":new_area.strip(),"bedrooms":int(new_bedrooms),
                    "capacity":int(new_capacity),"latitude":float(new_lat),"longitude":float(new_lon),
                    "airbnb_url":new_airbnb.strip(),"booking_url":new_booking.strip()})
                st.session_state["pending_property_id"] = new_id
                st.rerun()
    st.stop()

def money(value: float) -> str:
    return f"€{value:,.2f}"


def booked_revenue_by_day(items: list[dict], start: date, end_exclusive: date) -> dict[date, float]:
    """Gross night revenue from active reservations, clipped to a date range."""
    totals: dict[date, float] = {}
    for item in items:
        if item["status"] not in {"confirmed", "completed"}:
            continue
        checkin, checkout = date.fromisoformat(item["checkin"]), date.fromisoformat(item["checkout"])
        night = max(checkin, start)
        while night < min(checkout, end_exclusive):
            totals[night] = totals.get(night, 0.0) + float(item["nightly_rate"])
            night += timedelta(days=1)
    return totals


def revenue_chart_svg(values: dict[date, float], description: str) -> str:
    """Render a responsive, tooltip-enabled SVG area chart for the revenue dashboard."""
    entries = sorted(values.items())
    if not entries:
        return '<div class="revenue-empty">No revenue is recorded for this period yet.</div>'
    width, height = 1000, 300
    left, right, top, bottom = 68, 24, 24, 48
    plot_width, plot_height = width - left - right, height - top - bottom
    max_value = max((amount for _, amount in entries), default=0.0)
    upper = max(1.0, max_value * 1.18)
    step = plot_width / len(entries)
    parts = [
        f'<svg class="revenue-chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(description, quote=True)}" xmlns="http://www.w3.org/2000/svg">',
        '<defs><linearGradient id="staywiseRevenueArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#41a695" stop-opacity=".34"/><stop offset="100%" stop-color="#41a695" stop-opacity=".025"/></linearGradient></defs>',
    ]
    for tick in range(5):
        value = upper * (4 - tick) / 4
        y = top + plot_height * tick / 4
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e8eef0" stroke-width="1"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" fill="#82919a" font-size="12" font-family="DM Sans, sans-serif">€{value:,.0f}</text>')
    label_step = max(1, math.ceil(len(entries) / 7))
    points = []
    for index, (day, amount) in enumerate(entries):
        x = left + index * step + step / 2
        y = top + plot_height - amount / upper * plot_height
        points.append((x, y, day, amount))
        if index % label_step == 0 or index == len(entries) - 1:
            label = escape(day.strftime("%b %d") if len(entries) > 7 else day.strftime("%d"))
            parts.append(f'<text x="{x:.1f}" y="{height-13}" text-anchor="middle" fill="#82919a" font-size="12" font-family="DM Sans, sans-serif">{label}</text>')

    if points:
        baseline = top + plot_height
        line_path = f'M {points[0][0]:.1f} {points[0][1]:.1f}'
        for index in range(len(points) - 1):
            x1, y1 = points[index][0], points[index][1]
            x2, y2 = points[index + 1][0], points[index + 1][1]
            previous_y = points[index - 1][1] if index else y1
            next_y = points[index + 2][1] if index + 2 < len(points) else y2
            dx = x2 - x1
            control1_y = y1 + (y2 - previous_y) / 6
            control2_y = y2 - (next_y - y1) / 6
            low, high = sorted((y1, y2))
            control1_y = min(high, max(low, control1_y))
            control2_y = min(high, max(low, control2_y))
            line_path += f' C {x1 + dx/3:.1f} {control1_y:.1f}, {x1 + dx*2/3:.1f} {control2_y:.1f}, {x2:.1f} {y2:.1f}'
        area_path = f'{line_path} L {points[-1][0]:.1f} {baseline:.1f} L {points[0][0]:.1f} {baseline:.1f} Z'
        parts.append(f'<path d="{area_path}" fill="url(#staywiseRevenueArea)"/>')
        parts.append(f'<path d="{line_path}" fill="none" stroke="#1d7a78" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>')
        for x, y, day, amount in points:
            title = escape(f"{day.strftime('%A, %d %B %Y')}: {money(amount)}")
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="transparent"><title>{title}</title></circle>')
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#fff" stroke="#1d7a78" stroke-width="2" pointer-events="none"/>')
    parts.append('</svg>')
    return ''.join(parts)


@st.cache_data(ttl=3600, show_spinner=False)
def load_postgres_snapshot() -> tuple[pd.DataFrame, dict] | None:
    return load_latest_snapshot()


with st.sidebar:
    st.markdown('<div class="brand">StayWise<span style="color:#1D7A78">.</span></div>', unsafe_allow_html=True)
    st.caption("Short-stay rental studio")
    st.divider()
    page = st.radio("Workspace", ["Overview", "Bookings", "Calendar", "Market", "Revenue", "Account"], label_visibility="collapsed")
    property_ids = [p["id"] for p in properties]
    if st.session_state.get("selected_property_id") not in property_ids:
        demo_home = next((p for p in properties if p["name"] == DEMO_PROPERTY_NAME), None)
        st.session_state["selected_property_id"] = demo_home["id"] if demo_home else property_ids[0]
    active_property_id = st.selectbox("Rental property", property_ids,
                                      format_func=lambda pid: next(p["name"] for p in properties if p["id"] == pid),
                                      key="selected_property_id")
    st.divider()
    active_property = next(p for p in properties if p["id"] == active_property_id)
    st.markdown(f"**{active_property['name']}**")
    st.caption(active_property.get("area") or "Add a location in property settings")
    if public_demo:
        st.info("Public walkthrough · session-only fictional details · guest records disabled", icon="🧪")
    elif auth_user:
        st.caption(f"Private Supabase account · {auth_user['email']}")
    else:
        st.caption("Private local database")
    st.caption("EUR · English")

settings = {**settings, "property_name": active_property["name"], "property_area": active_property["area"],
            "bedrooms": str(active_property["bedrooms"]), "capacity": str(active_property["capacity"]),
            "latitude": str(active_property["latitude"]), "longitude": str(active_property["longitude"])}
reservations = get_reservations(active_property_id)
blocks = get_blocked_dates(active_property_id)
comps = get_comparables(active_property_id)

if READ_ONLY:
    st.warning("Public walkthrough: property profiles stay in this browser session. Use fictional property details only. Guest records, CSV uploads, and booking edits are disabled.", icon="🔒")


if page == "Account":
    st.markdown('<div class="eyebrow">Your account</div>', unsafe_allow_html=True)
    st.title("Account & privacy")
    if auth_user:
        st.success("Signed in with Google")
        profile_left, profile_right = st.columns(2)
        profile_left.metric("Email", auth_user["email"] or "Connected Google account")
        profile_right.metric("Portfolio storage", "Private Supabase database")
        if auth_user.get("name"):
            st.write(f"**Name:** {auth_user['name']}")
        st.caption("Your property profiles, bookings, guest contact details, blocked dates, comparables, and settings are isolated to your Google account. StayWise does not store your Google password or OAuth client secret.")
        st.info("The Google account manages your sign-in. Use Google account security settings to change its password or enable two-step verification.")
        if st.button("Sign out", type="secondary"):
            sign_out()
            st.session_state.pop("selected_property_id", None)
            st.rerun()
    else:
        st.write("Sign in with your Google account to keep a private portfolio that follows you between devices. The public walkthrough remains available without signing in.")
        if auth_is_configured():
            if st.button("Continue with Google", type="primary"):
                sign_in()
        else:
            st.warning("Google sign-in is not configured for this deployment yet.")
            st.markdown("Configure Google OIDC in Streamlit Community Cloud Secrets and set `SUPABASE_DATABASE_URL` to your Supabase Postgres connection string. The setup steps are in the README.")


elif page == "Overview":
    st.markdown('<div class="eyebrow">Your rental at a glance</div>', unsafe_allow_html=True)
    st.title(f"{settings.get('property_name','My Rental')} overview")
    st.markdown('<p class="subtle">Your rental calendar and local market context in one calm workspace.</p>', unsafe_allow_html=True)
    market = competitor_summary(comps)
    cols = st.columns(2)
    cols[0].metric("Blocked date ranges", len(blocks))
    cols[1].metric("Manual comparable median", money(market["median_rate"]) if market["median_rate"] is not None else "—")
    st.info("Use the Calendar to see availability by day, or Market to compare nearby Lisbon Airbnb listings by radius.")
    with st.expander("Manage your rental portfolio"):
        st.caption("Save each home separately, then switch between them from the property selector. Airbnb and Booking.com links open your listing; StayWise does not sync accounts directly.")
        with st.form("add_property", clear_on_submit=True):
            p1,p2,p3 = st.columns(3)
            new_name = p1.text_input("Property name *")
            new_area = p2.text_input("Area / neighborhood")
            new_bedrooms = p3.number_input("Bedrooms", min_value=0, max_value=30, value=2, key="new_property_bedrooms")
            p1,p2,p3 = st.columns(3)
            new_capacity = p1.number_input("Guest capacity", min_value=1, max_value=100, value=4, key="new_property_capacity")
            new_lat = p2.number_input("Latitude", min_value=-90.0, max_value=90.0, value=38.719, format="%.6f", key="new_property_lat")
            new_lon = p3.number_input("Longitude", min_value=-180.0, max_value=180.0, value=-9.165, format="%.6f", key="new_property_lon")
            p1,p2 = st.columns(2)
            new_airbnb = p1.text_input("Airbnb listing URL")
            new_booking = p2.text_input("Booking.com listing URL")
            if st.form_submit_button("Add property", type="primary"):
                if not new_name.strip():
                    st.error("Enter a name for this property.")
                else:
                    new_id = add_property({"name":new_name.strip(),"area":new_area.strip(),"bedrooms":int(new_bedrooms),
                        "capacity":int(new_capacity),"latitude":float(new_lat),"longitude":float(new_lon),
                        "airbnb_url":new_airbnb.strip(),"booking_url":new_booking.strip()})
                    st.session_state["pending_property_id"] = new_id
                    st.rerun()
        st.divider()
        st.subheader("Remove this rental")
        if READ_ONLY and active_property["name"] == DEMO_PROPERTY_NAME:
            st.info("This built-in fictional Campo de Ourique example is kept in every demo session.")
        else:
            st.warning("Removing this property permanently deletes its reservations and guest contact details, blocked dates, and market comparisons.")
            last_local_property = len(properties) == 1 and not READ_ONLY
            if last_local_property:
                st.caption("Add another property before removing this one; the local app must keep at least one rental.")
            confirm_delete = st.checkbox("I understand that this property's data will be permanently deleted.",
                                         key=f"confirm_delete_property_{active_property_id}")
            if st.button("Delete selected property", type="secondary",
                         disabled=not confirm_delete or last_local_property):
                delete_property(active_property_id)
                remaining_properties = get_properties()
                if remaining_properties:
                    st.session_state["pending_property_id"] = remaining_properties[0]["id"]
                else:
                    st.session_state.pop("selected_property_id", None)
                st.rerun()
    link_cols = st.columns(2)
    if active_property.get("airbnb_url"):
        link_cols[0].link_button("Open Airbnb listing", active_property["airbnb_url"])
    if active_property.get("booking_url"):
        link_cols[1].link_button("Open Booking.com listing", active_property["booking_url"])


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
                add_reservation({**item, "property_id":active_property_id})
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
                    for item in accepted: add_reservation({**item, "property_id":active_property_id})
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
                add_blocked_dates(block_start.isoformat(),block_end.isoformat(),reason,active_property_id)
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
            property_name = c1.text_input("Property name", active_property["name"])
            area = c2.text_input("Area / neighborhood", settings.get("property_area",""))
            bedrooms = c3.number_input("Bedrooms", min_value=0, max_value=30, value=int(settings.get("bedrooms",2)))
            c1,c2,c3 = st.columns(3)
            capacity = c1.number_input("Guest capacity", min_value=1, max_value=100, value=int(settings.get("capacity",4)))
            latitude = c2.number_input("Latitude", min_value=-90.0, max_value=90.0, value=float(settings.get("latitude",38.719)), format="%.6f")
            longitude = c3.number_input("Longitude", min_value=-180.0, max_value=180.0, value=float(settings.get("longitude",-9.165)), format="%.6f")
            c1,c2 = st.columns(2)
            airbnb_url = c1.text_input("Airbnb listing URL", active_property.get("airbnb_url", ""))
            booking_url = c2.text_input("Booking.com listing URL", active_property.get("booking_url", ""))
            st.caption("The default map point is approximate for Campo de Ourique. Set your home's coordinates for the most accurate radius search.")
            if st.form_submit_button("Save property settings", type="primary", disabled=READ_ONLY):
                update_property(active_property_id, {"name":property_name,"area":area,"bedrooms":int(bedrooms),"capacity":int(capacity),
                               "latitude":float(latitude),"longitude":float(longitude),"airbnb_url":airbnb_url,"booking_url":booking_url})
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
        st.session_state["inside_airbnb_refresh_requested"] = True
        load_inside_airbnb.clear()
        load_postgres_snapshot.clear()
    if st.session_state.get("inside_airbnb_loaded"):
        with st.spinner("Loading the latest configured Lisbon snapshot from Inside Airbnb…"):
            try:
                storage_info = None
                storage_error = None
                configured_urls = database_urls()
                refresh_requested = st.session_state.pop("inside_airbnb_refresh_requested", False)
                saved = None
                if not refresh_requested and any(configured_urls.values()):
                    try:
                        saved = load_postgres_snapshot()
                    except Exception as exc:
                        storage_error = str(exc)
                if saved:
                    source_data, storage_info = saved
                else:
                    source_data = load_inside_airbnb(LISBON_LISTINGS_URL)
                    if any(configured_urls.values()):
                        try:
                            storage_info = save_latest_snapshot(source_data, LISBON_LISTINGS_URL, "Lisbon")
                            load_postgres_snapshot.clear()
                        except Exception as exc:
                            storage_error = str(exc)
                nearby = listings_within_radius(
                    source_data, float(settings.get("latitude",38.719)), float(settings.get("longitude",-9.165)),
                    radius_km, int(settings.get("bedrooms",2)) if bedrooms_only else None,
                    int(settings.get("capacity",4)) if capacity_match else None,
                )
                st.caption(f"Source snapshot: 19 September 2026 · {len(nearby):,} matches · distances are straight-line from your saved coordinates. Prices and availability are source data, not live quotes.")
                if storage_info:
                    db_mb = (storage_info.get("database_bytes") or 0) / (1024 ** 2)
                    payload_mb = storage_info.get("payload_bytes", 0) / (1024 ** 2)
                    st.success(f"Full Lisbon snapshot saved in {storage_info['provider']} PostgreSQL · {storage_info['listing_count']:,} listings · {payload_mb:.1f} MiB of listing data · database currently {db_mb:.1f} MiB. Only the latest snapshot is retained.")
                elif storage_error:
                    st.warning(f"The comparison data loaded for this session, but could not be saved to PostgreSQL: {storage_error}")
                else:
                    st.info("The snapshot is currently loaded in this session only. To save it permanently, add SUPABASE_DATABASE_URL to Streamlit Community Cloud Secrets; add LAYERBASE_DATABASE_URL too if the measured database would exceed 500 MiB.")
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
                    st.subheader("Nearby competition map")
                    st.caption(f"{len(nearby):,} matching Airbnb listings · {radius_km:.1f} km radius. Listings group together when zoomed out; zoom in to separate individual homes.")
                    home_lat, home_lon = float(settings["latitude"]), float(settings["longitude"])
                    competition_map = folium.Map(location=[home_lat, home_lon], zoom_start=14, tiles="OpenStreetMap",
                        control_scale=True, scrollWheelZoom=True, prefer_canvas=True)
                    home_layer = folium.FeatureGroup(name="Your property", show=True).add_to(competition_map)
                    folium.Circle(location=[home_lat, home_lon], radius=radius_km * 1000, color="#16877E",
                        weight=2, fill=True, fill_color="#16877E", fill_opacity=0.05,
                        tooltip=f"{escape(settings['property_name'])} · {radius_km:.1f} km search radius").add_to(home_layer)
                    folium.Marker([home_lat, home_lon], tooltip="Your property", popup=folium.Popup(
                        f"<div style='font-family:sans-serif'><strong>{escape(settings['property_name'])}</strong><br>Your rental</div>", max_width=240),
                        icon=folium.Icon(color="darkgreen", icon="home", prefix="fa")).add_to(home_layer)
                    cluster_icon = """function(cluster) {
                        var n = cluster.getChildCount();
                        var size = n >= 100 ? 46 : 40;
                        return new L.DivIcon({html:'<div style=\"width:'+size+'px;height:'+size+'px;line-height:'+size+'px;border-radius:50%;background:#e79447;color:white;text-align:center;font-weight:700;font-family:sans-serif;border:3px solid white;box-shadow:0 2px 8px #17324d44\">'+n+'</div>',className:'',iconSize:[size,size]});
                    }"""
                    airbnb_group = MarkerCluster(name="Airbnb listings", options={"maxClusterRadius":44,"spiderfyOnMaxZoom":True,
                        "showCoverageOnHover":False,"zoomToBoundsOnClick":True}, icon_create_function=cluster_icon).add_to(competition_map)
                    for _, listing in nearby.iterrows():
                        name = escape(str(listing.get("name") or "Airbnb listing"))
                        listing_id = str(listing.get("id", "")).split(".")[0]
                        airbnb_url = f"https://www.airbnb.com/rooms/{listing_id}" if listing_id.isdigit() else "https://www.airbnb.com/"
                        price = float(listing["price"])
                        popup_html = (f"<div style='font-family:Arial,sans-serif;min-width:180px'>"
                            f"<div style='font-size:14px;font-weight:700;color:#17324D;margin-bottom:5px'>{name}</div>"
                            f"<div style='color:#526676'>€{price:,.0f} / night · {float(listing['distance_km']):.1f} km away</div>"
                            f"<a href='{escape(airbnb_url, quote=True)}' target='_blank' rel='noopener noreferrer' "
                            "style='display:inline-block;margin-top:9px;background:#E79447;color:white;padding:7px 11px;border-radius:7px;text-decoration:none;font-weight:700'>Open Airbnb listing ↗</a></div>")
                        icon = folium.DivIcon(html="<div style='width:13px;height:13px;border:2px solid white;border-radius:50%;background:#E79447;box-shadow:0 1px 5px #17324d66'></div>",
                            icon_size=(17,17), icon_anchor=(8,8), class_name="")
                        folium.Marker([float(listing["latitude"]),float(listing["longitude"])], tooltip=folium.Tooltip(name, sticky=True),
                            popup=folium.Popup(popup_html,max_width=270),icon=icon).add_to(airbnb_group)
                    manual_group = folium.FeatureGroup(name="Manually added listings", show=True).add_to(competition_map)
                    for comp in comps:
                        if comp.get("latitude") is None or comp.get("longitude") is None or float(comp.get("distance_km",0)) > radius_km:
                            continue
                        manual_name = escape(str(comp["name"]))
                        external_url = str(comp.get("url", ""))
                        safe_url = escape(external_url, quote=True)
                        manual_popup = f"<div style='font-family:Arial,sans-serif'><strong>{manual_name}</strong><br>€{float(comp['nightly_rate']):,.0f} / night"
                        if external_url.startswith(("https://", "http://")):
                            manual_popup += f"<br><a href='{safe_url}' target='_blank' rel='noopener noreferrer'>Open listing ↗</a>"
                        folium.Marker([float(comp["latitude"]),float(comp["longitude"])],tooltip=folium.Tooltip(manual_name,sticky=True),
                            popup=folium.Popup(manual_popup+"</div>",max_width=260),
                            icon=folium.DivIcon(html="<div style='width:13px;height:13px;border:2px solid white;border-radius:50%;background:#526676;box-shadow:0 1px 5px #17324d66'></div>",
                                icon_size=(17,17),icon_anchor=(8,8),class_name="")).add_to(manual_group)
                    lat_delta = radius_km / 111.32
                    lon_delta = radius_km / (111.32 * max(0.2, math.cos(math.radians(home_lat))))
                    competition_map.fit_bounds([[home_lat-lat_delta,home_lon-lon_delta],[home_lat+lat_delta,home_lon+lon_delta]],padding=(16,16))
                    folium.LayerControl(collapsed=True,position="topright").add_to(competition_map)
                    st.markdown("<span style='color:#16877E'>● Your property and radius</span>　<span style='color:#E79447'>● Airbnb listings</span>　<span style='color:#526676'>● Manually added listings</span>", unsafe_allow_html=True)
                    st.caption("Hover over an individual pin to see its name. Click the pin, then choose **Open Airbnb listing** in its card to visit that home.")
                    st_folium(competition_map, height=560, width=None, use_container_width=True, returned_objects=[], key="competition_folium_map")
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
        comp_map = st.checkbox("Add this comparable to the map", value=False)
        c1,c2 = st.columns(2)
        comp_lat = c1.number_input("Comparable latitude", min_value=-90.0, max_value=90.0, value=float(settings.get("latitude",38.719)), format="%.6f", disabled=not comp_map)
        comp_lon = c2.number_input("Comparable longitude", min_value=-180.0, max_value=180.0, value=float(settings.get("longitude",-9.165)), format="%.6f", disabled=not comp_map)
        url = st.text_input("Listing URL (optional)")
        comp_notes = st.text_input("Notes: amenities, size, or other differences")
        comp_submit = st.form_submit_button("Add comparison", type="primary", disabled=READ_ONLY)
    if comp_submit:
        if not comp_name.strip() or comp_rate <= 0:
            st.error("Enter a listing label and a price above zero.")
        else:
            add_comparable({"name":comp_name.strip(),"area":comp_area.strip(),"bedrooms":int(comp_beds),"capacity":int(comp_capacity),
                            "distance_km":float(distance),"nightly_rate":float(comp_rate),"observed_date":observed.isoformat(),
                            "url":url.strip(),"notes":comp_notes,"selected":1,
                            "latitude":float(comp_lat) if comp_map else None,"longitude":float(comp_lon) if comp_map else None,
                            "property_id":active_property_id})
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


elif page == "Revenue":
    st.markdown('<div class="eyebrow">Recorded stay income</div>', unsafe_allow_html=True)
    st.title("Revenue")
    st.markdown('<p class="subtle">A clear view of recorded stay income, with cancelled bookings and future nights left out.</p>', unsafe_allow_html=True)

    control_left, control_right = st.columns([1.25, 1], vertical_alignment="bottom")
    with control_left:
        period = st.segmented_control("Revenue period", ["Daily", "Monthly", "Year to date"],
                                      default="Monthly", label_visibility="collapsed", key="revenue_period")
    today = date.today()
    if period == "Daily":
        with control_right:
            selected_day = st.date_input("Choose a day", value=today, key="revenue_day")
        start, end = selected_day, selected_day + timedelta(days=1)
        period_label = selected_day.strftime("%A, %d %B %Y")
        period_values = booked_revenue_by_day(reservations, start, end)
        chart_start, chart_end = selected_day - timedelta(days=6), selected_day + timedelta(days=1)
        chart_values = booked_revenue_by_day(reservations, chart_start, chart_end)
        chart_title = "A little context around your day"
        chart_note = "Daily gross across the 7 days ending on your selected date"
    elif period == "Monthly":
        with control_right:
            selected_month = st.date_input("Choose a month", value=today.replace(day=1), key="revenue_month")
        start = selected_month.replace(day=1)
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        period_label = start.strftime("%B %Y")
        period_values = booked_revenue_by_day(reservations, start, end)
        chart_values = {start + timedelta(days=offset): period_values.get(start + timedelta(days=offset), 0.0)
                        for offset in range((end - start).days)}
        chart_title = "Your month, night by night"
        chart_note = "Each point shows gross revenue from one calendar night"
    else:
        start = date(today.year, 1, 1)
        end = today + timedelta(days=1)
        period_label = f"January – {today.strftime('%B %Y')}"
        period_values = booked_revenue_by_day(reservations, start, end)
        chart_values = {
            date(today.year, month, 1): sum(value for day, value in period_values.items() if day.month == month)
            for month in range(1, today.month + 1)
        }
        chart_title = "The year so far"
        chart_note = "Monthly gross revenue from January through today"

    gross = sum(period_values.values())
    booked_nights = len(period_values)
    average_rate = gross / booked_nights if booked_nights else 0.0
    active_bookings = []
    detail_rows = []
    for reservation in reservations:
        if reservation["status"] not in {"confirmed", "completed"}:
            continue
        checkin = date.fromisoformat(reservation["checkin"])
        checkout = date.fromisoformat(reservation["checkout"])
        clipped_start, clipped_end = max(checkin, start), min(checkout, end)
        nights = max(0, (clipped_end - clipped_start).days)
        if nights <= 0:
            continue
        active_bookings.append(reservation)
        detail_rows.append({
            "Stay": f"{checkin:%d %b} – {checkout:%d %b}",
            "Guest": reservation["guest_name"],
            "Channel": reservation["source"],
            "Nights": nights,
            "Nightly rate": money(float(reservation["nightly_rate"])),
            "Revenue in period": money(nights * float(reservation["nightly_rate"])),
            "Status": reservation["status"].title(),
        })

    property_label = escape(active_property["name"])
    st.markdown(
        f'<section class="revenue-hero"><div class="revenue-hero-label">Gross income · {escape(period_label)}</div>'
        f'<div class="revenue-hero-value">{money(gross)}</div>'
        f'<div class="revenue-hero-note">Recorded nightly revenue for {property_label}</div>'
        f'<span class="revenue-hero-badge">{len(active_bookings)} active stay{"s" if len(active_bookings) != 1 else ""} in this period</span></section>',
        unsafe_allow_html=True,
    )

    k1, k2, k3 = st.columns(3)
    k1.markdown(f'<div class="revenue-kpi"><div class="revenue-kpi-label">Booked nights</div><div class="revenue-kpi-value">{booked_nights}</div><div class="revenue-kpi-note">Confirmed or completed stays</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="revenue-kpi"><div class="revenue-kpi-label">Average nightly rate</div><div class="revenue-kpi-value">{money(average_rate)}</div><div class="revenue-kpi-note">Gross income per booked night</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="revenue-kpi"><div class="revenue-kpi-label">Period</div><div class="revenue-kpi-value">{escape(period_label)}</div><div class="revenue-kpi-note">Revenue is shown in EUR</div></div>', unsafe_allow_html=True)

    st.markdown(
        f'<section class="revenue-chart-card"><div class="revenue-chart-title">{escape(chart_title)}</div>'
        f'<div class="revenue-chart-subtitle">{escape(chart_note)} · hover a point for its exact amount</div>'
        f'{revenue_chart_svg(chart_values, chart_title)}</section>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="revenue-section-title">Stay details</div>', unsafe_allow_html=True)
    if detail_rows:
        st.dataframe(pd.DataFrame(detail_rows), width="stretch", hide_index=True)
    else:
        st.markdown('<div class="revenue-empty">No confirmed or completed stays are recorded for this period.</div>', unsafe_allow_html=True)
    st.caption("Gross nightly income only. Future nights, cancellations, platform fees, operating costs, and taxes are excluded.")
    st.divider()
    st.subheader("Download revenue workbook")
    st.caption("An Excel workbook with a KPI dashboard and chart, monthly summary, daily revenue ledger, and reservation details for the current year to date.")
    workbook = build_revenue_workbook(active_property["name"], date.today().year, reservations, date.today())
    st.download_button("Download revenue Excel workbook", workbook,
                       f"staywise-revenue-{date.today().year}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
