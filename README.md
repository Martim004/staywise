# StayWise

StayWise helps a short-term rental owner keep reservation details, compare similar homes, estimate annual revenue, and export a clean PDF or Excel report.

> **Course-project note:** the linked team-project guidance asks teams to extend a member's solo project. StayWise is intentionally standalone while an exception is requested. Confirm the exception before presenting this repository as a course-compliant submission.

## Demo and team

- Public demo: **To be deployed**
- Team members and student numbers: **Add all names and student numbers before course submission.**
- Repository: `https://github.com/Martim004/staywise`

The public demo is read-only and uses fictional data only. Never commit guest details or a local database file.

## Run locally

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

The local app stores data in `data/staywise.sqlite3`. That directory is excluded from Git. To inspect the read-only fictional sample dataset locally, set `STAYWISE_DEMO=1` before starting the app.

## Run tests

```bash
python -m unittest discover -s tests
```

## Main features

- Reservation records with guest contact details, stay dates, guest count, rate, source, notes, and status.
- CSV import with row-level validation and overlap checks; CSV export and a downloadable template.
- Owner-blocked dates for personal use or maintenance.
- User-entered comparable listings, median nightly-rate benchmark, and adjustable suggested rate.
- Year forecast combining confirmed stays with monthly occupancy and rate assumptions for available, unbooked nights.
- Estimated net after configured platform fees and operating costs. Taxes are excluded.
- Downloadable annual PDF report and editable Excel workbook.

## CSV columns

`guest_name,email,phone,checkin,checkout,guests,nightly_rate,status,source,notes`

Dates use `YYYY-MM-DD`. Status must be `confirmed`, `completed`, or `cancelled`. Check-out is exclusive: a three-night stay from June 12 through June 15 occupies the nights of June 12, 13, and 14.

## Public demo deployment

The demo can be deployed from this public GitHub repository on [Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app). Set `STAYWISE_DEMO=1` in the app's deployment settings so it starts with fictional demo records. Add the resulting app URL above and to the team-project submission README details before submission. Do not deploy personal guest records.

## Project structure

```text
app.py                 Streamlit screens and user workflows
staywise/calculations.py  Reservation rules, market summary, revenue forecast
staywise/database.py     SQLite storage and fictional demo seed data
staywise/imports.py      CSV template, validation, and export
staywise/reports.py      PDF and Excel report generation
tests/                  Business-rule and export verification
```
