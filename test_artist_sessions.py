#!/usr/bin/env python3
"""Dependency-free checks for build_dashboard.build_artist_sessions().

Run: python test_artist_sessions.py
Verifies the Artist web's session split: gaps over GRAPH_SESSION_GAP start a new
session, only sessions with 2+ tracked artists are kept, artist indices are
unique and sorted, and the day index uses the display timezone (Chicago).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import build_dashboard

EPOCH = date(2024, 1, 1)
IDX = {"A": 0, "B": 1, "C": 2}


def utc(day, hour, minute=0):
    return datetime(2024, 1, day, hour, minute, tzinfo=timezone.utc)


def sessions(log):
    return build_dashboard.build_artist_sessions(log, IDX, EPOCH)


def test_gap_splits_sessions():
    # 18:00 UTC on Jan 10 is midday in Chicago, so both sessions land on day 9.
    log = [(utc(10, 18), "A"), (utc(10, 18, 20), "B"), (utc(10, 19, 0), "C"), (utc(10, 19, 10), "A")]
    assert sessions(log) == [[9, [0, 1]], [9, [0, 2]]], sessions(log)


def test_gap_of_exactly_the_limit_does_not_split():
    gap = build_dashboard.GRAPH_SESSION_GAP
    start = utc(10, 18)
    log = [(start, "A"), (start + gap, "B"), (start + gap + timedelta(minutes=1), "C")]
    assert sessions(log) == [[9, [0, 1, 2]]], sessions(log)


def test_single_artist_and_untracked_sessions_dropped():
    log = [
        (utc(10, 1), "A"), (utc(10, 1, 5), "A"),          # one tracked artist, played twice
        (utc(10, 5), "B"), (utc(10, 5, 5), "Untracked"),  # second artist isn't tracked
    ]
    assert sessions(log) == [], sessions(log)


def test_unsorted_input_and_repeats():
    log = [(utc(10, 18, 10), "B"), (utc(10, 18), "A"), (utc(10, 18, 5), "B"), (utc(10, 18, 15), "A")]
    assert sessions(log) == [[9, [0, 1]]], sessions(log)


def test_day_uses_display_timezone():
    # 03:00 UTC on Jan 11 is 21:00 on Jan 10 in Chicago: day 9, not day 10.
    log = [(utc(11, 3), "A"), (utc(11, 3, 10), "B")]
    assert sessions(log) == [[9, [0, 1]]], sessions(log)


def test_no_epoch_means_no_sessions():
    assert build_dashboard.build_artist_sessions([(utc(10, 1), "A"), (utc(10, 1, 1), "B")], IDX, None) == []


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} artist session checks passed.")


if __name__ == "__main__":
    main()
