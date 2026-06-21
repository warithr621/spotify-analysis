#!/usr/bin/env python3
"""Headless cloud orchestrator for the GitHub Actions hourly scrape.

Reuses spotify_sync verbatim (one dedup/ms-resolution implementation). The refresh
token lives in the private data repo as live_token.json, NOT in an Actions secret:
this reads it from the data-repo checkout and, when Spotify rotates it, writes the
new one back so the workflow can commit it atomically with the live JSON.

Env:
  SPOTIFY_CLIENT_ID    Spotify app client id (PKCE; no secret)
  SPOTIFY_HISTORY_DIR  path to the data-repo checkout (e.g. ./_data); also tells
                       spotify_sync where to read/write the live buffer
Exit codes: 0 ok; 1 misconfig / refresh failure (re-authorize locally).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import requests

import spotify_sync

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("cloud_sync")

TOKEN_FILENAME = "live_token.json"


def _write_refresh_token(token_path: Path, refresh_token: str) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(token_path.parent),
        prefix=".live_token.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump({"refresh_token": refresh_token}, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, token_path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def main() -> int:
    client_id = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    if not client_id:
        logger.error("SPOTIFY_CLIENT_ID not set.")
        return 1

    data_dir = (os.environ.get("SPOTIFY_HISTORY_DIR") or "").strip()
    if not data_dir:
        logger.error("SPOTIFY_HISTORY_DIR not set (should point at the data-repo checkout).")
        return 1
    token_path = Path(data_dir) / TOKEN_FILENAME

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
        refresh_token = str(token_data.get("refresh_token") or "").strip()
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Could not read %s: %s", token_path, e)
        return 1
    if not refresh_token:
        logger.error("No refresh_token in %s; re-authorize locally and seed it.", token_path)
        return 1

    try:
        refreshed = spotify_sync._refresh_access_token(client_id, refresh_token)
    except requests.HTTPError as e:
        err = {}
        if e.response is not None:
            try:
                err = e.response.json()
            except ValueError:
                pass
        if err.get("error") == "invalid_grant":
            logger.error(
                "Refresh token is invalid (invalid_grant) — it expired or was revoked. "
                "Re-authorize locally and commit a new %s to the data repo.",
                TOKEN_FILENAME,
            )
        else:
            logger.error("Token refresh failed: %s", e)
        return 1
    except requests.RequestException as e:
        logger.error("Token refresh failed (network): %s", e)
        return 1

    access_token = refreshed.get("access_token")
    if not access_token:
        logger.error("Token refresh response had no access_token.")
        return 1

    # Spotify rotates the refresh token on every refresh; persist it immediately so
    # the workflow commits the new one. Done before sync so a later sync failure
    # never strands an unsaved rotated token.
    new_refresh = refreshed.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        _write_refresh_token(token_path, new_refresh)
        logger.info("Refresh token rotated; wrote new %s.", TOKEN_FILENAME)

    latest = spotify_sync.compute_latest_event_utc()
    added, _ = spotify_sync.sync_incremental(latest, access_token=access_token)
    logger.info("Synced %d new play(s) into %s.", added, data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
