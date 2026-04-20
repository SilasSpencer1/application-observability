# application-observability

Keep track of where every job you applied to actually stands. Not in a spreadsheet you forget to update. In your inbox, automatically, with charts.

## The idea

Every job application generates a paper trail in your email. A "thanks for applying" here, a "we'd love to chat" there, the occasional rejection, and if you are lucky an offer. It all arrives, and then it all disappears into the pile.

This project quietly reads that pile for you. Once an hour it pulls new messages from your Outlook mailbox, figures out which ones are job related, and tags each one as applied, next step, rejected, or offer. The results land in a local database. Grafana draws three dashboards on top:

- A summary view, for the question "where does everything stand right now"
- A time series view, for the question "am I sending more than I used to, and what's coming back"
- A funnel view, for the question "how often does sending an application actually lead somewhere"

Everything runs on your Mac. None of your mail ever leaves it.

## Setting it up

This takes about fifteen minutes the first time. Most of it is waiting for things to install or clicking through a Microsoft sign in page.

### Tell Microsoft this project can read your mail

The sync worker signs in to your Outlook mailbox the same way any other Microsoft app would. You need to register the project once so it has an identity to sign in as.

1. Open the [Azure portal](https://portal.azure.com) and search for **App registrations**.
2. Click **New registration**. Name it anything you want. `application-observability` is fine. Leave the default account type.
3. After it's created, go to **Authentication** in the side menu. Click **Add a platform**, pick **Mobile and desktop applications**, and check the box next to `https://login.microsoftonline.com/common/oauth2/nativeclient`. Scroll down and turn on **Allow public client flows**. Save.
4. Go to **API permissions**, click **Add a permission**, choose **Microsoft Graph**, then **Delegated permissions**. Find `Mail.Read`, check it, and add it.
5. On the app's overview page, copy the **Application (client) ID**. That's the value you'll use below.

### Install the Python pieces

From the project directory:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

That creates a local virtual environment and pulls in the handful of libraries the sync worker needs.

### Pull your history

Run a one time backfill to load the last six months of mail into the database. Replace the placeholder with the client id you copied a minute ago.

```bash
AAO_CLIENT_ID=<your-client-id> python -m sync.sync --backfill
```

On this first run, Microsoft will print a short code and a URL. Open the URL in any browser, sign in with your school email, and paste the code when asked. That happens once. After that the sync worker remembers who you are.

When it finishes, you'll have a file at `~/.application-observability/jobs.db`. That is your history.

### Keep it running

The sync worker should run on its own from now on, once an hour. macOS does this with something called launchd. There's a small config file in the `launchd/` folder. A couple of steps to install it:

1. Open `launchd/com.silas.application-observability.plist` and replace `REPLACE_WITH_YOUR_CLIENT_ID` with the real client id.
2. Create the folder where logs will live:
   ```bash
   mkdir -p ~/.application-observability/logs
   ```
3. Install and activate the schedule:
   ```bash
   cp launchd/com.silas.application-observability.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.silas.application-observability.plist
   ```

The next run will happen within the hour. If you want to see it work right away, kick it off manually:

```bash
launchctl kickstart gui/$(id -u)/com.silas.application-observability
```

### Start the dashboards

```bash
docker compose up -d
```

Open [http://localhost:3000](http://localhost:3000). No username, no password, the three dashboards are already loaded.

## Day to day

You shouldn't need to do anything. Every hour the worker wakes up, fetches anything new, classifies it, and the charts pick it up on their next refresh.

A few small things worth knowing:

**Logs live at `~/.application-observability/logs/sync.log`.** They rotate weekly, so they never balloon. Useful if something looks off.

**The classifier is driven by a plain text file.** Open `sync/rules.yaml` and you'll see the phrases it looks for. If you spot an email it should have caught but didn't, add a phrase. No code changes.

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
If that is zero, the sync worker hasn't recorded anything yet. Open the log and see what it's doing.

**An email you remember clearly is not showing up.**
The classifier's vocabulary is modest by design. Open `sync/rules.yaml`, add the phrase from the missing email, save, and trigger a sync. It'll pick it up the next time around.

**Microsoft keeps asking you to sign in.**
The token cache might have gotten wiped. Delete it and run the backfill once more to get a fresh one:
```bash
rm ~/.application-observability/token.json
AAO_CLIENT_ID=<your-client-id> python -m sync.sync --backfill
```

**The hourly schedule seems quiet.**
Ask macOS what it thinks of the job:
```bash
launchctl print gui/$(id -u)/com.silas.application-observability
```
The output includes the last exit status and anything launchd itself logged.

## Tests

```bash
pytest
```

## How the project is laid out

- `sync/` is the Python package. One file per job (classifier, database, Graph client, entry point).
- `tests/` is the test suite.
- `grafana/` is the compose stack, the datasource config, and the three dashboard JSON files.
- `launchd/` is the hourly schedule.
- `docs/superpowers/specs/` is the original design document, if you want to know why things are the way they are.
