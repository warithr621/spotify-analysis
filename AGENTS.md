# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, etc.) when working with code in this repository. `CLAUDE.md` imports this file, so edit here rather than there.

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

Six Python modules, no database — all state lives in local JSON files.

**`build_dashboard.py`** — data pipeline. Reads all `music-history/Streaming_History_Audio_*.json` files, computes aggregate statistics (per-day/month/year series, top artists/tracks/albums, heatmap, streak, etc.), serializes the result to a JSON bundle, then injects it into `template.html` by replacing the `__DATA_JSON__` placeholder string. Output is `dashboard.html`. This file is auto-rebuilt by `serve.py` whenever source JSON or `template.html` is newer. Also emits `artist_sessions` for the Artist web (see Key conventions).

**`spotify_sync.py`** — Spotify API layer. Implements PKCE OAuth (no client secret), fetches the 50 most recently played tracks via `/v1/me/player/recently-played`, maps them to Extended Streaming History-shaped rows, deduplicates by `(ts, spotify_track_uri)` key, and atomically appends new rows to `Streaming_History_Audio_live.json`. Credentials are read from `.env` (`SPOTIFY_CLIENT_ID`) or `spotify_config.json`. Tokens are cached in `spotify_tokens.json` (chmod 600, atomic write).

**`art_sync.py`** — Fetches real Spotify album art and artist photos for the current top ~12 artists/albums/tracks (by minutes played), for the Rankings podium. Uses `/v1/search` (name + artist query) rather than direct id lookups — `/v1/tracks` and `/v1/artists` return 403 under this app's current Spotify API access tier, but Search remains available and returns the same image data. Search's top hit is unreliable (e.g. "aespa" → IVE), so `_search()` fetches 10 results and caches only one whose artist name matches exactly. Reuses `spotify_sync.ensure_access_token()` for auth. Caches results to `art_cache.json` (gitignored), keyed `artist:<lowercased name>` / `album:<canon_album_key>` / `track:<canon_track_key>`. Best-effort like `cloud_pull.py`: failures are logged and returned as `(False, msg)`, never raised, so a refresh never breaks because art couldn't be fetched.

**`serve.py`** — Flask server. Routes:
- `GET /` — serves `dashboard.html`, triggering a rebuild if stale
- `GET /callback` — receives the OAuth code from Spotify and puts it on `oauth_code_queue`
- `POST /api/pull` — pulls the live buffer from the data repo (if configured) then rebuilds the dashboard. Does NOT call the Spotify API. Triggered by the "Refresh" button.
- `POST /api/refresh` — always runs `cloud_pull.pull_live()` (if configured), then `spotify_sync.sync_incremental()`, then `art_sync.refresh_art_cache()`, then `build_dashboard.main()`, then `cloud_pull.push_live()` (if configured), under a combined threading lock + PID-based file lock (`.refresh.lock`). Operates locally even without cloud credentials. Triggered by the "Rescrape" button.
- `POST /api/authorize` — forces a fresh Spotify PKCE login, stores the new refresh token locally, and pushes it to the data repo. Triggered by the "Re-authorize" button.
- `GET /api/refresh/status` — reads `.refresh.last.json` for last refresh result

**`template.html`** — HTML shell for the dashboard. References `dashboard.js` and `dashboard.css` via `<script src>` / `<link rel>` tags. `build_dashboard.py` injects only the `__DATA_JSON__` blob; charting logic lives in the external JS/CSS files, which Flask serves via `/dashboard.js` and `/dashboard.css` routes. Chart.js and d3 (v7, used only by the Artist web) are loaded from CDN at runtime (`cdn.jsdelivr.net`); all other charting logic is local.

**`dashboard.js`** — All client-side rendering. Reads `DATA` from a `<script id="dash-data">` tag injected by `build_dashboard.py`. Day-offset arithmetic mirrors the Python bundle: `dayStrToOff` converts calendar dates to integer offsets from `DAY_EPOCH`, so JS and Python indexes stay in sync. Builds Chart.js charts for day/month/year series, heatmap, platform breakdown, and top artists/tracks/albums with a shared date-range filter, plus the hand-drawn canvas "Top listens over time" race and the d3 Artist web.

**`dashboard.css`** — All styling for the dashboard.

**`cloud_pull.py`** — Three functions: `pull_live()` pulls the live JSON buffer from the private data repo (GitHub Contents API, with fallback to Git Data API for files >1 MB) into `music-history/Streaming_History_Audio_live.json`; `push_live()` writes the updated buffer back to the data repo after a local sync (uses Git Data API blob/tree/commit to handle files >1 MB); `push_live_token()` rotates the `live_token.json` in the data repo after a token refresh. All three are best-effort: if `DATA_REPO` / `DATA_REPO_TOKEN` are unset or the call fails, they log a warning and return `(False, msg)` without raising.

