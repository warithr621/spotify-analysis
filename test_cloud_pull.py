#!/usr/bin/env python3
"""Dependency-free checks for cloud_pull.pull_exports() (no network: requests.get is faked).

Run: python test_cloud_pull.py
Verifies that only top-level yearly exports missing locally are downloaded, an
existing local export is never overwritten, the live buffer and other files are
ignored, a bad download leaves no file behind, and the repo's default branch is
used (falling back to "main" if it can't be looked up).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import cloud_pull


class FakeResponse:
    def __init__(self, body=b"", payload=None, status=200):
        self.body = body
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise cloud_pull.requests.HTTPError(f"{self.status}")

    def json(self):
        return self.payload

    def iter_content(self, _size):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def entry(path, sha, body):
    return {"path": path, "type": "blob", "sha": sha, "size": len(body)}


def run(tree, blobs, local_files, branch="main", repo_status=200, trees_seen=None):
    """Run pull_exports against a fake repo; returns (result, local dir contents, requested shas)."""
    requested = []
    cloud_pull._branch_cache.clear()

    def fake_get(url, **_kwargs):
        if url == cloud_pull.REPO_API.format(repo="me/data"):
            return FakeResponse(payload={"default_branch": branch}, status=repo_status)
        if "/trees/" in url:
            if trees_seen is not None:
                trees_seen.append(url.rsplit("/", 1)[1])
            return FakeResponse(payload={"tree": tree})
        sha = url.rsplit("/", 1)[1]
        requested.append(sha)
        return FakeResponse(body=blobs[sha])

    with tempfile.TemporaryDirectory() as d:
        hist = Path(d)
        for name, body in local_files.items():
            (hist / name).write_bytes(body)
        env = {"DATA_REPO": "me/data", "DATA_REPO_TOKEN": "t"}
        with mock.patch.dict(os.environ, env), mock.patch.object(cloud_pull, "HISTORY_DIR", hist), \
                mock.patch.object(cloud_pull.requests, "get", fake_get):
            result = cloud_pull.pull_exports()
        files = {p.name: p.read_bytes() for p in hist.iterdir()}
    return result, files, requested


def test_downloads_only_missing_exports():
    tree = [
        entry("Streaming_History_Audio_2019.json", "s2019", b"[repo 2019]"),
        entry("Streaming_History_Audio_2020.json", "s2020", b"[repo 2020]"),
    ]
    blobs = {"s2019": b"[repo 2019]", "s2020": b"[repo 2020]"}
    (ok, msg), files, requested = run(tree, blobs, {"Streaming_History_Audio_2019.json": b"[local 2019]"})
    assert ok, msg
    assert requested == ["s2020"], requested
    assert files["Streaming_History_Audio_2020.json"] == b"[repo 2020]"
    assert files["Streaming_History_Audio_2019.json"] == b"[local 2019]", "local export was overwritten"


def test_ignores_live_buffer_nested_and_unrelated_files():
    tree = [
        entry(cloud_pull.LIVE_FILENAME, "slive", b"[]"),
        entry("archive/Streaming_History_Audio_2021.json", "snested", b"[]"),
        entry("live_token.json", "stoken", b"{}"),
        {"path": "Streaming_History_Audio_2022.json", "type": "tree", "sha": "sdir"},
    ]
    (ok, msg), files, requested = run(tree, {}, {})
    assert ok and "already up to date" in msg, msg
    assert requested == [] and files == {}, (requested, files)


def test_size_mismatch_leaves_no_file():
    tree = [entry("Streaming_History_Audio_2020.json", "s2020", b"[the full file]")]
    (ok, msg), files, _ = run(tree, {"s2020": b"[trunc"}, {})
    assert not ok and "2020" in msg, msg
    assert files == {}, f"partial download left behind: {sorted(files)}"


def test_lists_the_default_branch():
    seen = []
    (ok, msg), _, _ = run([], {}, {}, branch="master", trees_seen=seen)
    assert ok and seen == ["master"], (msg, seen)


def test_branch_lookup_failure_falls_back_to_main():
    seen = []
    (ok, msg), _, _ = run([], {}, {}, branch="master", repo_status=403, trees_seen=seen)
    assert ok and seen == ["main"], (msg, seen)


def test_unconfigured_is_a_no_op():
    with mock.patch.dict(os.environ, {"DATA_REPO": "", "DATA_REPO_TOKEN": ""}):
        ok, msg = cloud_pull.pull_exports()
    assert not ok and "not set" in msg, msg


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} export pull checks passed.")


if __name__ == "__main__":
    main()
