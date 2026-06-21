#!/usr/bin/env python3
"""Dependency-free checks for build_dashboard.dedup_rows().

Run: python test_merge_dedup.py
Verifies the live+export overlap merge: zero duplicate (ts,uri), export wins on
conflict, larger ms_played wins among same-kind rows, and no keys are dropped.
"""

from __future__ import annotations

import build_dashboard


def live_row(ts, uri, ms, **extra):
    r = {"ts": ts, "spotify_track_uri": uri, "ms_played": ms,
         "platform": "api", "ms_played_resolved": True}
    r.update(extra)
    return r


def export_row(ts, uri, ms, **extra):
    # Export rows lack the ms_played_resolved key.
    r = {"ts": ts, "spotify_track_uri": uri, "ms_played": ms, "reason_end": "trackdone"}
    r.update(extra)
    return r


def key(r):
    return (build_dashboard.spotify_sync.normalize_ts_key(str(r["ts"])), r["spotify_track_uri"])


def test_no_duplicate_keys():
    rows = [
        live_row("2024-01-01T00:00:00Z", "spotify:track:a", 100),
        live_row("2024-01-01T00:00:00Z", "spotify:track:a", 100),  # exact dup
        live_row("2024-01-01T00:01:00Z", "spotify:track:b", 200),
    ]
    out = build_dashboard.dedup_rows(rows)
    keys = [key(r) for r in out]
    assert len(keys) == len(set(keys)), "duplicate keys remain"
    assert len(out) == 2, f"expected 2 rows, got {len(out)}"


def test_export_wins_over_live():
    # Same (ts,uri) appears in both the live buffer and a fresh export.
    rows = [
        live_row("2024-02-02T12:00:00Z", "spotify:track:x", 90000),     # estimate
        export_row("2024-02-02T12:00:00Z", "spotify:track:x", 210000),  # true ms
    ]
    out = build_dashboard.dedup_rows(rows)
    assert len(out) == 1
    winner = out[0]
    assert "ms_played_resolved" not in winner, "export row (no resolved key) should win"
    assert winner["ms_played"] == 210000

    # Order must not matter: export first, live second.
    out2 = build_dashboard.dedup_rows(list(reversed(rows)))
    assert len(out2) == 1
    assert "ms_played_resolved" not in out2[0], "export should win regardless of order"


def test_larger_ms_wins_same_kind():
    rows = [
        live_row("2024-03-03T08:00:00Z", "spotify:track:y", 50000),
        live_row("2024-03-03T08:00:00Z", "spotify:track:y", 120000),
    ]
    out = build_dashboard.dedup_rows(rows)
    assert len(out) == 1
    assert out[0]["ms_played"] == 120000


def test_no_keys_dropped_on_overlap():
    # Export covers up to X; live buffer overlaps [start..X] and extends past X.
    export = [
        export_row("2024-04-01T00:00:00Z", "spotify:track:1", 180000),
        export_row("2024-04-01T00:05:00Z", "spotify:track:2", 180000),
    ]
    live = [
        live_row("2024-04-01T00:00:00Z", "spotify:track:1", 100000),  # overlap
        live_row("2024-04-01T00:05:00Z", "spotify:track:2", 100000),  # overlap
        live_row("2024-04-01T00:10:00Z", "spotify:track:3", 100000),  # past X
    ]
    out = build_dashboard.dedup_rows(export + live)
    out_keys = {key(r) for r in out}
    expected = {key(r) for r in export + live}
    assert out_keys == expected, "some unique keys were dropped"
    assert len(out) == 3, f"expected 3 unique rows, got {len(out)}"
    # Overlapping keys resolved to the export copy.
    for r in out:
        if r["spotify_track_uri"] in ("spotify:track:1", "spotify:track:2"):
            assert "ms_played_resolved" not in r, "overlap should keep export copy"


def test_rows_without_key_kept():
    rows = [
        {"ts": "2024-05-05T00:00:00Z", "spotify_episode_uri": "spotify:episode:p"},  # podcast, no track uri
        {"ts": "2024-05-05T00:00:00Z", "spotify_episode_uri": "spotify:episode:p"},
        live_row("2024-05-05T00:01:00Z", "spotify:track:z", 100),
    ]
    out = build_dashboard.dedup_rows(rows)
    # The two keyless rows are kept as-is (not collapsed); the track row stays.
    assert len(out) == 3, f"keyless rows should be preserved, got {len(out)}"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} dedup checks passed.")


if __name__ == "__main__":
    main()
