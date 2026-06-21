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

Spotify refresh requires a Spotify app Client ID. Set it in `.env`:

```
SPOTIFY_CLIENT_ID=your_client_id_here
```

Create the app at https://developer.spotify.com/dashboard and add `http://127.0.0.1:8765/callback` as the redirect URI with the Web API checkbox enabled.

`serve.py` also respects `REFRESH_BIND_HOST` (default `127.0.0.1`) and `REFRESH_PORT` (default `8765`) env vars.

## Architecture

Three Python modules, no database — all state lives in local JSON files.

**`build_dashboard.py`** — data pipeline. Reads all `music-history/Streaming_History_Audio_*.json` files, computes aggregate statistics (per-day/month/year series, top artists/tracks/albums, heatmap, streak, etc.), serializes the result to a JSON bundle, then injects it into `template.html` by replacing the `__DATA_JSON__` placeholder string. Output is `dashboard.html`. This file is auto-rebuilt by `serve.py` whenever source JSON or `template.html` is newer.

**`spotify_sync.py`** — Spotify API layer. Implements PKCE OAuth (no client secret), fetches the 50 most recently played tracks via `/v1/me/player/recently-played`, maps them to Extended Streaming History-shaped rows, deduplicates by `(ts, spotify_track_uri)` key, and atomically appends new rows to `Streaming_History_Audio_live.json`. Credentials are read from `.env` (`SPOTIFY_CLIENT_ID`) or `spotify_config.json`. Tokens are cached in `spotify_tokens.json` (chmod 600, atomic write).

**`serve.py`** — Flask server. Routes:
- `GET /` — serves `dashboard.html`, triggering a rebuild if stale
- `GET /callback` — receives the OAuth code from Spotify and puts it on `oauth_code_queue`
- `POST /api/refresh` — runs `spotify_sync.sync_incremental()` then `build_dashboard.main()` under a combined threading lock + PID-based file lock (`.refresh.lock`) to prevent concurrent refreshes
- `GET /api/refresh/status` — reads `.refresh.last.json` for last refresh result

**`template.html`** — HTML shell for the dashboard. References `dashboard.js` and `dashboard.css` via `<script src>` / `<link rel>` tags. `build_dashboard.py` injects only the `__DATA_JSON__` blob; charting logic lives in the external JS/CSS files, which Flask serves via `/dashboard.js` and `/dashboard.css` routes. Chart.js is loaded from CDN at runtime (`cdn.jsdelivr.net`); all other charting logic is local.

**`dashboard.js`** — All client-side rendering. Reads `DATA` from a `<script id="dash-data">` tag injected by `build_dashboard.py`. Day-offset arithmetic mirrors the Python bundle: `dayStrToOff` converts calendar dates to integer offsets from `DAY_EPOCH`, so JS and Python indexes stay in sync. Builds Chart.js charts for day/month/year series, heatmap, platform breakdown, and top artists/tracks/albums with a shared date-range filter.

**`dashboard.css`** — All styling for the dashboard.

## Key conventions

- **Display timezone**: `DISPLAY_TZ = ZoneInfo("America/Chicago")` in `build_dashboard.py`. All user-facing day/month/year buckets and the heatmap use this zone, not UTC.
- **Track/album deduplication**: `canon_track_key` and `canon_album_key` normalize to lowercase and join with `\x01` as separator, collapsing duplicate Spotify URIs for the same title+artist.
- **Extended history JSON vs. live JSON**: All `Streaming_History_Audio_*.json` files live in `music-history/`. Year-based export files are read-only; only `Streaming_History_Audio_live.json` is written by `spotify_sync.py`.
- **Day index compression**: `build_dashboard.py` encodes the global `day_series` as `{"i": <days_since_epoch>, "ms": ..., "n": ...}` where the epoch is the calendar date of the first ever play. Per-entity daily data (artists/tracks/albums) uses `compact_days()`, which encodes as `[[i, ms, n], ...]` (3-element lists). JS's `dayOffFromSeriesRow` handles both formats transparently.
- **`is_music_stream()` filter**: Rows with `spotify_episode_uri` (podcasts) or `audiobook_uri` are excluded from all stats. Export JSONs can contain mixed content despite the "Audio" filename.
- **Per-entity data caps**: Only the top 2500 artists, 2600 tracks, and 1400 albums (by `ms_played`) have their per-day arrays included in the bundle, to keep bundle size manageable. Set via `ARTIST_MONTHLY_CAP` / `TRACK_MONTHLY_CAP` / `ALBUM_MONTHLY_CAP` in `build_dashboard.py`.
- **Live row `ms_played` resolution**: The Spotify recently-played API returns track duration, not actual listening time. `resolve_live_ms_played()` post-processes unresolved rows (those with `ms_played_resolved: false`) by computing the time delta between consecutive `played_at` timestamps, capped at track duration. Rows already resolved (`ms_played_resolved: true`) are used as reference points but are not modified. This runs automatically after every sync.
- **Background automation (macOS)**: `com.USERNAME.spotify-refresh.plist` and `com.USERNAME.spotify-serve.plist` in the repo root are launchd agents that run the server and trigger hourly refreshes via `spotify_refresh.sh`. Replace `USERNAME` with your macOS username and load them into `~/Library/LaunchAgents/`.
- **Stale rebuild trigger**: `maybe_rebuild_dashboard()` in `serve.py` compares `dashboard.html` mtime against `template.html` and the newest `music-history/*.json` file — rebuilds automatically on `GET /` if any source is newer.
- **API coverage limit**: `spotify_sync.py` fetches from `/v1/me/player/recently-played` with a cursor-based `after` parameter. The API window is ~50 items per page and covers roughly the last 50 plays Spotify has synced. Offline plays appear only after the device reconnects and syncs to Spotify's servers; if many plays accumulated while offline, plays outside the API window may be missed and must come from a Spotify Extended Streaming History export.
