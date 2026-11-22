# StayWise

StayWise helps a short-term rental owner manage multiple homes and their stays, compare nearby Lisbon or Porto Airbnb listings, view competitors on a map, and track recorded nightly revenue.

> **Course-project note:** the linked team-project guidance asks teams to extend a member's solo project. StayWise is intentionally standalone while an exception is requested. Confirm the exception before presenting this repository as a course-compliant submission.

## Sign-in demo and team

- App: https://staywise-martim004.streamlit.app
- Team members and student numbers: **Add all names and student numbers before course submission.**
- Repository: https://github.com/Martim004/staywise

The deployed app requires Google sign-in. Each account starts with an empty private portfolio. When a user adds a rental, StayWise creates clearly fictional bookings, a blocked period, and map-ready fictional comparisons. Each user's portfolio is isolated by Supabase RLS. The city selector follows the Portuguese city snapshots currently listed by Inside Airbnb (Lisbon and Porto). Never commit real guest details or a local database file.

## Run locally

Requires Python 3.11 or newer (needed by the pinned map integration).

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
STAYWISE_LOCAL_MODE=1 streamlit run app.py
```

The local app stores data in `data/staywise.sqlite3`. That directory is excluded from Git. To inspect fictional sample records locally, set `STAYWISE_DEMO=1` before starting the app.

## Security

- The deployed app fails closed unless Google sign-in is configured. Any verified Google account can create its own isolated portfolio; no rental data is loaded before sign-in. Local SQLite development requires the explicit `STAYWISE_LOCAL_MODE=1` opt-in.
- PostgreSQL uses authenticated roles and row-level security scoped to the verified Google subject; child records must reference a property owned by the same user.
- Application and database checks bound dates, rates, counts, text lengths, URLs, and CSV upload size/row count.
- CSV and Excel exports escape formula-like text; PDF output escapes user-provided markup.
- `requirements.in` lists the minimal direct packages; `requirements.txt` pins the full dependency tree with SHA-256 hashes. Regenerate it with `uv pip compile requirements.in --python-version 3.11 --generate-hashes -o requirements.txt`.
- GitHub Actions runs `pip-audit` on pushes, pull requests, and weekly; Dependabot proposes dependency and workflow updates.
- Keep `.streamlit/secrets.toml`, database files, API keys, and real guest records out of Git. Use fictional records in public demos.

## Run tests

```bash
python -m unittest discover -s tests
```

## Main features

- Reservation records with guest details, stay dates, source, and status; CSV import and export.
- A multi-property portfolio with property-specific reservations, blocked dates, comparables, map coordinates, and Airbnb / Booking.com listing links.
- Google sign-in and an account page; signed-in portfolios are stored in Supabase Postgres and separated with PostgreSQL Row Level Security (RLS).
- Add or remove rentals from the portfolio; removing a rental also removes its linked reservations, guest contacts, blocked dates, and comparisons. Every rental can be deleted after confirmation.
- Color-coded month calendar showing booked, blocked, and available nights.
- Lisbon and Porto Airbnb market comparisons from the public Inside Airbnb snapshots, with a configurable radius, bedroom and capacity filters, price distribution, ratings, reviews, availability, and listing-level details.
- An OpenStreetMap street view centered on the selected home, with clustered competitors, hover names, and listing popups that link to Airbnb pages.
- Manual comparable records for Booking.com or other sources, since Inside Airbnb publishes Airbnb data only.
- Revenue views for a chosen night, a chosen month, and current-year-to-date. Revenue is actual booked gross nightly revenue, not a projection.
- Revenue Excel workbook with a KPI dashboard and chart, monthly summary, daily ledger, and reservation detail.
- Fictional demo bookings, blocked dates, comparison map pins, calendar entries, and revenue records generated whenever a user adds a property.
- PostgreSQL snapshot storage for the current Inside Airbnb Lisbon and Porto detailed listings files. The latest snapshot for each city is retained separately; the CSV's original columns are kept in JSONB.

The Inside Airbnb public snapshot is downloaded on request and cached for 24 hours. Prices are observations from that snapshot, not live booking quotes. Comparisons use straight-line distance and should be interpreted as market context, not an exact price prediction. Airbnb and Booking.com links open the owner's listing page; StayWise does not currently connect accounts or sync reservations directly. Airbnb API-connected software access and Booking.com connectivity require approved partner / property connections. Source: [Inside Airbnb data](https://insideairbnb.com/pt/get-the-data/).

When a PostgreSQL URL is configured, **Load / refresh Airbnb comparables** saves the complete Lisbon or Porto `listings.csv.gz` snapshot matching the selected property's city to PostgreSQL before filtering it for the selected home. Calendar and review files are not imported in this feature. StayWise estimates the next database footprint with a safety margin: below 500 MiB it selects Supabase; at or above that threshold it selects Layerbase. It reports the actual PostgreSQL database size after saving. The most recent snapshot replaces the prior listing snapshot for that city to keep storage bounded.

For the Streamlit Cloud app, add database connection strings under **Manage app → Settings → Secrets**. Supply a Supabase connection URL, and a Layerbase URL as the size fallback:

```toml
SUPABASE_DATABASE_URL = "postgresql://..."
LAYERBASE_DATABASE_URL = "postgresql://..."
```

Use the connection URL from each provider's dashboard and keep these credentials out of GitHub and chat. Supabase documents the **Session pooler** for long-running backends that need IPv4-compatible access; the exact endpoint and username are shown in its dashboard. If no database URL is configured, the Market page still works but keeps the snapshot only in the app session.

## Google sign-in and private accounts

StayWise uses Streamlit's OpenID Connect handler to verify Google accounts. The Google password is entered only on Google's sign-in page; StayWise never receives or stores it. Streamlit keeps the sign-in session in its protected cookie. Rental data is stored in the configured Supabase Postgres database, with a separate Google subject on every row and RLS policies applied to the account tables. The app uses its server-side database connection only after verifying the Google identity. The Supabase database password and Google OAuth client secret belong only in Streamlit Secrets; never commit them or send them in chat.

One-time setup:

1. In Google Cloud Console, create an OAuth client of type **Web application**. Add the redirect URI `https://staywise-martim004.streamlit.app/oauth2callback` under **Authorized redirect URIs**. For local development also add `http://localhost:8501/oauth2callback`.
2. Copy the OAuth client ID and client secret into Streamlit Community Cloud **Manage app → Settings → Secrets**. Keep the existing `SUPABASE_DATABASE_URL` connection secret. It must be a server-side Postgres connection string, not the publishable/anon API key.
3. Add these values to Streamlit Secrets (place `SUPABASE_DATABASE_URL` before the `[auth]` section):

   ```toml
   SUPABASE_DATABASE_URL = "postgresql://..."

   [auth]
   redirect_uri = "https://staywise-martim004.streamlit.app/oauth2callback"
   cookie_secret = "generate a long random value"
   client_id = "your Google OAuth client ID"
   client_secret = "your Google OAuth client secret"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```

