#!/usr/bin/env python3
"""Pull the cloud live buffer (and any yearly export files) from the private data repo into music-history/.

Best-effort by design: if the cloud isn't configured (env vars unset) or the
fetch fails, this logs a warning and returns False without raising, so the local
dashboard keeps working off whatever live buffer it already has.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
HISTORY_DIR = BASE / "music-history"
LIVE_FILENAME = "Streaming_History_Audio_live.json"
TOKEN_FILENAME = "live_token.json"
CONTENTS_API = "https://api.github.com/repos/{repo}/contents/{path}"
GIT_API = "https://api.github.com/repos/{repo}/git"


def push_live() -> tuple[bool, str]:
    """Push the local live buffer to the data repo via Git Data API (handles >1 MB).

    Uses the low-level blob/tree/commit/ref flow because the file exceeds the
    1 MB limit of the Contents API. Requires DATA_REPO_TOKEN to have Contents
    write permission on the data repo. Best-effort: returns (False, msg) on any
    failure without raising.
    """
    repo = (os.environ.get("DATA_REPO") or "").strip()
    token = (os.environ.get("DATA_REPO_TOKEN") or "").strip()
    if not repo or not token:
        return False, "DATA_REPO / DATA_REPO_TOKEN not set."

    live_path = HISTORY_DIR / LIVE_FILENAME
    try:
        content = live_path.read_bytes()
    except OSError as e:
        return False, f"Could not read local live buffer: {e}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = GIT_API.format(repo=repo)

    try:
        r = requests.get(f"{base}/ref/heads/main", headers=headers, timeout=60)
        r.raise_for_status()
        head_sha = r.json()["object"]["sha"]

        r = requests.get(f"{base}/commits/{head_sha}", headers=headers, timeout=60)
        r.raise_for_status()
        tree_sha = r.json()["tree"]["sha"]

        r = requests.post(f"{base}/blobs", headers=headers, json={
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        }, timeout=120)
        r.raise_for_status()
        blob_sha = r.json()["sha"]

        r = requests.post(f"{base}/trees", headers=headers, json={
            "base_tree": tree_sha,
            "tree": [{"path": LIVE_FILENAME, "mode": "100644", "type": "blob", "sha": blob_sha}],
        }, timeout=60)
        r.raise_for_status()
        new_tree_sha = r.json()["sha"]

        r = requests.post(f"{base}/commits", headers=headers, json={
            "message": f"sync: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} (local push)",
            "tree": new_tree_sha,
            "parents": [head_sha],
        }, timeout=60)
        r.raise_for_status()
        new_commit_sha = r.json()["sha"]

        r = requests.patch(f"{base}/refs/heads/main", headers=headers, json={
            "sha": new_commit_sha,
        }, timeout=60)
        r.raise_for_status()

    except requests.RequestException as e:
        logger.warning("Push live buffer to data repo failed: %s", e)
        return False, f"Push failed: {e}"

    logger.info("Pushed live buffer (%d bytes) to %s/%s", len(content), repo, LIVE_FILENAME)
    return True, "Pushed live buffer to data repo."


def pull_live() -> bool:
    """Fetch the data repo's live JSON into music-history/. Returns True on success."""
    repo = (os.environ.get("DATA_REPO") or "").strip()
    token = (os.environ.get("DATA_REPO_TOKEN") or "").strip()
    if not repo or not token:
        logger.warning("DATA_REPO / DATA_REPO_TOKEN not set; skipping cloud pull.")
        return False

    url = CONTENTS_API.format(repo=repo, path=LIVE_FILENAME)
    try:
        r = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.raw",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=60,
        )
        r.raise_for_status()
        content = r.content
    except requests.RequestException as e:
        logger.warning("Cloud pull failed (%s); using existing local live buffer.", e)
        return False

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Cloud live buffer is invalid JSON (%s); skipping write.", e)
        return False
    if not isinstance(data, list):
        logger.warning("Cloud live buffer is not a JSON list; skipping write.")
        return False

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    live_path = HISTORY_DIR / LIVE_FILENAME
    tmp = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=str(HISTORY_DIR),
        prefix=".live_audio.",
        suffix=".tmp",
        delete=False,
    )
    try:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, live_path)
    except OSError as e:
        logger.warning("Could not write live buffer (%s); skipping.", e)
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return False

    logger.info("Pulled cloud live buffer (%d rows) into %s", len(data), live_path)
    return True


