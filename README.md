# application-observability

Keep track of where every job you applied to actually stands. Not in a spreadsheet you forget to update. In your inbox, automatically, with charts.

## The idea

Every job application generates a paper trail in your email. A "thanks for applying" here, a "we'd love to chat" there, the occasional rejection, and if you are lucky an offer. It all arrives, and then it all disappears into the pile.

This project quietly reads that pile for you. Once an hour it pulls new messages from your mailbox, figures out which ones are job related, and tags each one as applied, next step, rejected, or offer. The results land in a local database. Grafana draws three dashboards on top:

- A summary view, for the question "where does everything stand right now"
- A time series view, for the question "am I sending more than I used to, and what's coming back"
- A funnel view, for the question "how often does sending an application actually lead somewhere"

Everything runs on your Mac. None of your mail ever leaves it.

## Pick your mail provider

The project reads mail from one of two providers. Gmail is the default and easiest to set up. Outlook works too, but most school and work Microsoft tenants require admin approval before an app can read mail, which can take a while.

| Provider | Env variable | Who it's for |
| --- | --- | --- |
| `gmail` | `AAO_PROVIDER=gmail` (default) | Personal Gmail accounts |
| `graph` | `AAO_PROVIDER=graph` | Outlook / Microsoft 365 |

If you never set `AAO_PROVIDER`, the sync worker uses Gmail.

## Setting it up with Gmail

Budget about ten minutes the first time.

### Turn on the Gmail API in Google Cloud

The sync worker needs a small OAuth credential so Google knows which app is asking to read mail.

1. Open [console.cloud.google.com](https://console.cloud.google.com) and sign in with the Gmail account you want to track.
2. Create a new project. Call it anything, `application-observability` is fine.
3. Use the search bar to find **Gmail API** and enable it.
4. Go to **APIs & Services → OAuth consent screen**. Pick **External**, fill in the app name, your email as support and developer contact. On the scopes page click **Save and continue**. On the test users page, add your own Gmail address so Google lets you through the unpublished-app warning.
5. Go to **APIs & Services → Credentials**, click **Create credentials → OAuth client ID**, pick **Desktop app**, and name it. Click **Download JSON** and save the file somewhere on your machine.

### Install the Python pieces

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Pull your history

Point the sync worker at the JSON file you downloaded and run a backfill:

```bash
AAO_GOOGLE_CREDENTIALS=/path/to/your/client_secret.json python -m sync.sync --backfill
```

On the first run a browser window opens and asks you to grant the app permission to read your mail. Click through. Google caches the refresh token at `~/.application-observability/gmail_token.json` so you never see the prompt again.

When it finishes you'll have a database at `~/.application-observability/jobs.db`.

## Setting it up with Outlook

Only use this path if you want to pull from an Outlook or Microsoft 365 mailbox. Most school tenants require admin approval, so expect some back and forth with IT.

1. Register an app in the [Azure portal](https://portal.azure.com) under **App registrations**. On the **Authentication** tab add a mobile/desktop platform with the `https://login.microsoftonline.com/common/oauth2/nativeclient` redirect, and turn on **Allow public client flows**. On the **API permissions** tab add the `Mail.Read` delegated permission on Microsoft Graph.
2. Copy the Application (client) ID. For single-tenant accounts, also grab the tenant id from **Entra ID → Overview**.
3. Install Python deps (same commands as above).
4. Run a backfill:
   ```bash
   AAO_PROVIDER=graph AAO_CLIENT_ID=<your-client-id> AAO_TENANT=<your-tenant-id> python -m sync.sync --backfill
   ```
   On the first run Microsoft prints a short code and a URL. Open it in any browser, sign in, paste the code.

## Keep it running

The sync worker should run on its own, once an hour. macOS does this with launchd. Install the schedule:

1. Open `launchd/com.silas.application-observability.plist` and fill in the credentials path. It ships set up for Gmail (`AAO_PROVIDER=gmail` and `AAO_GOOGLE_CREDENTIALS`). If you're using Outlook, swap those for `AAO_PROVIDER=graph`, `AAO_CLIENT_ID`, and `AAO_TENANT`.
2. Create the log folder:
   ```bash
   mkdir -p ~/.application-observability/logs
   ```
3. Install and activate:
   ```bash
   cp launchd/com.silas.application-observability.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.silas.application-observability.plist
   ```

Trigger a run right now instead of waiting an hour:
```bash
launchctl kickstart gui/$(id -u)/com.silas.application-observability
```

## Start the dashboards

```bash
docker compose up -d
```

Open [http://localhost:3000](http://localhost:3000). No username, no password, the three dashboards are already loaded.

## Day to day

You shouldn't need to do anything. Every hour the worker wakes up, fetches anything new, classifies it, and the charts pick it up on their next refresh.

**Logs live at `~/.application-observability/logs/sync.log`.** They rotate weekly. Useful if something looks off.

**The classifier is driven by a plain text file.** Open `sync/rules.yaml` and you'll see the phrases it looks for. If an email got missed, add a phrase.

**To run a sync without waiting for the hourly tick:**
```bash
launchctl kickstart gui/$(id -u)/com.silas.application-observability
```

## When something doesn't look right

**The dashboards are empty.**
Check whether the database has anything in it:
```bash
sqlite3 ~/.application-observability/jobs.db 'SELECT COUNT(*) FROM applications'
```
If that is zero, the sync worker hasn't recorded anything yet. Open the log.

**An email you remember clearly is not showing up.**
The classifier's vocabulary is modest by design. Open `sync/rules.yaml`, add the phrase from the missing email, save, and trigger a sync.

**Sign in keeps coming back.**
The token cache may have expired or been wiped. Delete it and run the backfill once more.

Gmail:
```bash
rm ~/.application-observability/gmail_token.json
AAO_GOOGLE_CREDENTIALS=/path/to/client_secret.json python -m sync.sync --backfill
```

Outlook:
```bash
rm ~/.application-observability/token.json
AAO_PROVIDER=graph AAO_CLIENT_ID=<id> AAO_TENANT=<tenant> python -m sync.sync --backfill
```

**The hourly schedule seems quiet.**
```bash
launchctl print gui/$(id -u)/com.silas.application-observability
```
The output includes the last exit status and anything launchd logged.

## Tests

```bash
pytest
```

## How the project is laid out

- `sync/` is the Python package. One file per job: classifier, database, Gmail client, Graph client, entry point.
- `tests/` is the test suite.
- `grafana/` is the compose stack, the datasource config, and the three dashboard JSON files.
- `launchd/` is the hourly schedule.
- `docs/superpowers/specs/` is the original design document, if you want to know why things are the way they are.
