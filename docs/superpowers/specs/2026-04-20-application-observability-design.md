# Application Observability: Design Spec

**Date:** 2026-04-20
**Status:** Draft
**Owner:** Silas Spencer

## Goal

Give the user visibility into software engineering job applications sent from `spencer.si@northeastern.edu`, by automatically pulling email, classifying each message as one of four statuses (`applied`, `next_step`, `rejected`, `offer`), storing the data locally, and visualizing it in Grafana.

## Non-Goals

- Tracking applications sent from any other email address (a future Gmail account is out of scope for v1).
- LLM-based or ML-based classification. All classification is rule-based.
- Sending notifications, reminders, or follow-ups.
- Public hosting. The project runs locally; remote access can be added later via port forwarding if desired.

## Architecture Overview

Three components, all running on the user's Mac:

1. **Email sync worker** (Python script, `sync.py`). Authenticates to Microsoft Graph, pulls mail from the user's Outlook mailbox, applies classification rules, writes results to SQLite. Triggered by a `launchd` timer.
2. **Storage**: a single SQLite database file (`jobs.db`).
3. **Grafana**: runs in Docker (`docker compose up -d`). Reads the SQLite file using the `frser-sqlite-datasource` plugin. Dashboards are provisioned from JSON files in the repo and served at `http://localhost:3000`.

```
[Outlook Mailbox]
       |
       |  Microsoft Graph API (OAuth device code)
       v
[sync.py worker]  -->  [jobs.db (SQLite)]  <--  [Grafana (Docker)]
       ^                                              |
       |                                              v
[launchd timer]                              http://localhost:3000
```

## Data Model

Two tables in SQLite.

### `applications`

One row per company + role the user applied to.

| column | type | notes |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | |
| `company` | TEXT NOT NULL | parsed from sender display name or domain |
| `role` | TEXT | nullable; parsed from email subject when possible |
| `first_email_id` | TEXT NOT NULL | Graph message id of the application confirmation |
| `applied_at` | DATETIME NOT NULL | timestamp from the `applied` email |
| `current_status` | TEXT NOT NULL | one of `applied`, `next_step`, `rejected`, `offer` |
| `status_updated_at` | DATETIME NOT NULL | last time `current_status` changed |

Unique index on `(company, role)` to enable upsert logic during dedup.

### `status_events`

Append-only log of every status change. Drives time-series and funnel charts.

| column | type | notes |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | |
| `application_id` | INTEGER NOT NULL | FK to `applications.id` |
| `status` | TEXT NOT NULL | one of `applied`, `next_step`, `rejected`, `offer` |
| `email_id` | TEXT NOT NULL UNIQUE | Graph message id that triggered the event |
| `occurred_at` | DATETIME NOT NULL | from email's `receivedDateTime` |

The unique constraint on `email_id` enforces idempotency: re-running sync never inserts duplicate events.

### Why two tables

Funnel and time-series charts need state-change history, not just current state. Grafana queries `status_events` for "applications over time" and joins back to `applications` for the company table view.

### Deduplication

When a new email is classified, the worker matches it to an existing application by `(company, role)`. If a match exists, it appends a `status_events` row and updates the application's `current_status` and `status_updated_at`. If no match exists and the new email is an `applied` event, a new `applications` row is created. Non-`applied` events with no matching application are logged but not inserted (we cannot establish the application baseline without an initial `applied` event).

## Email Classification

Classification runs on every email pulled from Graph. Rules live in `sync/rules.yaml` so the user can tune them without touching code.

### Step 1: Job filter (cheap pre-check)

Skip the email entirely unless its subject or body contains at least one of: `engineer`, `developer`, `software`, `swe`, `intern`. This filters out unrelated marketing email that happens to use phrases like "thank you for applying."

### Step 2: Status detection

Match the subject and the first ~2 KB of the body against the keyword sets below. First match wins; rules are evaluated in this order: `offer`, `next_step`, `rejected`, `applied`. Higher-signal statuses are checked first so that, for example, an interview confirmation is not misclassified as a generic "applied" message.

| Status | Patterns (case-insensitive) |
| --- | --- |
| `applied` | "thank you for applying", "we received your application", "application received", "thanks for your interest" |
| `rejected` | "unfortunately", "we have decided to move forward with other candidates", "not moving forward", "no longer being considered", "we will not be progressing" |
| `next_step` | "next step", "schedule a", "phone screen", "interview", "would you be available", "recruiter would like to" |
| `offer` | "offer", "we are pleased to extend", "offer letter" |

If no status matches, the email is logged to `unclassified.log` and skipped.

### Step 3: Company extraction

Run after a status is detected.

