# StayWise

StayWise helps a short-term rental owner manage multiple homes and their stays, compare nearby Lisbon Airbnb listings, view competitors on a map, and track recorded nightly revenue.

> **Course-project note:** the linked team-project guidance asks teams to extend a member's solo project. StayWise is intentionally standalone while an exception is requested. Confirm the exception before presenting this repository as a course-compliant submission.

## Demo and team

- Public demo: https://staywise-martim004.streamlit.app
- Team members and student numbers: **Add all names and student numbers before course submission.**
- Repository: https://github.com/Martim004/staywise

The public demo is read-only and uses fictional records only, including a Campo de Ourique T2 sample with roughly 60% annual booked-night occupancy. Never commit guest details or a local database file.

## Run locally

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

The local app stores data in `data/staywise.sqlite3`. That directory is excluded from Git. To inspect fictional sample records locally, set `STAYWISE_DEMO=1` before starting the app.

## Run tests

```bash
python -m unittest discover -s tests
```

## Main features

- Reservation records with guest details, stay dates, source, and status; CSV import and export.
- A multi-property portfolio with property-specific reservations, blocked dates, comparables, map coordinates, and Airbnb / Booking.com listing links.
- Color-coded month calendar showing booked, blocked, and available nights.
- Lisbon Airbnb market comparisons from the public Inside Airbnb listings snapshot, with a configurable radius, bedroom and capacity filters, price distribution, ratings, reviews, availability, and listing-level details.
- A map centered on the selected home, with a search-radius ring, an aggregated listing-density view, and individual listing pins as an alternate view.
- Manual comparable records for Booking.com or other sources, since Inside Airbnb publishes Airbnb data only.
- Revenue views for a chosen night, a chosen month, and current-year-to-date. Revenue is actual booked gross nightly revenue, not a projection.

The Inside Airbnb public snapshot is downloaded on request and cached for 24 hours. Prices are observations from that snapshot, not live booking quotes. Comparisons use straight-line distance and should be interpreted as market context, not an exact price prediction. Airbnb and Booking.com links open the owner's listing page; StayWise does not currently connect accounts or sync reservations directly. Airbnb API-connected software access and Booking.com connectivity require approved partner / property connections. Source: [Inside Airbnb data](https://insideairbnb.com/pt/get-the-data/).

Revenue forecasting, expected-revenue summaries, and PDF/Excel annual reports are temporarily removed.

## Booking CSV columns

`guest_name,email,phone,checkin,checkout,guests,nightly_rate,status,source,notes`

Dates use `YYYY-MM-DD`. Status must be `confirmed`, `completed`, or `cancelled`. Check-out is exclusive: a three-night stay from June 12 through June 15 occupies the nights of June 12, 13, and 14.

## Public demo deployment

The demo is deployed from this public GitHub repository on [Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app). In Advanced settings, `STAYWISE_DEMO = "1"` is configured in Secrets TOML. Never deploy personal guest records.

## Project structure

```text
app.py                   Streamlit screens and user workflows
staywise/calculations.py Reservation validation and manual market summary
staywise/database.py     SQLite storage and fictional demo seed data
staywise/imports.py      CSV template, validation, and export
staywise/inside_airbnb.py Inside Airbnb filtering and distance calculations
tests/                   Business-rule, export, and app smoke checks
```
