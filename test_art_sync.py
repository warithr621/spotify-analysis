#!/usr/bin/env python3
"""Dependency-free checks for art_sync's miss caching (no network: Spotify calls are faked).

Run: python test_art_sync.py
Verifies that a search with no verified match is recorded as `miss:<key>`, is not
retried until MISS_RETRY_AFTER has passed, and never shows up as an image key.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import art_sync


def play(artist, track, album):
    return {
        "spotify_track_uri": f"spotify:track:{track}",
        "ms_played": 200000,
        "master_metadata_album_artist_name": artist,
        "master_metadata_track_name": track,
        "master_metadata_album_album_name": album,
    }


EVENTS = [play("Found", "Song1", "Album1"), play("Missing", "Song2", "Album2")]


def days_ago(n):
    return date.fromordinal(date.today().toordinal() - n).isoformat()


def test_recent_miss():
    cache = {"miss:artist:a": days_ago(0), "miss:artist:b": days_ago(31), "miss:artist:c": "garbage"}
    assert art_sync._recent_miss(cache, "artist:a")
    assert not art_sync._recent_miss(cache, "artist:b"), "a 31-day-old miss should be retried"
    assert not art_sync._recent_miss(cache, "artist:c")
    assert not art_sync._recent_miss(cache, "artist:d")


def test_needing_art_skips_cached_and_recent_misses():
    cache = {
        "artist:found": "https://img/found",
        "miss:artist:missing": days_ago(1),
        "track:song1\x01found": "https://img/t1",
        "miss:track:song2\x01missing": days_ago(40),
    }
    tracks, albums, artists = art_sync._top_entities_needing_art(EVENTS, cache)
    assert artists == [], artists
    assert list(tracks) == ["song2\x01missing"], tracks
    assert len(albums) == 2, albums


def test_refresh_records_misses_and_stops_retrying():
    calls = []

    def fake_get(url, params=None, **_kwargs):
        calls.append(params["q"])
        kind = params["type"]
        items = []
        if kind == "artist" and params["q"] == "Found":
            items = [{"name": "Found", "images": [{"url": "https://img/big"}, {"url": "https://img/small"}]}]
        resp = mock.Mock()
        resp.json.return_value = {f"{kind}s": {"items": items}}
        return resp

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "art_cache.json"
        with mock.patch.object(art_sync, "ART_CACHE_PATH", path), \
                mock.patch.object(art_sync, "BASE", Path(d)), \
                mock.patch.object(art_sync.build_dashboard, "load_events", lambda: EVENTS), \
                mock.patch.object(art_sync.spotify_sync, "ensure_access_token", lambda: "tok"), \
                mock.patch.object(art_sync.requests, "get", fake_get):
            ok, msg = art_sync.refresh_art_cache()
            assert ok, msg
            cache = json.loads(path.read_text())
            assert cache["artist:found"] == "https://img/small"
            assert cache["miss:artist:missing"] == date.today().isoformat()
            assert "artist:missing" not in cache, "a miss must not look like an image"
            assert len(calls) == 6, calls  # 2 artists + 2 tracks + 2 albums

            calls.clear()
            ok, msg = art_sync.refresh_art_cache()
            assert ok and calls == [], (msg, calls)
            assert "already up to date" in msg, msg


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} art cache checks passed.")


if __name__ == "__main__":
    main()
