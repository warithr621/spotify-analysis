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

From the dashboard, click **Refresh Spotify data** to authorize Spotify and fetch newer plays.

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
4. Create two fine-grained Personal Access Tokens:
   - **Cloud** (`DATA_REPO_PAT`): Contents **Read and write** on the data repo only.
   - **Local** (`DATA_REPO_TOKEN`): Contents **Read** on the data repo only.
   Give both an expiry and set a calendar reminder.
5. On **this** repo (Settings → Secrets and variables → Actions):
   - Secrets: `SPOTIFY_CLIENT_ID`, `DATA_REPO_PAT`.
   - Variables: `DATA_REPO` (e.g. `yourname/spotify-analysis-data`), and optionally `SPOTIFY_AUTH_DATE` (`YYYY-MM-DD` of step 2, to get a re-auth reminder near the 6-month expiry).
6. Add to your local `.env`:

	```bash
	DATA_REPO=yourname/spotify-analysis-data
	DATA_REPO_TOKEN=your_local_read_pat
	```

7. Enable Actions on this repo, then run **Spotify hourly sync → Run workflow** once. Confirm it's green and a new commit appears in the data repo.
8. With your Mac off for over an hour, confirm the data repo still gets hourly commits — that proves it's independent of your computer.

Once `DATA_REPO` and `DATA_REPO_TOKEN` are set in `.env`, the dashboard's **Refresh Spotify data** button pulls the cloud buffer instead of calling Spotify directly. With them unset, it behaves exactly as before (direct local Spotify sync), so nothing breaks before you finish setup.

**Every ~6 months:** Spotify refresh tokens expire 6 months after authorization (refreshing does not reset the clock). Repeat step 2, then commit the new `live_token.json` to the data repo with your own git credentials (the local PAT is read-only), and update `SPOTIFY_AUTH_DATE`.

> **Note on the 60-day rule:** GitHub disables scheduled workflows after 60 days with no repo activity. `keepalive.yml` ships a small heartbeat commit every ~20 days to prevent that.

# Background Serving and Refreshing

These are Mac-only instructions if you wish to have the dashboard serve in the background, and automatically refresh every hour while your computer is on. With cloud sync configured, the hourly local refresh becomes a **pull** of the cloud data rather than a direct Spotify call.

1. Install `launchctl` if you don't have it already:

	```bash
	brew install launchctl
	```

2. Replace the `USERNAME` in both `.plist` files of this directory with your computer's username. Do the same in the `[USERNAME]` section of both of these, as well as the `spotify_refresh.sh` file.

3. Create the directory `/Users/[USERNAME]/Library/Application Support/spotify-dashboard`, and move the script `spotify_refresh.sh` there.

4. Move the two `.plist` files into `~/Library/LaunchAgents/`.

5. Run the following commands:

	```bash
	plutil -lint ~/Library/LaunchAgents/com.USERNAME.spotify-refresh.plist
	plutil -lint ~/Library/LaunchAgents/com.USERNAME.spotify-serve.plist
	launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.USERNAME.spotify-refresh.plist
	launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.USERNAME.spotify-serve.plist
	launchctl kickstart -k gui/$(id -u)/com.USERNAME.spotify-serve
	```