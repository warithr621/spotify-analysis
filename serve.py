#!/usr/bin/env python3
"""Local Flask server: dashboard + Spotify incremental refresh API."""

from __future__ import annotations

import glob
import json
import logging
import os
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

import build_dashboard
import cloud_pull
import spotify_sync

spotify_sync.prime_local_env()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
HOST = os.environ.get("REFRESH_BIND_HOST", "127.0.0.1")
PORT = int(os.environ.get("REFRESH_PORT", "8765"))

OUT_HTML = BASE / "dashboard.html"
TEMPLATE = BASE / "template.html"
LOCK_PATH = BASE / ".refresh.lock"
LAST_STATUS_PATH = BASE / ".refresh.last.json"

oauth_code_queue: queue.Queue[str | None] = queue.Queue()
refresh_thread_lock = threading.Lock()

spotify_sync.set_oauth_code_queue(oauth_code_queue)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def try_acquire_file_lock() -> bool:
    """Cross-process refresh guard; stale if PID not running."""
    if LOCK_PATH.exists():
        try:
            raw = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            pid = int(raw.get("pid", 0))
            if pid > 0 and _pid_alive(pid):
                return False
        except (json.JSONDecodeError, OSError, ValueError):
            pass
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        LOCK_PATH.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            ),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def release_file_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def newest_source_mtime() -> float:
    mtimes: list[float] = []
    for pattern in ("Streaming_History_Audio_*.json",):
        for fp in glob.glob(str(BASE / "music-history" / pattern)):
            try:
                mtimes.append(Path(fp).stat().st_mtime)
            except OSError:
                continue
    return max(mtimes) if mtimes else 0.0


def maybe_rebuild_dashboard() -> None:
    """Rebuild if dashboard missing or older than template / source JSON."""
    try:
        tmpl_m = TEMPLATE.stat().st_mtime
    except OSError:
        tmpl_m = 0.0
    src_m = newest_source_mtime()
    try:
        out_m = OUT_HTML.stat().st_mtime
    except OSError:
        out_m = 0.0
    if not OUT_HTML.is_file() or out_m < src_m or out_m < tmpl_m:
        logger.info("Regenerating dashboard.html")
        build_dashboard.main()


def write_last_status(payload: dict) -> None:
    try:
        LAST_STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Could not write %s: %s", LAST_STATUS_PATH, e)


app = Flask(__name__)


@app.route("/")
def index():
    maybe_rebuild_dashboard()
    if not OUT_HTML.is_file():
        return Response("Run build_dashboard.py first or add Streaming_History_Audio_*.json files to music-history/", status=404)
    return send_file(OUT_HTML, mimetype="text/html; charset=utf-8")


@app.route("/dashboard.js")
def serve_dashboard_js():
    return send_file(BASE / "dashboard.js", mimetype="application/javascript")


@app.route("/dashboard.css")
def serve_dashboard_css():
    return send_file(BASE / "dashboard.css", mimetype="text/css")


@app.route("/callback")
def oauth_callback():
    err = request.args.get("error")
    if err:
        oauth_code_queue.put(None)
        return Response(
            "<!DOCTYPE html><html><body><p>Authorization failed. You can close this window.</p></body></html>",
            mimetype="text/html",
        )
    code = request.args.get("code")
    if not code:
        oauth_code_queue.put(None)
        return Response(
            "<!DOCTYPE html><html><body><p>Missing code. You can close this window.</p></body></html>",
            mimetype="text/html",
        )
    oauth_code_queue.put(code)
    return Response(
        "<!DOCTYPE html><html><body><p>Spotify authorized. You can close this window "
        "and return to the dashboard.</p></body></html>",
        mimetype="text/html",
    )


@app.route("/api/refresh/status", methods=["GET"])
def api_refresh_status():
    if not LAST_STATUS_PATH.is_file():
        return jsonify({})
    try:
        data = json.loads(LAST_STATUS_PATH.read_text(encoding="utf-8"))
        return jsonify(data)
    except (json.JSONDecodeError, OSError):
        return jsonify({"ok": False, "message": "Could not read last refresh status."})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if not refresh_thread_lock.acquire(blocking=False):
        return jsonify(ok=False, message="Refresh already in progress."), 409
    if not try_acquire_file_lock():
        refresh_thread_lock.release()
        return jsonify(ok=False, message="Refresh already in progress."), 409

    try:
        # When the cloud scraper is configured, refresh = pull the merged cloud
        # buffer. Otherwise fall back to the local Spotify sync so the dashboard
        # behaves exactly as before cloud setup. pull_live() is best-effort and
        # never raises.
        cloud_configured = bool(
            (os.environ.get("DATA_REPO") or "").strip()
            and (os.environ.get("DATA_REPO_TOKEN") or "").strip()
        )
        added = 0

        if cloud_configured:
            pulled = cloud_pull.pull_live()
            if not pulled:
                payload = {"ok": False, "message": "Could not pull cloud data. See server logs."}
                write_last_status(payload)
                return jsonify(payload), 502
        else:
            latest = spotify_sync.compute_latest_event_utc()
            try:
                added, _ = spotify_sync.sync_incremental(latest)
            except Exception as e:
                logger.exception("Spotify sync failed")
                payload = {"ok": False, "message": f"Sync failed: {e}"}
                write_last_status(payload)
                return jsonify(payload), 500

        try:
            build_dashboard.main()
        except Exception as e:
            logger.exception("Dashboard rebuild failed")
            payload = {"ok": False, "message": f"Rebuild failed: {e}", "new_rows": added}
            write_last_status(payload)
            return jsonify(payload), 500

        new_latest = spotify_sync.compute_latest_event_utc()
        rebuilt_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if cloud_configured:
            msg = "Pulled latest cloud data."
        else:
            msg = f"Added {added} new play(s)." if added else "No new plays from Spotify (within API window)."
        payload = {
            "ok": True,
            "message": msg,
            "new_rows": added,
            "latest_event_utc": new_latest.strftime("%Y-%m-%dT%H:%M:%SZ") if new_latest else None,
            "rebuilt_at": rebuilt_at,
        }
        write_last_status(payload)
        return jsonify(payload), 200
    finally:
        release_file_lock()
        refresh_thread_lock.release()


@app.route("/api/authorize", methods=["POST"])
def api_authorize():
    """Force a fresh Spotify PKCE login (opens the browser) and store the new
    refresh token in spotify_tokens.json, for seeding/rotating the cloud token."""
    if not refresh_thread_lock.acquire(blocking=False):
        return jsonify(ok=False, message="Another operation is in progress."), 409
    try:
        # Discard any cached token so ensure_access_token runs the full browser flow
        # and yields a brand-new refresh token.
        spotify_sync.TOKENS_PATH.unlink(missing_ok=True)
        try:
            spotify_sync.ensure_access_token()
        except Exception as e:
            logger.exception("Re-authorization failed")
            return jsonify(ok=False, message=f"Re-authorization failed: {e}"), 500
        tokens = spotify_sync.load_tokens() or {}
        if not tokens.get("refresh_token"):
            return jsonify(ok=False, message="Authorized, but no refresh token was returned."), 500
        return jsonify(
            ok=True,
            message="Re-authorized. Refresh token saved to spotify_tokens.json — "
            "commit it to the data repo as live_token.json.",
        ), 200
    finally:
        refresh_thread_lock.release()


def main() -> None:
    maybe_rebuild_dashboard()
    logger.info("Open http://%s:%s/", HOST, PORT)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
