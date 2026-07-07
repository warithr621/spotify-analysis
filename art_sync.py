#!/usr/bin/env python3
"""Fetches and caches real Spotify album/artist art for the top-ranked
artists, albums, and tracks shown in the dashboard's Rankings section.

Spotify's direct catalog lookups (Get Track(s) / Get Artist(s) by id) return
403 for this app under Spotify's current API access tier, so this uses the
Search endpoint instead (name + artist query), which remains available and
returns the same image data.

Best-effort like cloud_pull.py: any failure is logged and reported via the
return value rather than raised, so a refresh never breaks because art
couldn't be fetched.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import defaultdict
from pathlib import Path

import requests

import build_dashboard
import spotify_sync

BASE = Path(__file__).resolve().parent
ART_CACHE_PATH = BASE / "art_cache.json"

SEARCH_URL = "https://api.spotify.com/v1/search"

# Only the entities actually shown with art (the top-3 podium per category)
# need images, but we fetch a little extra headroom so the cache stays warm
# if the top-3 shuffle between refreshes.
TOP_N = 12

logger = logging.getLogger(__name__)


def load_art_cache() -> dict:
    try:
        with open(ART_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_art_cache(cache: dict) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=BASE, delete=False, suffix=".tmp", encoding="utf-8"
    )
    try:
        json.dump(cache, tmp, indent=2, sort_keys=True)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, ART_CACHE_PATH)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def _top_entities_needing_art(
    events: list[dict], cache: dict
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]], list[str]]:
    """Lightweight re-aggregation (mirrors build_dashboard's grouping, minus the
    daily breakdown) to find the top-N canonical artist/album/track keys not
    already cached, each mapped to a (name, artist) pair to search for."""
    track_ms: defaultdict[str, int] = defaultdict(int)
    track_display: dict[str, tuple[str, str]] = {}
    album_ms: defaultdict[str, int] = defaultdict(int)
    album_display: dict[str, tuple[str, str]] = {}
    artist_ms: defaultdict[str, int] = defaultdict(int)

    for r in events:
        if not build_dashboard.is_music_stream(r):
            continue
        ms = int(r.get("ms_played") or 0)
        if ms <= 0:
            continue
        artist_name = (r.get("master_metadata_album_artist_name") or "Unknown Artist").strip()
        track_name = (r.get("master_metadata_track_name") or "Unknown Track").strip()
        album_name = (r.get("master_metadata_album_album_name") or "Unknown Album").strip()

        tkey = build_dashboard.canon_track_key(track_name, artist_name)
        track_ms[tkey] += ms
        track_display.setdefault(tkey, (track_name, artist_name))

        akey = build_dashboard.canon_album_key(album_name, artist_name)
        album_ms[akey] += ms
        album_display.setdefault(akey, (album_name, artist_name))

        artist_ms[artist_name] += ms

    top_track_keys = sorted(track_ms.keys(), key=lambda k: -track_ms[k])[:TOP_N]
    top_album_keys = sorted(album_ms.keys(), key=lambda k: -album_ms[k])[:TOP_N]
    top_artist_names = sorted(artist_ms.keys(), key=lambda a: -artist_ms[a])[:TOP_N]

    need_tracks = {k: track_display[k] for k in top_track_keys if f"track:{k}" not in cache}
    need_albums = {k: album_display[k] for k in top_album_keys if f"album:{k}" not in cache}
    need_artists = [a for a in top_artist_names if f"artist:{a.lower()}" not in cache]
    return need_tracks, need_albums, need_artists


def _search(headers: dict, query: str, entity_type: str) -> dict | None:
    r = requests.get(
        SEARCH_URL, headers=headers, params={"q": query, "type": entity_type, "limit": 1}, timeout=15
    )
    r.raise_for_status()
    items = (r.json().get(f"{entity_type}s") or {}).get("items") or []
    return items[0] if items else None


def refresh_art_cache() -> tuple[bool, str]:
    """Fetch real Spotify art (via Search) for any top artist/album/track not
    already cached, and merge it into art_cache.json. Never raises."""
    try:
        cache = load_art_cache()
        events = build_dashboard.load_events()
        need_tracks, need_albums, need_artists = _top_entities_needing_art(events, cache)

        if not (need_tracks or need_albums or need_artists):
            return True, "Art cache already up to date."

        token = spotify_sync.ensure_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        fetched = 0

        for tkey, (title, artist) in need_tracks.items():
            try:
                item = _search(headers, f"{title} {artist}", "track")
                images = ((item or {}).get("album") or {}).get("images") or []
                if images:
                    cache[f"track:{tkey}"] = images[-1]["url"]
                    fetched += 1
            except requests.RequestException as e:
                logger.warning("Track art search failed for %r: %s", title, e)

        for akey, (album, artist) in need_albums.items():
            try:
                item = _search(headers, f"{album} {artist}", "album")
                images = (item or {}).get("images") or []
                if images:
                    cache[f"album:{akey}"] = images[-1]["url"]
                    fetched += 1
            except requests.RequestException as e:
                logger.warning("Album art search failed for %r: %s", album, e)

        for name in need_artists:
            try:
                item = _search(headers, name, "artist")
                images = (item or {}).get("images") or []
                if images:
                    cache[f"artist:{name.lower()}"] = images[-1]["url"]
                    fetched += 1
            except requests.RequestException as e:
                logger.warning("Artist art search failed for %r: %s", name, e)

        _save_art_cache(cache)
        return True, f"Fetched art for {fetched} item(s)."
    except Exception as e:
        logger.warning("Art cache refresh failed (non-fatal): %s", e)
        return False, f"Art refresh failed: {e}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ok, msg = refresh_art_cache()
    print(("OK: " if ok else "FAILED: ") + msg)
