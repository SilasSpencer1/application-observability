# application-observability

A small local pipeline that turns your inbox into a picture of your job search. It reads job application emails from Outlook, figures out who you applied to and where things stand, stores it in SQLite, and shows it in a handful of Grafana dashboards.

## What it does

Once an hour the sync worker pulls any new messages from your Microsoft 365 mailbox. It classifies each one as `applied`, `next_step`, `rejected`, or `offer` by looking for tell-tale phrases. The results go into a local database. Grafana reads that database and renders three dashboards:

- **Summary** for "where does everything stand right now"
- **Time Series** for "how is activity changing over time"
- **Funnel** for "how often does the first email turn into a real conversation"

Everything runs on your Mac. Nothing gets uploaded anywhere.

## One-time setup

### 1. Register an app in Azure

You need a client id so the sync worker can sign in to Microsoft Graph on your behalf.

1. Open the [Azure portal](https://portal.azure.com) and go to **App registrations**.
2. Click **New registration**. Name it `application-observability`. Leave the account type on the default for your Microsoft 365 tenant.
3. Go to **Authentication**, click **Add a platform**, pick **Mobile and desktop applications**, and tick the `https://login.microsoftonline.com/common/oauth2/nativeclient` redirect. Turn on **Allow public client flows**.
4. Go to **API permissions**, click **Add a permission**, choose **Microsoft Graph**, then **Delegated permissions**, and add `Mail.Read`.
5. Copy the **Application (client) ID** from the overview page. You will use this as `AAO_CLIENT_ID`.

### 2. Install Python dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Backfill the last six months

```bash
AAO_CLIENT_ID=<your-client-id> python -m sync.sync --backfill
```

On first run the script prints a one-time code and a URL. Sign in on any device, approve the access, and the token gets cached so you never see that prompt again.

After it finishes, the database lives at `~/.application-observability/jobs.db`.

### 4. Schedule hourly syncs

1. Open `launchd/com.silas.application-observability.plist` and replace `REPLACE_WITH_YOUR_CLIENT_ID` with the client id from step 1.
2. Make sure the log directory exists:
   ```bash
   mkdir -p ~/.application-observability/logs
   ```
3. Install the plist:
   ```bash
   cp launchd/com.silas.application-observability.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.silas.application-observability.plist
   ```

From here the sync worker runs every hour. If you want a run right now instead of waiting:

```bash
launchctl kickstart gui/$(id -u)/com.silas.application-observability
```

### 5. Start Grafana

```bash
docker compose up -d
```

Open [http://localhost:3000](http://localhost:3000). The three dashboards are pre-loaded. There is no login.

## Daily life

- Logs for the sync worker are at `~/.application-observability/logs/sync.log`. They rotate weekly.
- To change how emails are classified, edit `sync/rules.yaml` and re-run the sync. No code changes needed.
- To manually trigger a sync outside the hourly schedule: `launchctl kickstart gui/$(id -u)/com.silas.application-observability`.

## When things look wrong

**Dashboards are empty.**
Check that the database file has rows:

```bash
sqlite3 ~/.application-observability/jobs.db 'SELECT COUNT(*) FROM applications'
```

If it is zero, the sync has not recorded anything yet. Look at the sync log to see whether it ran, what it saw, and what it classified.

**An email you know you applied to is not showing up.**
The rules are deliberately simple and miss some edge cases. Open `sync/rules.yaml` and add the phrase from the email you are missing. Then re-run: `launchctl kickstart gui/$(id -u)/com.silas.application-observability`.

**The sign-in prompt keeps coming back.**
Delete `~/.application-observability/token.json` and rerun the backfill once to re-authenticate.

**launchd looks silent.**
```bash
launchctl print gui/$(id -u)/com.silas.application-observability
```

The output shows the last exit status and anything launchd logged.

## Tests

```bash
pytest
```

## Layout

- `sync/` is the Python package. One file per responsibility.
- `tests/` is the unit test suite.
- `grafana/` holds the compose stack, provisioning config, and dashboard JSON.
- `launchd/` holds the schedule file.
- `docs/superpowers/specs/` has the design spec.
