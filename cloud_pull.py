#!/usr/bin/env python3
"""Pull the cloud live buffer from the private data repo into music-history/.

Best-effort by design: if the cloud isn't configured (env vars unset) or the
fetch fails, this logs a warning and returns False without raising, so the local
dashboard keeps working off whatever live buffer it already has.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
HISTORY_DIR = BASE / "music-history"
LIVE_FILENAME = "Streaming_History_Audio_live.json"
CONTENTS_API = "https://api.github.com/repos/{repo}/contents/{path}"


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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    pull_live()
