#!/usr/bin/env python3
"""Dependency-free checks for the Last.fm helpers (no network, no API key).

Run: python test_lastfm.py
Covers tag cleanup, similar-artist parsing, and the fetch flow against a
faked Last.fm.
"""

from __future__ import annotations

import lastfm_sync


def check(name, cond):
    print(("  ok  " if cond else "FAIL  ") + name)
    if not cond:
        raise SystemExit(1)


def test_clean_tags():
    raw = [
        {"name": "Seen Live", "count": 100},
        {"name": "K-Pop", "count": 90},
        {"name": "IVE", "count": 80},          # the artist's own name
        {"name": "2021", "count": 70},         # bare year
        {"name": "girl group", "count": 60},
        {"name": "k-pop", "count": 50},        # duplicate after lowercasing
        {"name": "korean", "count": 10},       # below MIN_TAG_COUNT
    ]
    check("clean_tags drops noise, dedupes, keeps order",
          lastfm_sync.clean_tags(raw, "IVE") == ["k-pop", "girl group"])
    many = [{"name": f"t{i}", "count": 90 - i} for i in range(10)]
    check("clean_tags caps at MAX_TAGS", len(lastfm_sync.clean_tags(many, "x")) == lastfm_sync.MAX_TAGS)
    check("clean_tags handles None", lastfm_sync.clean_tags(None, "x") == [])


def test_parse_similar():
    raw = [{"name": "B", "match": "0.4"}, {"name": "A", "match": "0.9"}, {"name": "", "match": "1"}, {"name": "C", "match": "0"}]
    check("parse_similar sorts, drops empty/zero", lastfm_sync.parse_similar(raw) == [["A", 0.9], ["B", 0.4]])


def test_fetch_artist():
    calls = []

    def fake_call(api_key, method, artist, **extra):
        calls.append(method)
        if method == "artist.getSimilar":
            return {"similarartists": {"@attr": {"artist": "IVE"}, "artist": [{"name": "LE SSERAFIM", "match": "0.8"}]}}
        return {"toptags": {"tag": [{"name": "k-pop", "count": 100}]}}

    real_call, real_gap = lastfm_sync._call, lastfm_sync.REQUEST_GAP_S
    lastfm_sync._call, lastfm_sync.REQUEST_GAP_S = fake_call, 0
    try:
        entry = lastfm_sync.fetch_artist("key", "ive")
        check("fetch_artist builds entry", entry["name"] == "IVE" and entry["tags"] == ["k-pop"]
              and entry["similar"] == [["LE SSERAFIM", 0.8]])
        lastfm_sync._call = lambda *a, **k: {"error": 6, "message": "not found"}
        entry = lastfm_sync.fetch_artist("key", "nobody")
        check("unknown artist gets an empty entry", entry["tags"] == [] and entry["similar"] == [])
    finally:
        lastfm_sync._call, lastfm_sync.REQUEST_GAP_S = real_call, real_gap


if __name__ == "__main__":
    test_clean_tags()
    test_parse_similar()
    test_fetch_artist()
    print("All Last.fm checks passed.")
