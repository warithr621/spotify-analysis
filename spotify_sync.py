#!/usr/bin/env python3
"""Spotify Web API: PKCE auth, recently-played incremental sync, append to live JSON."""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import logging
import os
import queue
import secrets
import stat
import tempfile
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
HISTORY_DIR = BASE / "music-history"
AUDIO_GLOB = "Streaming_History_Audio_*.json"
LIVE_FILENAME = "Streaming_History_Audio_live.json"
TOKENS_PATH = BASE / "spotify_tokens.json"
CONFIG_PATH = BASE / "spotify_config.json"
EXAMPLE_CONFIG_PATH = BASE / "spotify_config.example.json"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
RECENT_URL = "https://api.spotify.com/v1/me/player/recently-played"

SCOPE = "user-read-recently-played"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/callback"

OAUTH_WAIT_SECONDS = 600

# Queue populated by Flask /callback with authorization code or None on error
_oauth_code_queue: queue.Queue[str | None] | None = None


def set_oauth_code_queue(q: queue.Queue[str | None]) -> None:
    global _oauth_code_queue
    _oauth_code_queue = q


def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        s2 = s.strip()
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def normalize_ts_key(ts_raw: str) -> str:
    """Canonical UTC `ts` string for dedupe (matches export style, no sub-second)."""
    dt = parse_ts(ts_raw.strip())
    if not dt:
        return ts_raw.strip()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json_file(path: Path) -> list[dict[str, Any]] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, TypeError) as e:
        logger.warning("Skipping unreadable JSON %s: %s", path, e)
        return None
    if not isinstance(data, list):
        logger.warning("Skipping %s: expected list at top level", path)
        return None
    return data


def compute_latest_event_utc() -> datetime | None:
    """Newest `ts` among all Streaming_History_Audio_*.json rows."""
    latest: datetime | None = None
    for fp in sorted(glob.glob(str(HISTORY_DIR / AUDIO_GLOB))):
        data = _load_json_file(Path(fp))
        if not data:
            continue
        for r in data:
            dt = parse_ts(str(r.get("ts") or ""))
            if dt and (latest is None or dt > latest):
                latest = dt
    return latest


def collect_existing_row_keys() -> set[tuple[str, str]]:
    """Keys (ts, spotify_track_uri) for deduplication."""
    keys: set[tuple[str, str]] = set()
    for fp in sorted(glob.glob(str(HISTORY_DIR / AUDIO_GLOB))):
        data = _load_json_file(Path(fp))
        if not data:
            continue
        for r in data:
            ts_raw = str(r.get("ts") or "").strip()
            uri = str(r.get("spotify_track_uri") or "").strip()
            ts_k = normalize_ts_key(ts_raw)
            if ts_k and uri:
                keys.add((ts_k, uri))
    return keys


def prime_local_env() -> None:
    """Load `.env` into the process if present (does not override existing env vars)."""
    env_path = BASE / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError as e:
        logger.warning("Could not read .env: %s", e)


def load_spotify_config() -> dict[str, str]:
    prime_local_env()
    client_id = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    redirect_uri = DEFAULT_REDIRECT_URI
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                if not client_id and raw.get("client_id"):
                    cid = str(raw["client_id"]).strip()
                    if cid and not cid.upper().startswith("PASTE_"):
                        client_id = cid
                if raw.get("redirect_uri"):
                    redirect_uri = str(raw["redirect_uri"]).strip()
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read spotify_config.json: %s", e)
    if not client_id:
        hint = (
            f"Spotify client_id missing. Do one of the following in {BASE}:\n"
            "  • Create a file spotify_config.json with {\"client_id\":\"<your_app_client_id>\"} "
            f"(copy from {EXAMPLE_CONFIG_PATH.name})\n"
            "  • Or add SPOTIFY_CLIENT_ID=... to a .env file in this folder\n"
            "  • Or export SPOTIFY_CLIENT_ID in your shell before running serve.py\n"
            "Then restart the server and try Request data again."
        )
        raise RuntimeError(hint)
    return {"client_id": client_id, "redirect_uri": redirect_uri}


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(32)[:128]


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _token_expired(expires_at: float, skew_seconds: int = 120) -> bool:
    return datetime.now(timezone.utc).timestamp() >= expires_at - skew_seconds