**`cloud_sync.py`** — Headless orchestrator for the GitHub Actions hourly scrape. Reads the Spotify refresh token from the data-repo checkout (`live_token.json`), calls `spotify_sync` to fetch new plays, and writes the updated live buffer and rotated token back so the workflow can commit them atomically. Env vars: `SPOTIFY_CLIENT_ID`, `SPOTIFY_HISTORY_DIR` (path to the data-repo checkout). Exit code 1 means the refresh token is expired and needs re-authorization locally.

## Key conventions

- **Display timezone**: `DISPLAY_TZ = ZoneInfo("America/Chicago")` in `build_dashboard.py`. All user-facing day/month/year buckets and the heatmap use this zone, not UTC.
- **Track/album deduplication**: `canon_track_key` and `canon_album_key` normalize to lowercase and join with `\x01` as separator, collapsing duplicate Spotify URIs for the same title+artist.
- **Extended history JSON vs. live JSON**: All `Streaming_History_Audio_*.json` files live in `music-history/`. Year-based export files are read-only; only `Streaming_History_Audio_live.json` is written by `spotify_sync.py`. The export files are authoritative for any period they cover — `load_events()` drops live rows whose timestamps fall within the export coverage window (plus a 4-second buffer) before running dedup. This prevents double-counting: Spotify's recently-played API reports `played_at` 0–3 seconds later than the data export records the same play, so exact `(ts, uri)` dedup fails to merge them.
- **Day index compression**: `build_dashboard.py` encodes the global `day_series` as `{"i": <days_since_epoch>, "ms": ..., "n": ...}` where the epoch is the calendar date of the first ever play. Per-entity daily data (artists/tracks/albums) uses `compact_days()`, which encodes as `[[i, ms, n], ...]` (3-element lists). JS's `dayOffFromSeriesRow` handles both formats transparently.
- **`is_music_stream()` filter**: Rows with `spotify_episode_uri` (podcasts) or `audiobook_uri` are excluded from all stats. Export JSONs can contain mixed content despite the "Audio" filename.
- **No per-entity data caps**: Every artist, track, and album gets its per-day array included in the bundle (previously capped at the top 2500/2600/1400 by `ms_played`; the caps were removed since they made the "in window" KPI tiles undercount on large histories).
- **Live row `ms_played` resolution**: The Spotify recently-played API returns track duration, not actual listening time. `resolve_live_ms_played()` post-processes unresolved rows (those with `ms_played_resolved: false`) by computing the time delta between consecutive `played_at` timestamps, capped at track duration. Rows already resolved (`ms_played_resolved: true`) are used as reference points but are not modified. This runs automatically after every sync.
- **Background automation (macOS)**: `com.USERNAME.spotify-serve.plist` in the repo root is a launchd agent that keeps the Flask server running. Replace `USERNAME` with your macOS username and load it into `~/Library/LaunchAgents/`. There is no longer a local hourly refresh plist — cloud-side scraping is handled entirely by the GitHub Actions workflow triggered by cron-job.org.
- **GitHub Actions**: `.github/workflows/spotify-sync.yml` runs `cloud_sync.py` on `workflow_dispatch` only — triggered hourly by cron-job.org via the GitHub API (`POST /repos/warithr621/spotify-analysis/actions/workflows/spotify-sync.yml/dispatches`). The cron-job.org PAT needs **Actions: Read and write** on `spotify-analysis` only. There is no keepalive workflow: GitHub's 60-day auto-disable only applies to `schedule` triggers, which this workflow doesn't use. Required secrets: `SPOTIFY_CLIENT_ID`, `DATA_REPO_PAT` (Contents: Read and write on `spotify-analysis-data`). Required var: `DATA_REPO`. Optional var: `SPOTIFY_AUTH_DATE` (YYYY-MM-DD of last local re-auth, used to warn when the token nears 180-day expiry).
- **Stale rebuild trigger**: `maybe_rebuild_dashboard()` in `serve.py` compares `dashboard.html` mtime against `template.html` and the newest `music-history/*.json` file — rebuilds automatically on `GET /` if any source is newer.
- **API coverage limit**: `spotify_sync.py` fetches from `/v1/me/player/recently-played` with a cursor-based `after` parameter. The API window is ~50 items per page and covers roughly the last 50 plays Spotify has synced. Offline plays appear only after the device reconnects and syncs to Spotify's servers; if many plays accumulated while offline, plays outside the API window may be missed and must come from a Spotify Extended Streaming History export.
- **Rankings layout**: The Rankings section renders three full-width cards (Artists/Albums/Tracks), each a stepped 2nd/1st/3rd podium (top 3, with art) above a scrollable compact list (rank 4+, no art, sticky header). Columns differ by category but are always exactly 3 data fields beside the rank number — Artists: Name/Streams/Minutes; Albums: Album/Artist/Minutes; Tracks: Track/Artist/Minutes (Minutes mode; see Minutes/Plays toggle below for the Plays-mode layout). Rendered by `renderRankSection()` in `dashboard.js`; the search box filters by toggling element visibility (`applySearchVisibility()`) rather than rebuilding the DOM or re-ranking.
- **Minutes/Plays toggle**: The switch fixed top-right below Rescrape (`#metric-switch` in `template.html`) flips a module-level `metric` var in `dashboard.js` between `"minutes"` (default) and `"plays"`, then calls `rebuildRankings()`. It only affects the Rankings section — KPI tiles, the artist-dive chart, the artist datalist, the Top listens race, and the Artist web still rank/sort by minutes regardless of the toggle. `rankArtists`/`rankTracks`/`rankAlbums` take a `metric` param that changes the sort key (`fm` minutes-ms vs `fn` play count). In Plays mode: for artists, the podium's 2nd row becomes plain minutes (no `fmtMin` day/hour hint) and the 3rd row becomes streams, and the list table swaps its Streams/Minutes columns to match (`updateRankHeaders()` relabels the `#hd-artists-2`/`#hd-artists-3` header cells); for albums/tracks, the minutes stat is replaced outright by streams in both the podium and the list column (`#hd-albums-metric`/`#hd-tracks-metric` header relabels to "Streams"). `minutesCellHtml(ms, showHint)` and `streamsCellHtml(n)` are the shared cell renderers behind both modes.
- **Art cache**: `art_cache.json` (gitignored, like `dashboard.html`) maps `artist:<name>` / `album:<key>` / `track:<key>` to a Spotify CDN image URL. Populated by `art_sync.py` (see Architecture); `build_dashboard.py` reads it read-only via `load_art_cache()` and attaches an `image` field to each artist/track/album entry in the bundle when cached. Entities without cached art fall back to a colored initial-letter tile in the frontend (`artHtml()` in `dashboard.js`). `art_sync.py` fetches the top `TOP_N = 12` tracks/albums and the top `ARTIST_TOP_N = 80` artists (enough for the Artist web's "Top 80" setting), so most tracks/albums in the race have no art of their own; the race falls back from track/album art to the artist's photo before the initial-letter tile. Searches with no verified match aren't cached, so they're retried on every Rescrape.
- **Top listens race** (Trends section, `race*` functions in `dashboard.js`): canvas line chart animated over the shared date range. Each line is one artist/track/album; its value on a given day is minutes in a trailing 7/30/90-day window, or cumulative for "All time". `buildRaceData()` builds dense per-day arrays for a candidate pool (`RACE_POOL`: top 400 artists / 700 albums / 1500 tracks by all-time minutes) and marks each day's top `RACE_TOP` (10) as shown. The artist filter (chips) is "only these" or "hide these"; in "only" mode for artists, up to `RACE_TOP_MAX` (15) lines are shown. Rebuilt by `renderRace()` on date-range change (from `renderCharts()`); kind/trail/filter changes go through `raceRebuild()`, which keeps the playhead position. Autoplays once on screen via `IntersectionObserver`; respects `prefers-reduced-motion` (jumps to the final frame).
- **Artist web** (`#artist-web` section, `buildWebGraph()` / `renderArtistWeb()`): d3 force graph linking top artists played in the same listening session (Spotify's related-artists endpoint is unavailable to new apps). Python side: `build_artist_sessions()` splits plays into sessions at gaps > `GRAPH_SESSION_GAP` (30 min), counting only plays ≥ `GRAPH_MIN_PLAY_MS` (30s) and skipping "Unknown Artist"; each session with 2+ of the top `GRAPH_ARTIST_CAP` (400) artists is emitted as `[day_index, [artist_idx, ...]]` in `DATA.artist_sessions`, where `artist_idx` indexes `DATA.graph_artists` (the 400 names). JS side: pairs need ≥ `WEB_MIN_SHARED` (2) shared sessions in the date range; strength is cosine-normalised (`shared / sqrt(sessA * sessB)`, where `sess` counts in-range sessions with at least one other displayed artist) so heavy-rotation artists don't link to everything. Link selection: every artist keeps its single strongest link, then more are added strongest-first only while **both** ends are under `WEB_LINKS_PER_NODE` (3) — an "either end under the cap" rule let hub artists collect 20+ links. Clusters come from weighted label propagation, ordered by total minutes, coloured from `WEB_PALETTE`, and named in the legend after their top artist. (Down-weighting large sessions by `1/(k−1)` was tried and made hubs worse; Louvain found the same clusters as label propagation.) The layout is settled synchronously (`webSim.tick(300)`) then zoom-fitted (`webFit`, also the Reset view button); positions are remembered by name in `webPos` so re-renders keep their shape. Only the top `WEB_LABELS` (15) artists are labelled until highlighted. Hover shows a tooltip; click pins the highlight and opens `#web-panel` with an "Open in Artist dive" button; clicking the background unpins. The hint reports artists hidden for having no links and in-range top artists outside the all-time top 400 (untracked).
