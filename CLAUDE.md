# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
source ~/venv/bin/activate
pip install -r requirements.txt
python serve.py          # serves at http://127.0.0.1:8765/
```

To regenerate `dashboard.html` without starting the server:

```bash
python build_dashboard.py
```

To run the test suite (no dependencies beyond the project itself):

```bash
python test_merge_dedup.py
```

Spotify refresh requires a Spotify app Client ID. Set it in `.env`:

```
SPOTIFY_CLIENT_ID=your_client_id_here
```

Create the app at https://developer.spotify.com/dashboard and add `http://127.0.0.1:8765/callback` as the redirect URI with the Web API checkbox enabled.

`serve.py` also respects `REFRESH_BIND_HOST` (default `127.0.0.1`) and `REFRESH_PORT` (default `8765`) env vars.

For cloud sync, also set in `.env`:

```
DATA_REPO=yourname/spotify-analysis-data
DATA_REPO_TOKEN=your_github_pat
```

`DATA_REPO_TOKEN` needs **Contents: Read and write** permission — it's used both to pull and to push the live buffer back after a local refresh.

## Architecture

Three Python modules, no database — all state lives in local JSON files.

**`build_dashboard.py`** — data pipeline. Reads all `music-history/Streaming_History_Audio_*.json` files, computes aggregate statistics (per-day/month/year series, top artists/tracks/albums, heatmap, streak, etc.), serializes the result to a JSON bundle, then injects it into `template.html` by replacing the `__DATA_JSON__` placeholder string. Output is `dashboard.html`. This file is auto-rebuilt by `serve.py` whenever source JSON or `template.html` is newer.

**`spotify_sync.py`** — Spotify API layer. Implements PKCE OAuth (no client secret), fetches the 50 most recently played tracks via `/v1/me/player/recently-played`, maps them to Extended Streaming History-shaped rows, deduplicates by `(ts, spotify_track_uri)` key, and atomically appends new rows to `Streaming_History_Audio_live.json`. Credentials are read from `.env` (`SPOTIFY_CLIENT_ID`) or `spotify_config.json`. Tokens are cached in `spotify_tokens.json` (chmod 600, atomic write).

**`serve.py`** — Flask server. Routes:
- `GET /` — serves `dashboard.html`, triggering a rebuild if stale
- `GET /callback` — receives the OAuth code from Spotify and puts it on `oauth_code_queue`
- `POST /api/pull` — pulls the live buffer from the data repo (if configured) then rebuilds the dashboard. Does NOT call the Spotify API. Triggered by the "Refresh" button.
- `POST /api/refresh` — always runs `cloud_pull.pull_live()` (if configured), then `spotify_sync.sync_incremental()`, then `build_dashboard.main()`, then `cloud_pull.push_live()` (if configured), under a combined threading lock + PID-based file lock (`.refresh.lock`). Operates locally even without cloud credentials. Triggered by the "Rescrape" button.
- `POST /api/authorize` — forces a fresh Spotify PKCE login, stores the new refresh token locally, and pushes it to the data repo. Triggered by the "Re-authorize" button.
- `GET /api/refresh/status` — reads `.refresh.last.json` for last refresh result

**`template.html`** — HTML shell for the dashboard. References `dashboard.js` and `dashboard.css` via `<script src>` / `<link rel>` tags. `build_dashboard.py` injects only the `__DATA_JSON__` blob; charting logic lives in the external JS/CSS files, which Flask serves via `/dashboard.js` and `/dashboard.css` routes. Chart.js is loaded from CDN at runtime (`cdn.jsdelivr.net`); all other charting logic is local.

**`dashboard.js`** — All client-side rendering. Reads `DATA` from a `<script id="dash-data">` tag injected by `build_dashboard.py`. Day-offset arithmetic mirrors the Python bundle: `dayStrToOff` converts calendar dates to integer offsets from `DAY_EPOCH`, so JS and Python indexes stay in sync. Builds Chart.js charts for day/month/year series, heatmap, platform breakdown, and top artists/tracks/albums with a shared date-range filter.

**`dashboard.css`** — All styling for the dashboard.

**`cloud_pull.py`** — Three functions: `pull_live()` pulls the live JSON buffer from the private data repo (GitHub Contents API, with fallback to Git Data API for files >1 MB) into `music-history/Streaming_History_Audio_live.json`; `push_live()` writes the updated buffer back to the data repo after a local sync (uses Git Data API blob/tree/commit to handle files >1 MB); `push_live_token()` rotates the `live_token.json` in the data repo after a token refresh. All three are best-effort: if `DATA_REPO` / `DATA_REPO_TOKEN` are unset or the call fails, they log a warning and return `(False, msg)` without raising.