def load_tokens() -> dict[str, Any] | None:
    if not TOKENS_PATH.is_file():
        return None
    try:
        return json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_tokens(payload: dict[str, Any]) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(BASE),
        prefix=".spotify_tokens.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(payload, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, TOKENS_PATH)
        try:
            os.chmod(TOKENS_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def _exchange_code_for_tokens(
    client_id: str, redirect_uri: str, code: str, code_verifier: str
) -> dict[str, Any]:
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _refresh_access_token(client_id: str, refresh_token: str) -> dict[str, Any]:
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def ensure_access_token() -> str:
    """Return a valid access token; run PKCE browser flow if needed."""
    cfg = load_spotify_config()
    client_id = cfg["client_id"]
    redirect_uri = cfg["redirect_uri"]

    data = load_tokens()
    now = datetime.now(timezone.utc).timestamp()

    if data and data.get("access_token") and data.get("expires_at"):
        if not _token_expired(float(data["expires_at"])):
            return str(data["access_token"])
        if data.get("refresh_token"):
            try:
                refreshed = _refresh_access_token(client_id, str(data["refresh_token"]))
                new_access = refreshed["access_token"]
                expires_in = int(refreshed.get("expires_in", 3600))
                payload = {
                    "access_token": new_access,
                    "refresh_token": refreshed.get("refresh_token") or data["refresh_token"],
                    "expires_at": now + expires_in,
                }
                save_tokens(payload)
                return new_access
            except requests.HTTPError as e:
                err: dict[str, Any] = {}
                if e.response is not None:
                    try:
                        err = e.response.json()
                    except Exception:
                        pass
                if err.get("error") == "invalid_grant":
                    logger.info("Refresh token expired (invalid_grant); discarding and re-authorizing")
                    TOKENS_PATH.unlink(missing_ok=True)
                else:
                    logger.warning("Token refresh HTTP error, re-authorizing: %s", e)
            except requests.RequestException as e:
                logger.warning("Token refresh failed (network), re-authorizing: %s", e)

    # PKCE authorization code flow
    q = _oauth_code_queue
    if q is None:
        raise RuntimeError("OAuth queue not configured; server must call set_oauth_code_queue first")

    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            break

    code_verifier = _pkce_verifier()
    challenge = _pkce_challenge(code_verifier)
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": SCOPE,
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    }
    url = f"{AUTH_URL}?{urlencode(params)}"
    logger.info("Opening browser for Spotify authorization")
    webbrowser.open(url)

    try:
        code = q.get(timeout=OAUTH_WAIT_SECONDS)
    except queue.Empty as exc:
        raise RuntimeError("Timed out waiting for Spotify authorization callback") from exc

    if code is None:
        raise RuntimeError("Spotify authorization was cancelled or failed")

    token_payload = _exchange_code_for_tokens(client_id, redirect_uri, code, code_verifier)
    access = token_payload["access_token"]
    refresh = token_payload.get("refresh_token")
    expires_in = int(token_payload.get("expires_in", 3600))
    save_tokens(
        {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": datetime.now(timezone.utc).timestamp() + expires_in,
        }
    )
    return access


def fetch_recently_played_after(access_token: str, after_ms: int) -> list[dict[str, Any]]:
    """Page through recently-played with `after` cursor until no more items."""
    headers = {"Authorization": f"Bearer {access_token}"}
    items: list[dict[str, Any]] = []
    next_url: str | None = RECENT_URL
    params: dict[str, Any] | None = {"limit": 50, "after": after_ms}

    while next_url:
        r = requests.get(
            next_url,
            headers=headers,
            params=params,
            timeout=60,
        )
        if r.status_code == 401:
            raise RuntimeError("Spotify API returned 401; token may be invalid")
        r.raise_for_status()
        body = r.json()
        batch = body.get("items") or []
        items.extend(batch)
        next_url = body.get("next")
        params = None  # `next` URL already contains query string

    return items


def api_item_to_row(item: dict[str, Any]) -> dict[str, Any] | None:
    """Map Spotify recently-played item to Extended Streaming History-shaped row."""
    track = item.get("track")
    if not isinstance(track, dict):
        return None
    uri = track.get("uri")
    if not uri or not str(uri).startswith("spotify:track:"):
        return None

    played_at = item.get("played_at")
    if not played_at:
        return None
    ts_str = normalize_ts_key(str(played_at).strip())
    if not ts_str:
        return None

    artists = track.get("artists") or []
    artist_name = "Unknown Artist"
    if artists and isinstance(artists[0], dict) and artists[0].get("name"):
        artist_name = str(artists[0]["name"])

    album = track.get("album") or {}
    album_name = str(album.get("name") or "Unknown Album")

    duration_ms = int(track.get("duration_ms") or 0)
    if duration_ms <= 0:
        duration_ms = 1

    track_name = str(track.get("name") or "Unknown Track")

    return {
        "ts": ts_str,
        "platform": "api",
        "ms_played": duration_ms,
        "conn_country": None,
        "ip_addr": None,
        "master_metadata_track_name": track_name,
        "master_metadata_album_artist_name": artist_name,
        "master_metadata_album_album_name": album_name,
        "spotify_track_uri": uri,
        "episode_name": None,
        "episode_show_name": None,
        "spotify_episode_uri": None,
        "audiobook_title": None,
        "audiobook_uri": None,
        "audiobook_chapter_uri": None,
        "audiobook_chapter_title": None,
        "reason_start": None,
        "reason_end": None,
        "shuffle": False,
        "skipped": False,
        "offline": False,
        "offline_timestamp": None,
        "incognito_mode": False,
        "ms_played_resolved": False,
    }


