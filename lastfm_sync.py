#!/usr/bin/env python3
"""Fetches and caches Last.fm artist tags (for the Taste River) and similar
artists for the top artists.

Spotify's related-artists endpoint is closed to new apps, so Last.fm's
`artist.getSimilar` (listener-overlap based) stands in for it, and
`artist.getTopTags` supplies user-voted tags. Read-only calls need only an API
key (`LASTFM_API_KEY` in `.env`); no secret or login flow.

Best-effort like art_sync.py and cloud_pull.py: failures are logged and
returned as `(False, msg)`, never raised, so a refresh never breaks because
Last.fm was unreachable. Run `python lastfm_sync.py` to fill the whole cache
(~2 requests per artist); the server's Rescrape only tops up a small batch.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

import build_dashboard
import spotify_sync

BASE = Path(__file__).resolve().parent
CACHE_PATH = BASE / "lastfm_cache.json"

API_URL = "https://ws.audioscrobbler.com/2.0/"

# Same artist set the session graph tracks, so every cached artist can appear in the web.
TOP_ARTISTS = build_dashboard.GRAPH_ARTIST_CAP
STALE_AFTER = timedelta(days=30)
SIMILAR_LIMIT = 60
MIN_TAG_COUNT = 20  # Last.fm tag weight (0-100) below which a tag is noise
MAX_TAGS = 5
REQUEST_GAP_S = 0.2  # min spacing between requests across all threads (~5/second, Last.fm's guideline)
WORKERS = 4  # parallel fetches; the shared limiter above still caps the overall rate
BATCH_LIMIT = 25  # artists fetched per server refresh (~10 s; CLI fetches all)

# Generic tags that say nothing about the music.
TAG_BLACKLIST = {
    "seen live", "favorites", "favourites", "favorite", "favourite", "my favorites",
    "albums i own", "love", "awesome", "good", "beautiful", "best", "all", "spotify",
    "under 2000 listeners", "love at first listen", "check out", "cool", "amazing",
}
_YEAR_TAG = re.compile(r"^(?:\d{2}|\d{4})s?$")

logger = logging.getLogger(__name__)


def load_cache() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    tmp = tempfile.NamedTemporaryFile(mode="w", dir=BASE, delete=False, suffix=".tmp", encoding="utf-8")
    try:
        json.dump(cache, tmp, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, CACHE_PATH)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def clean_tags(raw: list[dict], artist_name: str) -> list[str]:
    """Lowercased top tags by weight, minus generic/year/self-named noise."""
    out: list[str] = []
    own = artist_name.strip().lower()
    for t in sorted(raw or [], key=lambda t: -int(t.get("count") or 0)):
        name = (t.get("name") or "").strip().lower()
        if int(t.get("count") or 0) < MIN_TAG_COUNT:
            break
        if not name or name in TAG_BLACKLIST or name == own or _YEAR_TAG.match(name) or name in out:
            continue
        out.append(name)
        if len(out) >= MAX_TAGS:
            break
    return out


def parse_similar(raw: list[dict]) -> list[list]:
    """`[[name, match], ...]` with match in 0..1, strongest first."""
    out = []
    for s in raw or []:
        name = (s.get("name") or "").strip()
        try:
            match = float(s.get("match") or 0)
        except (TypeError, ValueError):
            continue
        if name and match > 0:
            out.append([name, round(match, 3)])
    out.sort(key=lambda x: -x[1])
    return out


_rate_lock = threading.Lock()
_next_ok = 0.0


def _throttle() -> None:
    """Block until this request may start; spaces requests REQUEST_GAP_S apart across threads."""
    global _next_ok
    with _rate_lock:
        now = time.monotonic()
        wait = _next_ok - now
        _next_ok = max(now, _next_ok) + REQUEST_GAP_S
    if wait > 0:
        time.sleep(wait)


def _call(api_key: str, method: str, artist: str, **extra) -> dict:
    params = {"method": method, "artist": artist, "autocorrect": 1, "api_key": api_key, "format": "json", **extra}
    for attempt in range(3):
        _throttle()
        r = requests.get(API_URL, params=params, timeout=15)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise requests.RequestException(f"Last.fm {method} kept failing for {artist!r}")


def fetch_artist(api_key: str, name: str) -> dict:
    """One cache entry for `name`. Unknown artists (Last.fm error 6) get an empty
    entry so they aren't re-requested until the entry goes stale."""
    sim = _call(api_key, "artist.getSimilar", name, limit=SIMILAR_LIMIT)
    if sim.get("error") == 6:
        return {"name": name, "tags": [], "similar": [], "fetched": date.today().isoformat()}
    if "error" in sim:
        raise requests.RequestException(f"Last.fm error {sim['error']}: {sim.get('message')}")
    tags = _call(api_key, "artist.getTopTags", name)
    canonical = ((sim.get("similarartists") or {}).get("@attr") or {}).get("artist") or name
    return {
        "name": canonical,
        "tags": clean_tags((tags.get("toptags") or {}).get("tag"), name),
        "similar": parse_similar((sim.get("similarartists") or {}).get("artist")),
        "fetched": date.today().isoformat(),
    }


