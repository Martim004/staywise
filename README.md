# StayWise

StayWise helps a short-term rental owner manage stays and blocked dates, compare nearby Lisbon Airbnb listings, and export booking information as CSV.

> **Course-project note:** the linked team-project guidance asks teams to extend a member's solo project. StayWise is intentionally standalone while an exception is requested. Confirm the exception before presenting this repository as a course-compliant submission.

## Demo and team

- Public demo: https://staywise-martim004.streamlit.app
- Team members and student numbers: **Add all names and student numbers before course submission.**
- Repository: https://github.com/Martim004/staywise

The public demo is read-only and uses fictional records only. Never commit guest details or a local database file.

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
- Color-coded month calendar showing booked, blocked, and available nights.
- Lisbon Airbnb market comparisons from the public Inside Airbnb listings snapshot, with a configurable radius, bedroom and capacity filters, price distribution, ratings, reviews, availability, and listing-level details.
- Manual comparable records for Booking.com or other sources, since Inside Airbnb publishes Airbnb data only.
- Property location settings using latitude and longitude. The initial Campo de Ourique coordinates are approximate and should be adjusted for the property.

The Inside Airbnb public snapshot is downloaded on request and cached for 24 hours. Prices are observations from that snapshot, not live booking quotes. Comparisons use straight-line distance and should be interpreted as market context, not an exact price prediction. Source: [Inside Airbnb data](https://insideairbnb.com/pt/get-the-data/).

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
