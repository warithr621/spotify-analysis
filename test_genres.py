#!/usr/bin/env python3
"""Dependency-free checks for genres.assign_genres(). Run: python test_genres.py"""

from __future__ import annotations

import genres


def check(name, cond):
    print(("  ok  " if cond else "FAIL  ") + name)
    if not cond:
        raise SystemExit(1)


def test_synonyms_and_specificity():
    # 15 lofi-ish artists using different spellings, all also tagged with generic "pop"/"electronic".
    spellings = [["pop", "lofi"], ["electronic", "Lo-Fi"], ["pop", "lofi hip hop"], ["chillhop", "pop"], ["beats", "electronic"]]
    tags = [list(spellings[i % len(spellings)]) for i in range(15)]
    # 15 plain pop artists
    tags += [["pop", "dance pop"] for _ in range(15)]
    names, idx, inferred = genres.assign_genres(tags, [10.0] * len(tags))
    check("lofi spellings merge into one family", len({idx[i] for i in range(15)}) == 1 and names[idx[0]] == "lo-fi")
    check("specific genre beats generic 'pop'", names[idx[0]] != "pop")
    check("plain pop artists still get a genre", all(idx[i] is not None for i in range(15, 30)))


def test_small_genres_fall_back():
    tags = [["country", "pop"] for _ in range(20)] + [["polka", "pop"] for _ in range(3)] + [["pop"] for _ in range(20)]
    names, idx, _ = genres.assign_genres(tags, [1.0] * len(tags))
    check("rare tag is not a genre", "polka" not in names)
    check("artist with a rare tag falls back to its next tag", names[idx[20]] == "pop")
    check("country family present", "country" in names)


def test_inference_from_neighbours():
    tags = [["country"] for _ in range(14)] + [[]]  # last artist has no tags
    links = [[14, 0, 0.9], [14, 1, 0.8], [14, 2, 0.7]]
    names, idx, inferred = genres.assign_genres(tags, [5.0] * 15, links)
    check("untagged artist borrows neighbours' genre", idx[14] is not None and names[idx[14]] == "country" and inferred[14])
    check("tagged artists are not marked inferred", not any(inferred[:14]))


def test_order_by_minutes():
    tags = [["rock"] for _ in range(14)] + [["jazz"] for _ in range(14)]
    minutes = [1.0] * 14 + [100.0] * 14
    names, idx, _ = genres.assign_genres(tags, minutes)
    check("genres ordered by total minutes", names[0] == "jazz")


if __name__ == "__main__":
    test_synonyms_and_specificity()
    test_small_genres_fall_back()
    test_inference_from_neighbours()
    test_order_by_minutes()
    print("All genre checks passed.")