**`cloud_sync.py`** — Headless orchestrator for the GitHub Actions hourly scrape. Reads the Spotify refresh token from the data-repo checkout (`live_token.json`), calls `spotify_sync` to fetch new plays, and writes the updated live buffer and rotated token back so the workflow can commit them atomically. Env vars: `SPOTIFY_CLIENT_ID`, `SPOTIFY_HISTORY_DIR` (path to the data-repo checkout). Exit code 1 means the refresh token is expired and needs re-authorization locally.

## Key conventions

- **Display timezone**: `DISPLAY_TZ = ZoneInfo("America/Chicago")` in `build_dashboard.py`. All user-facing day/month/year buckets and the heatmap use this zone, not UTC.
- **Track/album deduplication**: `canon_track_key` and `canon_album_key` normalize to lowercase and join with `\x01` as separator, collapsing duplicate Spotify URIs for the same title+artist.
- **Extended history JSON vs. live JSON**: All `Streaming_History_Audio_*.json` files live in `music-history/`. Year-based export files are read-only; only `Streaming_History_Audio_live.json` is written by `spotify_sync.py`. The export files are authoritative for any period they cover — `load_events()` drops live rows whose timestamps fall within the export coverage window (plus a 4-second buffer) before running dedup. This prevents double-counting: Spotify's recently-played API reports `played_at` 0–3 seconds later than the data export records the same play, so exact `(ts, uri)` dedup fails to merge them.
- **Day index compression**: `build_dashboard.py` encodes the global `day_series` as `{"i": <days_since_epoch>, "ms": ..., "n": ...}` where the epoch is the calendar date of the first ever play. Per-entity daily data (artists/tracks/albums) uses `compact_days()`, which encodes as `[[i, ms, n], ...]` (3-element lists). JS's `dayOffFromSeriesRow` handles both formats transparently.
- **`is_music_stream()` filter**: Rows with `spotify_episode_uri` (podcasts) or `audiobook_uri` are excluded from all stats. Export JSONs can contain mixed content despite the "Audio" filename.
- **Per-entity data caps**: Only the top 2500 artists, 2600 tracks, and 1400 albums (by `ms_played`) have their per-day arrays included in the bundle, to keep bundle size manageable. Set via `ARTIST_MONTHLY_CAP` / `TRACK_MONTHLY_CAP` / `ALBUM_MONTHLY_CAP` in `build_dashboard.py`.
- **Live row `ms_played` resolution**: The Spotify recently-played API returns track duration, not actual listening time. `resolve_live_ms_played()` post-processes unresolved rows (those with `ms_played_resolved: false`) by computing the time delta between consecutive `played_at` timestamps, capped at track duration. Rows already resolved (`ms_played_resolved: true`) are used as reference points but are not modified. This runs automatically after every sync.
- **Background automation (macOS)**: `com.USERNAME.spotify-serve.plist` in the repo root is a launchd agent that keeps the Flask server running. Replace `USERNAME` with your macOS username and load it into `~/Library/LaunchAgents/`. There is no longer a local hourly refresh plist — cloud-side scraping is handled entirely by the GitHub Actions workflow triggered by cron-job.org.
- **GitHub Actions**: `.github/workflows/spotify-sync.yml` runs `cloud_sync.py` on `workflow_dispatch` only — triggered hourly by cron-job.org via the GitHub API (`POST /repos/warithr621/spotify-analysis/actions/workflows/spotify-sync.yml/dispatches`). The cron-job.org PAT needs **Actions: Read and write** on `spotify-analysis` only. `.github/workflows/keepalive.yml` makes a heartbeat commit every ~20 days to prevent GitHub from disabling the workflow after 60 days idle. Required secrets: `SPOTIFY_CLIENT_ID`, `DATA_REPO_PAT` (Contents: Read and write on `spotify-analysis-data`). Required var: `DATA_REPO`. Optional var: `SPOTIFY_AUTH_DATE` (YYYY-MM-DD of last local re-auth, used to warn when the token nears 180-day expiry).
- **Stale rebuild trigger**: `maybe_rebuild_dashboard()` in `serve.py` compares `dashboard.html` mtime against `template.html` and the newest `music-history/*.json` file — rebuilds automatically on `GET /` if any source is newer.
- **API coverage limit**: `spotify_sync.py` fetches from `/v1/me/player/recently-played` with a cursor-based `after` parameter. The API window is ~50 items per page and covers roughly the last 50 plays Spotify has synced. Offline plays appear only after the device reconnects and syncs to Spotify's servers; if many plays accumulated while offline, plays outside the API window may be missed and must come from a Spotify Extended Streaming History export.
