#!/usr/bin/env python3

from __future__ import annotations

import glob
import heapq
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Global display timezone. All user-facing day/month/year buckets, the heatmap,
# and the date picker bounds project events into this zone (handles CST/CDT) so
# the dashboard reflects local calendar days instead of UTC days.
DISPLAY_TZ = ZoneInfo("America/Chicago")

BASE = Path(__file__).resolve().parent
HISTORY_DIR = BASE / "music-history"
TEMPLATE = BASE / "template.html"
OUT_HTML = BASE / "dashboard.html"
AUDIO_GLOB = "Streaming_History_Audio_*.json"

logger = logging.getLogger(__name__)


def ym(d: datetime) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_events() -> list[dict]:
    rows: list[dict] = []
    files = sorted(glob.glob(str(HISTORY_DIR / AUDIO_GLOB)))
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning("Skipping malformed or unreadable JSON %s: %s", fp, e)
            continue
        if not isinstance(data, list):
            logger.warning("Skipping %s: expected list at top level, got %s", fp, type(data).__name__)
            continue
        rows.extend(data)
    return rows


def latest_timestamp(events: list[dict]) -> datetime | None:
    """Newest `ts` among all rows (any stream type), for export freshness."""
    latest: datetime | None = None
    for r in events:
        dt = parse_ts(r.get("ts") or "")
        if dt and (latest is None or dt > latest):
            latest = dt
    return latest


def is_music_stream(r: dict) -> bool:
    if r.get("spotify_episode_uri"):
        return False
    if r.get("audiobook_uri"):
        return False
    return bool(r.get("spotify_track_uri"))


def normalize_platform(raw: str) -> str:
    p = (raw or "unknown").lower().strip()
    if p.startswith("web_player"):
        return "Web"
    if p.startswith("osx"):
        return "macOS"
    if p.startswith("ios"):
        return "iOS"
    return p[:1].upper() + p[1:] if p.isalpha() else p


def canon_track_key(track_name: str, artist_name: str) -> str:
    """Merge duplicate Spotify URIs for the same normalized title + artist."""
    t = track_name.strip().lower()
    a = artist_name.strip().lower()
    return f"{t}\u0001{a}"


def canon_album_key(album_name: str, artist_name: str) -> str:
    a = artist_name.strip().lower()
    al = album_name.strip().lower()
    return f"{al}\u0001{a}"


def day_index(day_iso: str, epoch: date) -> int:
    """Days since epoch (calendar math only; matches Chicago wall dates in the bundle)."""
    return (datetime.fromisoformat(day_iso).date() - epoch).days


def top_recent_streams(events: list[dict], n: int = 20) -> list[dict]:
    """Most recent `n` music plays by `ts` (O(n log k) over the event list)."""

    def entries():
        for r in events:
            if not is_music_stream(r):
                continue
            dt = parse_ts(str(r.get("ts") or ""))
            if not dt:
                continue
            if int(r.get("ms_played") or 0) <= 0:
                continue
            track_name = (r.get("master_metadata_track_name") or "Unknown Track").strip()
            artist_name = (r.get("master_metadata_album_artist_name") or "Unknown Artist").strip()
            album_name = (r.get("master_metadata_album_album_name") or "Unknown Album").strip()
            yield (
                dt,
                {
                    "ts_utc": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "track": track_name,
                    "artist": artist_name,
                    "album": album_name,
                },
            )

    rows = heapq.nlargest(n, entries(), key=lambda x: x[0])
    return [row for _, row in rows]


