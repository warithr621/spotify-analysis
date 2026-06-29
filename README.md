# Spotify Analysis Tool

Yay now you can visualize your Spotify listening history!!

# Setup

## Python Environment

1. Create and activate a virtual environment:

	```bash
	python3 -m venv .venv
	source .venv/bin/activate
	```

2. Install the project dependencies:

	```bash
	pip install -r requirements.txt
	```

## Spotify API Setup

This is necessary for the "refresh" feature, which allows you to fetch newer Spotify plays.

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app.
2. Add `http://127.0.0.1:8765/callback` as the Redirect URI, and click the checkox for `Web API` under "APIs used".

3. Copy the app’s Client ID, and paste this into your local `.env` file.

```bash
SPOTIFY_CLIENT_ID=your_client_id_here
```

## Run the app

Start the local server:

```bash
python serve.py
```

Then open the dashboard in your browser:

```text
http://127.0.0.1:8765/
```

From the dashboard, three buttons are available in the top-right corner:
- **Re-authorize** — run the Spotify OAuth flow and store a new refresh token
- **Refresh** — pull the latest data from the cloud data repo and rebuild the dashboard (no Spotify API call)
- **Rescrape** — fetch new plays from Spotify, push them to the cloud data repo, and rebuild the dashboard

# Extended History

Spotify's API only lets you fetch the 50 most recently played songs. If you want your all-time statistics, first request your Extended Streaming History from [this link](https://www.spotify.com/us/account/privacy/). After a few days (it should be way less than the advertised 30 days), you should get emailed a ZIP file with several JSON files, all named something like `Streaming_History_Audio_2026.json`.

Put all these JSONs in the `music-history/` subfolder of this directory and rerun the server — the app will automatically read them and include them in the statistics.

# Cloud Sync (always-on, free)

The local refresh only runs while your computer is on, and Spotify's API only returns the last ~50 plays — so if your machine is off long enough that more than 50 songs play, those in-between plays are lost. Moving the hourly scrape to **GitHub Actions** makes it always-on and free, with no dependency on your computer. The dashboard stays local and **pulls** the cloud data on refresh.

This needs a **separate private repo** to hold your live data (so personal listening history never lands in this public repo). The Spotify refresh token lives in that private repo too (not as an Actions secret), committed atomically with each sync.

1. Create an empty **private** GitHub repo, e.g. `spotify-analysis-data`.
2. Run `python serve.py`, open the dashboard, and click **Re-authorize Spotify (cloud)**. Authorize in the browser; this writes a fresh refresh token to `spotify_tokens.json`.
3. Seed the data repo with two files at its root:
   - `Streaming_History_Audio_live.json` — copy your current `music-history/Streaming_History_Audio_live.json` (or `[]` if none yet).
   - `live_token.json` — `{"refresh_token": "<the refresh_token from spotify_tokens.json>"}`.
4. Create two Personal Access Tokens:
   - **Cloud** (`DATA_REPO_PAT`): fine-grained, Contents **Read and write** on the data repo only. Used by GitHub Actions to check out and commit to the data repo.
   - **Local** (`DATA_REPO_TOKEN`): fine-grained, Contents **Read and write** on the data repo only. Used locally to pull the live buffer and to push a new refresh token when you click **Re-authorize**.
   Give both an expiry and set a calendar reminder.
5. On **this** repo (Settings → Secrets and variables → Actions):
   - Secrets: `SPOTIFY_CLIENT_ID`, `DATA_REPO_PAT`.
   - Variables: `DATA_REPO` (e.g. `yourname/spotify-analysis-data`), and optionally `SPOTIFY_AUTH_DATE` (`YYYY-MM-DD` of step 2, to get a re-auth reminder near the 6-month expiry).
6. Add to your local `.env`:

	```bash
	DATA_REPO=yourname/spotify-analysis-data
	DATA_REPO_TOKEN=your_local_pat
	```

7. Set up hourly triggering via **cron-job.org** (free):
   - Create an account at [cron-job.org](https://cron-job.org).
   - Create a third PAT (fine-grained, **Actions: Read and write** on *this* repo only — not the data repo). This is separate from the two above.
   - Create a new cron job: `POST https://api.github.com/repos/YOUR_USERNAME/spotify-analysis/actions/workflows/spotify-sync.yml/dispatches`, headers `Authorization: Bearer YOUR_PAT`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, body `{"ref":"main"}`, schedule every hour.
   - Hit **Test run** — it should return 204 and a new Actions run should appear within seconds.
8. With your Mac off for over an hour, confirm the data repo still gets hourly commits — that proves it's independent of your computer.

**Every ~6 months:** Spotify refresh tokens expire 6 months after authorization (refreshing does not reset the clock). Just click **Re-authorize** and approve in the browser — the new token is pushed to the data repo automatically, and the next cloud run picks it up. Optionally update the `SPOTIFY_AUTH_DATE` variable so the workflow's expiry warning resets.

> **Note on the 60-day rule:** GitHub disables workflows with no recent activity after 60 days. `keepalive.yml` ships a small heartbeat commit every ~20 days to prevent that. Unlike a `schedule:` trigger, `workflow_dispatch` is not affected by this rule — but the keepalive is still useful to keep the repo active.

# Background Serving (macOS)

These are Mac-only instructions to have the dashboard server start automatically on login and stay running in the background. The hourly scrape is handled entirely by cron-job.org + GitHub Actions — no local background process is needed for that.

1. Replace `USERNAME` in `com.USERNAME.spotify-serve.plist` with your macOS username.

2. Move the plist into `~/Library/LaunchAgents/`.

3. Load it:

	```bash
	plutil -lint ~/Library/LaunchAgents/com.USERNAME.spotify-serve.plist
	launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.USERNAME.spotify-serve.plist
	launchctl kickstart -k gui/$(id -u)/com.USERNAME.spotify-serve
	```