def _git_blob_sha(path: Path) -> str:
    """The SHA GitHub reports for this file's content (git's `blob <size>\0<bytes>` hash)."""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % path.stat().st_size)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pull_exports() -> tuple[bool, str]:
    """Download the data repo's yearly `Streaming_History_Audio_*.json` export files that are
    missing locally or whose content differs (compared by git blob SHA, so unchanged files are
    skipped without downloading). The live buffer is handled by `pull_live`. Best-effort:
    returns (False, msg) on any failure without raising, leaving existing local files untouched."""
    repo = (os.environ.get("DATA_REPO") or "").strip()
    token = (os.environ.get("DATA_REPO_TOKEN") or "").strip()
    if not repo or not token:
        return False, "DATA_REPO / DATA_REPO_TOKEN not set."
    headers = {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
    base = GIT_API.format(repo=repo)
    try:
        r = requests.get(f"{base}/trees/main", params={"recursive": "1"}, headers={**headers, "Accept": "application/vnd.github+json"}, timeout=60)
        r.raise_for_status()
        remote = [
            t for t in r.json().get("tree", [])
            if t.get("type") == "blob" and "/" not in t["path"]
            and t["path"].startswith("Streaming_History_Audio_") and t["path"].endswith(".json")
            and t["path"] != LIVE_FILENAME
        ]
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for t in remote:
            dest = HISTORY_DIR / t["path"]
            if dest.is_file() and _git_blob_sha(dest) == t["sha"]:
                continue
            tmp = tempfile.NamedTemporaryFile(mode="wb", dir=str(HISTORY_DIR), prefix=".export.", suffix=".tmp", delete=False)
            try:
                with requests.get(f"{base}/blobs/{t['sha']}", headers={**headers, "Accept": "application/vnd.github.raw"}, stream=True, timeout=300) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(1 << 20):
                        tmp.write(chunk)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                if tmp_size_mismatch(tmp.name, t.get("size")):
                    raise OSError("downloaded size does not match the repo")
                os.replace(tmp.name, dest)
                downloaded.append(t["path"])
            except (requests.RequestException, OSError) as e:
                logger.warning("Could not download %s: %s", t["path"], e)
                try:
                    tmp.close()
                    os.unlink(tmp.name)
                except OSError:
                    pass
                return False, f"Export download failed for {t['path']}: {e}"
    except requests.RequestException as e:
        logger.warning("Listing data repo exports failed: %s", e)
        return False, f"Could not list exports in the data repo: {e}"
    if downloaded:
        logger.info("Pulled %d export file(s) from %s: %s", len(downloaded), repo, ", ".join(downloaded))
        return True, f"Downloaded {len(downloaded)} export file(s): {', '.join(downloaded)}."
    return True, "Export files already up to date."


def tmp_size_mismatch(path: str, expected: int | None) -> bool:
    return expected is not None and os.path.getsize(path) != expected


def push_live_token(refresh_token: str) -> tuple[bool, str]:
    """Write live_token.json to the data repo via the GitHub contents API.

    Used by the local re-authorize flow so a fresh refresh token lands in the data
    repo without manual git steps. Requires DATA_REPO + a DATA_REPO_TOKEN with
    Contents: Read and write. Returns (ok, message).
    """
    repo = (os.environ.get("DATA_REPO") or "").strip()
    token = (os.environ.get("DATA_REPO_TOKEN") or "").strip()
    if not repo or not token:
        return False, "DATA_REPO / DATA_REPO_TOKEN not set."

    url = CONTENTS_API.format(repo=repo, path=TOKEN_FILENAME)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # The contents API needs the current blob sha to update an existing file.
    sha = None
    try:
        g = requests.get(url, headers=headers, timeout=60)
        if g.status_code == 200:
            sha = g.json().get("sha")
        elif g.status_code != 404:
            g.raise_for_status()
    except requests.RequestException as e:
        return False, f"Could not read existing token file: {e}"

    content = json.dumps({"refresh_token": refresh_token}, indent=2).encode("utf-8")
    payload = {
        "message": f"re-auth: update refresh token {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "content": base64.b64encode(content).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha

    try:
        p = requests.put(url, headers=headers, json=payload, timeout=60)
        p.raise_for_status()
    except requests.RequestException as e:
        detail = ""
        if isinstance(e, requests.HTTPError) and e.response is not None:
            if e.response.status_code in (403, 404):
                detail = " (does DATA_REPO_TOKEN have Contents: Read and write?)"
        return False, f"Push failed: {e}{detail}"

    logger.info("Pushed new refresh token to %s/%s", repo, TOKEN_FILENAME)
    return True, "Pushed the new token to the data repo."


if __name__ == "__main__":
    import spotify_sync

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    spotify_sync.prime_local_env()
    print(pull_exports()[1])
    print("live buffer pulled:", pull_live())