def main() -> None:
    if not logging.root.handlers:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    events = load_events()
    latest_event_any = latest_timestamp(events)

    skipped_n = shuffle_n = 0

    glob_day_ms: defaultdict[str, int] = defaultdict(int)
    glob_day_n: defaultdict[str, int] = defaultdict(int)
    glob_month_ms: defaultdict[str, int] = defaultdict(int)
    glob_month_n: defaultdict[str, int] = defaultdict(int)
    glob_year_ms: defaultdict[str, int] = defaultdict(int)
    glob_year_n: defaultdict[str, int] = defaultdict(int)

    plat_ms: defaultdict[str, int] = defaultdict(int)
    country_ms: defaultdict[str, int] = defaultdict(int)
    reason_end_ms: defaultdict[str, int] = defaultdict(int)

    weekday_hour_ms = [[0] * 24 for _ in range(7)]

    artist_ms: defaultdict[str, int] = defaultdict(int)
    artist_n: defaultdict[str, int] = defaultdict(int)

    track_bucket: defaultdict[str, dict] = defaultdict(
        lambda: {"title": "", "artist": "", "album": "", "uri": "", "ms": 0, "n": 0}
    )
    album_bucket: defaultdict[str, dict] = defaultdict(
        lambda: {"album": "", "artist": "", "ms": 0, "n": 0}
    )

    artist_daily: defaultdict[str, defaultdict[str, tuple[int, int]]] = defaultdict(
        lambda: defaultdict(lambda: (0, 0))
    )
    track_daily: defaultdict[str, defaultdict[str, tuple[int, int]]] = defaultdict(
        lambda: defaultdict(lambda: (0, 0))
    )
    album_daily: defaultdict[str, defaultdict[str, tuple[int, int]]] = defaultdict(
        lambda: defaultdict(lambda: (0, 0))
    )

    earliest: datetime | None = None
    latest: datetime | None = None

    excluded = total_ms_all = total_n_all = 0

    for r in events:
        if not is_music_stream(r):
            excluded += 1
            continue
        ts_raw = r.get("ts") or ""
        dt = parse_ts(ts_raw)
        if not dt:
            continue
        ms = int(r.get("ms_played") or 0)
        if ms <= 0:
            continue

        total_ms_all += ms
        total_n_all += 1

        if earliest is None or dt < earliest:
            earliest = dt
        if latest is None or dt > latest:
            latest = dt

        dt_local = dt.astimezone(DISPLAY_TZ)
        dkey = dt_local.date().isoformat()
        mkey = ym(dt_local)
        ykey = str(dt_local.year)

        glob_day_ms[dkey] += ms
        glob_day_n[dkey] += 1
        glob_month_ms[mkey] += ms
        glob_month_n[mkey] += 1
        glob_year_ms[ykey] += ms
        glob_year_n[ykey] += 1

        if r.get("skipped"):
            skipped_n += 1
        if r.get("shuffle"):
            shuffle_n += 1

        plat = normalize_platform(r.get("platform") or "")
        plat_ms[plat] += ms

        cc = (r.get("conn_country") or "unknown").strip() or "unknown"
        country_ms[cc] += ms

        re = (r.get("reason_end") or "unknown").strip() or "unknown"
        reason_end_ms[re] += ms

        wd = dt_local.weekday()  # Mon=0 in display timezone
        weekday_hour_ms[wd][dt_local.hour] += ms

        artist_name = (r.get("master_metadata_album_artist_name") or "Unknown Artist").strip()
        track_name = (r.get("master_metadata_track_name") or "Unknown Track").strip()
        album_name = (r.get("master_metadata_album_album_name") or "Unknown Album").strip()
        uri = r.get("spotify_track_uri") or ""

        tkey = canon_track_key(track_name, artist_name)

        tb = track_bucket[tkey]
        if not tb["title"]:
            tb["title"] = track_name
            tb["artist"] = artist_name
            tb["album"] = album_name
        if uri and not tb.get("uri"):
            tb["uri"] = uri
        tb["ms"] += ms
        tb["n"] += 1

        alb_key = canon_album_key(album_name, artist_name)
        ab = album_bucket[alb_key]
        if not ab["album"]:
            ab["album"] = album_name
            ab["artist"] = artist_name
        ab["ms"] += ms
        ab["n"] += 1

        artist_ms[artist_name] += ms
        artist_n[artist_name] += 1

        ad = artist_daily[artist_name]
        cms, cn = ad[dkey]
        ad[dkey] = (cms + ms, cn + 1)

        td = track_daily[tkey]
        cms, cn = td[dkey]
        td[dkey] = (cms + ms, cn + 1)

        ald = album_daily[alb_key]
        cms, cn = ald[dkey]
        ald[dkey] = (cms + ms, cn + 1)

    # Derived: daily sorted list for frontend (compact day index `i` vs day_epoch)
    all_days_sorted = sorted(glob_day_ms.keys())
    epoch_date = datetime.fromisoformat(all_days_sorted[0]).date() if all_days_sorted else None
    day_series = []
    if epoch_date is not None:
        for d in all_days_sorted:
            day_series.append(
                {"i": day_index(d, epoch_date), "ms": glob_day_ms[d], "n": glob_day_n[d]}
            )

    month_keys_sorted = sorted(glob_month_ms.keys())
    month_series = [{"m": m, "ms": glob_month_ms[m], "n": glob_month_n[m]} for m in month_keys_sorted]

    year_keys_sorted = sorted(glob_year_ms.keys(), key=int)
    year_series = [{"y": y, "ms": glob_year_ms[y], "n": glob_year_n[y]} for y in year_keys_sorted]

    # Top entities with per-day breakdown (limit for payload size)
    ARTIST_MONTHLY_CAP = 2500
    TRACK_MONTHLY_CAP = 2600
    ALBUM_MONTHLY_CAP = 1400

    def compact_days(days_raw: dict[str, tuple[int, int]]) -> list[list[int]]:
        if epoch_date is None:
            return []
        return [
            [day_index(dk, epoch_date), dv[0], dv[1]]
            for dk, dv in sorted(days_raw.items())
        ]

    top_artists = sorted(artist_ms.keys(), key=lambda a: (-artist_ms[a], a.lower()))[:ARTIST_MONTHLY_CAP]
    artists_out = []
    for a in top_artists:
        days_raw = artist_daily[a]
        artists_out.append(
            {
                "name": a,
                "ms": artist_ms[a],
                "n": artist_n[a],
                "days": compact_days(days_raw),
            }
        )

    top_track_keys = sorted(track_bucket.keys(), key=lambda k: (-track_bucket[k]["ms"], k))[:TRACK_MONTHLY_CAP]
    tracks_out = []
    for k in top_track_keys:
        b = track_bucket[k]
        days_raw = track_daily[k]
        tracks_out.append(
            {
                "key": k,
                "title": b["title"],
                "artist": b["artist"],
                "album": b["album"],
                "uri": b["uri"],
                "ms": b["ms"],
                "n": b["n"],
                "days": compact_days(days_raw),
            }
        )

    top_album_keys = sorted(album_bucket.keys(), key=lambda k: (-album_bucket[k]["ms"], k))[:ALBUM_MONTHLY_CAP]
    albums_out = []
    for k in top_album_keys:
        b = album_bucket[k]
        days_raw = album_daily[k]
        albums_out.append(
            {
                "key": k,
                "album": b["album"],
                "artist": b["artist"],
                "ms": b["ms"],
                "n": b["n"],
                "days": compact_days(days_raw),
            }
        )

    unique_artists = len(artist_ms)
    unique_tracks = len(track_bucket)
    unique_albums = len(album_bucket)

    # Longest listening streak (days with ms > 0)
    day_set = set(glob_day_ms.keys())
    last_d = None
    cur_start = streak_start_best = streak_end_best = None
    cur_streak_len = max_streak_len = 0
    for d_iso in sorted(day_set):
        d = datetime.fromisoformat(d_iso).date()
        if last_d is None:
            cur_streak_len = 1
            cur_start = d
            cur_end = d
        elif d == last_d + timedelta(days=1):
            cur_streak_len += 1
            cur_end = d
        else:
            if cur_streak_len > max_streak_len:
                max_streak_len = cur_streak_len
                streak_start_best, streak_end_best = cur_start, cur_end
            cur_streak_len = 1
            cur_start = cur_end = d
        last_d = d
    if last_d is not None and cur_streak_len > max_streak_len:
        max_streak_len = cur_streak_len
        streak_start_best, streak_end_best = cur_start, cur_end

    plat_list = [{"p": k, "ms": v} for k, v in sorted(plat_ms.items(), key=lambda x: -x[1])][:12]
    country_list = [{"c": k, "ms": v} for k, v in sorted(country_ms.items(), key=lambda x: -x[1])][:12]
    reason_list = [{"r": k, "ms": v} for k, v in sorted(reason_end_ms.items(), key=lambda x: -x[1])]

    recent_streams = top_recent_streams(events, 20)

    now_ct = datetime.now(DISPLAY_TZ)
    bundle = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "coverage": {
            "earliest_utc": earliest.isoformat().replace("+00:00", "Z") if earliest else None,
            "latest_utc": latest.isoformat().replace("+00:00", "Z") if latest else None,
            "earliest_day": all_days_sorted[0] if all_days_sorted else None,
            "latest_day": all_days_sorted[-1] if all_days_sorted else None,
            "day_epoch": all_days_sorted[0] if all_days_sorted else None,
            "as_of_day_chicago": now_ct.date().isoformat(),
            "display_timezone": str(DISPLAY_TZ),
            "first_play_chicago": earliest.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M %Z")
            if earliest
            else None,
            "last_play_chicago": latest.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M %Z")
            if latest
            else None,
            "latest_event_utc": latest_event_any.isoformat().replace("+00:00", "Z")
            if latest_event_any
            else None,
            "included_streams": total_n_all,
            "excluded_non_music": excluded,
            "skipped_streams": skipped_n,
            "shuffle_streams": shuffle_n,
        },
        "totals": {
            "minutes": round(total_ms_all / 60000, 1),
            "ms": total_ms_all,
            "streams": total_n_all,
            "unique_artists": unique_artists,
            "unique_tracks": unique_tracks,
            "unique_albums": unique_albums,
        },
        "streak_best_days": max_streak_len if max_streak_len else 0,
        "streak_best_span": {
            "from": streak_start_best.isoformat() if streak_start_best else None,
            "to": streak_end_best.isoformat() if streak_end_best else None,
        },
        "series": {"day": day_series, "month": month_series, "year": year_series},
        "weekday_hour_ms": weekday_hour_ms,
        "platforms": plat_list,
        "countries": country_list,
        "reason_end": reason_list,
        "artists": artists_out,
        "tracks": tracks_out,
        "albums": albums_out,
        "recent_streams": recent_streams,
        "notes": (
            "Spotify Extended Streaming History does not include genre metadata; podcast/audiobook rows excluded. "
            "Tracks and albums collapse duplicate rows that match the same normalized title + performer "
            "(case-insensitive); distinct titles (e.g. alternate versions with different titles) remain separate."
        ),
    }

    tmpl = TEMPLATE.read_text(encoding="utf-8")
    json_blob = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    escaped = json_blob.replace("</script", "<\\/script")
    merged = tmpl.replace("__DATA_JSON__", escaped)

    OUT_HTML.write_text(merged, encoding="utf-8")
    kb = OUT_HTML.stat().st_size / 1024
    print(f"Wrote {OUT_HTML.name} (~{kb:.1f} KB)")


if __name__ == "__main__":
    main()