- If the sender matches a known ATS pattern (`*@greenhouse.io`, `*@us.greenhouse-mail.io`, `*@hire.lever.co`, `*@jobs.lever.co`, `*@myworkday.com`, `*@myworkdayjobs.com`, `*@ashbyhq.com`, `*@smartrecruiters.com`, `*@icims.com`), use ATS-specific parsing. Most ATSes put the company name in the `From` display name, and we strip common suffixes like "Recruiting", "Talent", "Careers".
- Otherwise, fall back to a generic extractor: use the `From` display name, then sender domain (for example, `careers@stripe.com` becomes `Stripe`).
- If both fail, store `Unknown` and log the email id so the rule pack can be improved later.

### Step 4: Role extraction

Best-effort regex on the subject line: try first quoted string, then text after "for the" or "for your application to". If nothing parses cleanly, store `null` rather than guessing.

## Sync Worker

A single Python script with two modes.

- `python sync.py --backfill`: one-time setup. Fetches all emails received in the last 6 months, classifies, and populates the database.
- `python sync.py` (default): incremental. Reads `MAX(occurred_at)` from `status_events`, fetches emails newer than that timestamp, classifies, and inserts.

### Microsoft Graph specifics

- **Auth**: device-code OAuth flow. First run prints a code and a URL (`microsoft.com/devicelogin`); the user pastes the code there to grant the script `Mail.Read` scope. The refresh token is cached in `~/.application-observability/token.json` so subsequent runs are non-interactive.
- **Endpoint**: `GET /me/messages` with `$filter=receivedDateTime ge <last_sync>`, `$select=id,subject,from,bodyPreview,receivedDateTime`, and `$top=50`. Pagination uses Graph's `@odata.nextLink`.
- **Idempotency**: every message is keyed by Graph `message_id`; the unique constraint on `status_events.email_id` makes duplicate inserts a no-op.

### Schedule

A `launchd` plist (`launchd/com.silas.application-observability.plist`) runs `sync.py` once per hour. Stdout and stderr are appended to `~/.application-observability/logs/sync.log`, rotated weekly via Python's `logging.handlers.TimedRotatingFileHandler`.

### Failure handling

On any error (network, Graph API, auth refresh, classification bug), the script logs the exception and exits non-zero. The next scheduled run picks up where the last successful run left off, since incremental sync is naturally idempotent. No custom retry logic is needed.

## Grafana

Three dashboards in one Grafana instance, all reading the SQLite file via the `frser-sqlite-datasource` plugin. Datasource and dashboard configurations are committed to the repo and auto-provisioned on container start using Grafana's file-based provisioning.

### 1. Summary (default landing page)

- Stat panels: total applications, count by status (`applied`, `next_step`, `rejected`, `offer`), response rate (percentage of applications that have moved past `applied`).
- Table: every company with `company`, `role`, `current_status`, `applied_at`, `status_updated_at`. Sortable and filterable.

### 2. Time series

- Line chart: cumulative applications over time.
- Stacked bar: applications per week, colored by current status.
- Bar chart: response time per company, defined as days between the `applied` event and the next status event.

### 3. Funnel

- Bar gauge in funnel orientation: Applied -> Next Step -> Offer. Rejected count shown as a separate panel.
- Conversion rate annotations between stages (calculated in SQL).

## Repo Layout

```
application-observability/
├── docker-compose.yml
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/sqlite.yml
│   │   └── dashboards/dashboards.yml
│   └── dashboards/
│       ├── summary.json
│       ├── timeseries.json
│       └── funnel.json
├── sync/
│   ├── __init__.py
│   ├── sync.py
│   ├── graph_client.py
│   ├── classifier.py
│   ├── db.py
│   └── rules.yaml
├── launchd/
│   └── com.silas.application-observability.plist
├── tests/
│   ├── test_classifier.py
│   ├── test_db.py
│   └── fixtures/
│       └── sample_emails.json
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-04-20-application-observability-design.md
├── pyproject.toml
├── .gitignore
└── README.md
```

## Testing Strategy

- **Classifier**: unit tests against a fixture file of representative emails (real ATS confirmations, rejections, interview requests, offers, and noise) covering each status and ATS pattern.
- **DB layer**: tests using a temporary SQLite file to verify schema creation, dedup logic, and idempotent inserts.
- **Graph client**: thin wrapper, exercised through manual smoke test on first auth. Not heavily unit tested since Microsoft's API is the integration boundary.

## Operational Concerns

- **Secrets**: only an Azure App Registration client id (public) is needed; OAuth device code flow does not require a client secret. The user creates the registration once and notes the id in `.env`.
- **Backups**: SQLite file lives in the repo's data directory and is excluded from git via `.gitignore`. The user can back it up by copying the file.
- **Log volume**: ~1 KB per email processed, hourly. Rotated weekly. Negligible disk impact.

## Open Questions

None at spec time. All design decisions above are confirmed with the user.