def _is_stale(entry: dict | None) -> bool:
    if not entry:
        return True
    try:
        return date.today() - date.fromisoformat(entry["fetched"]) > STALE_AFTER
    except (KeyError, ValueError):
        return True


def _top_artist_names(limit: int) -> list[str]:
    ms: defaultdict[str, int] = defaultdict(int)
    for r in build_dashboard.load_events():
        if not build_dashboard.is_music_stream(r):
            continue
        n = int(r.get("ms_played") or 0)
        if n <= 0:
            continue
        name = (r.get("master_metadata_album_artist_name") or "Unknown Artist").strip()
        ms[name] += n
    ms.pop("Unknown Artist", None)
    return sorted(ms, key=lambda a: (-ms[a], a.lower()))[:limit]


def refresh_cache(limit: int | None = BATCH_LIMIT) -> tuple[bool, str]:
    """Fetch tags + similar artists for top artists that are missing or stale
    (at most `limit` artists per call; None = all). Never raises."""
    try:
        spotify_sync.prime_local_env()
        api_key = (os.environ.get("LASTFM_API_KEY") or "").strip()
        if not api_key:
            return False, "LASTFM_API_KEY not set; skipping Last.fm."

        cache = load_cache()
        todo = [a for a in _top_artist_names(TOP_ARTISTS) if _is_stale(cache.get(f"artist:{a.lower()}"))]
        remaining = max(0, len(todo) - (limit or len(todo)))
        todo = todo[:limit] if limit else todo
        if not todo:
            return True, "Last.fm cache already up to date."

        lock = threading.Lock()
        progress = {"fetched": 0, "failed": 0}

        def work(name: str) -> None:
            try:
                entry = fetch_artist(api_key, name)
            except (requests.RequestException, ValueError) as e:
                logger.warning("Last.fm fetch failed for %r: %s", name, e)
                with lock:
                    progress["failed"] += 1
                return
            with lock:
                cache[f"artist:{name.lower()}"] = entry
                progress["fetched"] += 1
                n = progress["fetched"]
                if n % 100 == 0:
                    _save_cache(cache)  # keep progress on long runs
                    logger.info("Last.fm: %d/%d artists fetched", n, len(todo))

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(work, todo))
        _save_cache(cache)
        fetched = progress["fetched"]
        msg = f"Fetched Last.fm data for {fetched} artist(s)."
        return True, msg + (f" {remaining} more pending." if remaining else "")
    except Exception as e:
        logger.warning("Last.fm refresh failed (non-fatal): %s", e)
        return False, f"Last.fm refresh failed: {e}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ok, msg = refresh_cache(limit=None)
    print(("OK: " if ok else "FAILED: ") + msg)