def append_new_rows(rows: list[dict[str, Any]]) -> int:
    """
    Append rows not already present (dedupe by ts + spotify_track_uri).
    Writes Streaming_History_Audio_live.json atomically.
    Returns count of newly appended rows.
    """
    if not rows:
        return 0

    existing = collect_existing_row_keys()
    live_path = HISTORY_DIR / LIVE_FILENAME
    current: list[dict[str, Any]] = []
    if live_path.is_file():
        loaded = _load_json_file(live_path)
        if loaded is not None:
            current = loaded

    added = 0
    for row in rows:
        ts = normalize_ts_key(str(row.get("ts") or ""))
        uri = str(row.get("spotify_track_uri") or "").strip()
        key = (ts, uri)
        if not ts or not uri or key in existing:
            continue
        existing.add(key)
        current.append(row)
        added += 1

    if added == 0:
        return 0

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(HISTORY_DIR),
        prefix=".live_audio.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(current, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, live_path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise

    return added


def resolve_live_ms_played() -> None:
    """
    Recompute ms_played for unresolved rows in live.json using played_at deltas.

    For each unresolved row (ms_played_resolved missing or False), sets:
        ms_played = max(0, min(played_at - predecessor_played_at, duration_ms))
    The oldest row with no predecessor keeps ms_played = duration_ms.

    Resolved rows (ms_played_resolved == True) are used as predecessors but not
    modified. Writes the full sorted list back atomically only if changes were made.
    """
    live_path = HISTORY_DIR / LIVE_FILENAME
    if not live_path.is_file():
        return

    rows = _load_json_file(live_path)
    if not rows:
        return

    if all(r.get("ms_played_resolved") for r in rows):
        return

    rows.sort(key=lambda r: parse_ts(str(r.get("ts") or "")) or datetime.min.replace(tzinfo=timezone.utc))

    changed = False
    predecessor_ts: datetime | None = None

    for row in rows:
        ts = parse_ts(str(row.get("ts") or ""))
        if row.get("ms_played_resolved"):
            predecessor_ts = ts
            continue

        duration_ms = int(row.get("ms_played") or 0)
        if predecessor_ts is not None and ts is not None:
            diff_ms = int((ts - predecessor_ts).total_seconds() * 1000)
            row["ms_played"] = max(0, min(diff_ms, duration_ms))
        row["ms_played_resolved"] = True
        predecessor_ts = ts
        changed = True

    if not changed:
        return

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(HISTORY_DIR),
        prefix=".live_audio.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(rows, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, live_path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def sync_incremental(latest_saved: datetime | None) -> tuple[int, list[dict[str, Any]]]:
    """
    Fetch plays after latest_saved (exclusive per Spotify `after` ms semantics),
    map to rows, dedupe and append. If latest_saved is None, uses epoch.
    Returns (added_count, mapped_rows_before_dedup).
    """
    token = ensure_access_token()
    after_dt = latest_saved or datetime(1970, 1, 1, tzinfo=timezone.utc)
    after_ms = int(after_dt.timestamp() * 1000)
    items = fetch_recently_played_after(token, after_ms)
    mapped: list[dict[str, Any]] = []
    for it in items:
        row = api_item_to_row(it)
        if row:
            mapped.append(row)
    added = append_new_rows(mapped)
    resolve_live_ms_played()
    return added, mapped


def format_gate_message(latest: datetime, gate: timedelta = timedelta(minutes=10)) -> tuple[str, int]:
    """Human message and retry_after_seconds for 429 responses."""
    now = datetime.now(timezone.utc)
    unlock_at = latest + gate
    remaining = unlock_at - now
    sec = max(0, int(remaining.total_seconds()))
    parts = []
    if sec >= 3600:
        parts.append(f"{sec // 3600}h {(sec % 3600) // 60}m")
    elif sec >= 60:
        parts.append(f"{sec // 60}m {sec % 60}s")
    else:
        parts.append(f"{sec}s")
    human = parts[0]
    msg = (
        f"Data requested too early. Latest saved play was {latest.strftime('%Y-%m-%d %H:%M:%S UTC')}; "
        f"next refresh allowed in {human}."
    )
    return msg, sec