4. On the first signed-in visit, StayWise creates its account tables and RLS policies using SUPABASE_DATABASE_URL. The profile, properties, bookings, guest contacts, calendar blocks, comparables, and settings are saved in Supabase. Any Google account that completes sign-in may use StayWise; each account receives its own isolated fictional example portfolio.
5. If Google's OAuth consent screen is still in Testing mode, Google permits only the listed test users. To allow your professor or other Google accounts to sign in without adding each as a tester, publish the external consent screen. Google may require verification depending on the scopes and usage.


For local Google sign-in, create `.streamlit/secrets.toml` with the same `[auth]` values, use the local callback URI above, and set `SUPABASE_DATABASE_URL` to the Supabase connection string. The file is ignored by Git. Existing local SQLite data is kept local; StayWise does not automatically upload guest records during account setup.

Revenue forecasting, expected-revenue summaries, and PDF reports are not included. The revenue workbook contains recorded revenue only.

## Booking CSV columns

`guest_name,email,phone,checkin,checkout,guests,nightly_rate,status,source,notes`

Dates use `YYYY-MM-DD`. Status must be `confirmed`, `completed`, or `cancelled`. Check-out is exclusive: a three-night stay from June 12 through June 15 occupies the nights of June 12, 13, and 14.

## Signed-in deployment

The app is deployed from this public GitHub repository on [Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app). Sign-in is required before rental data loads. Remove the legacy `STAYWISE_DEMO` secret from Streamlit Cloud. Never deploy personal guest records.

## Project structure

```text
app.py                   Streamlit screens and user workflows
staywise/auth.py         Verified Google OpenID Connect identity
staywise/calculations.py Reservation validation and manual market summary
staywise/database.py     SQLite demo/local storage and Supabase user data
staywise/imports.py      CSV template, validation, and export
staywise/inside_airbnb.py Inside Airbnb filtering and distance calculations
supabase/migrations/     RLS-protected account data schema
tests/                   Business-rule, export, and app smoke checks
```
