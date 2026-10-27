#!/usr/bin/env python3
"""Assign each artist one genre for the taste map, from its Last.fm tags and similarity links.

Last.fm tags are crowd-sourced and noisy ("lofi", "lo-fi", "lofi hip hop" and "chillhop" are all the
same cluster), and an artist's first tag is often generic ("pop", "japanese"). So:

1. tags are normalised and merged into families (FAMILIES),
2. an artist takes its most *specific* qualifying genre (generic tags such as "pop" or "japanese" are
   only used when nothing more specific applies),
3. genres need enough artists to count; the rest fall back to the next best tag,
4. artists still without a genre (no tags, or only rare ones) borrow the weighted majority genre of the
   artists Last.fm says they are similar to.

Pure functions, no I/O, so it is easy to test (see test_genres.py).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

# display name -> canonical (lowercase alphanumeric) tags that mean the same cluster
FAMILIES: dict[str, list[str]] = {
    "lo-fi": ["lofi", "lofihiphop", "lofibeats", "sadlofi", "lofichill", "chillhop", "chillbeats",
              "instrumentalhiphop", "beats", "jazzhop", "studybeats"],
    "country": ["country", "moderncountry", "countrypop", "classiccountry", "countryrap", "contemporarycountry",
                "countryrock", "popcountry", "americana", "bluegrass", "outlawcountry", "altcountry",
                "alternativecountry", "countryfolk"],
    "k-pop": ["kpop", "korean", "koreanpop", "kpopgirlgroup", "kpopboygroup", "korea"],
    "j-pop": ["jpop", "japanesepop", "japanpop"],
    "j-rock": ["jrock", "japaneserock", "visualkei", "japanesepunk"],
    "hip-hop": ["hiphop", "rap", "trap", "undergroundhiphop", "cloudrap", "gangstarap", "hiphoprap", "boombap", "drill"],
    "r&b / soul": ["rnb", "soul", "neosoul", "rhythmandblues", "randb", "contemporaryrnb", "altrnb"],
    "vocaloid": ["vocaloid", "vocaloidp", "utauloid", "hatsunemiku", "miku", "vocaloidjapanese", "vocaloidmusic"],
    "soundtrack": ["soundtrack", "videogamemusic", "ost", "gamemusic", "videogame", "gamerip", "animeost", "score"],
    "house": ["house", "electrohouse", "deephouse", "progressivehouse", "futurehouse", "tropicalhouse", "techhouse"],
    "drum & bass": ["drumandbass", "dnb", "liquiddnb", "neurofunk", "jungle", "drumnbass"],
    "dubstep": ["dubstep", "brostep", "riddim", "melodicdubstep", "chillstep", "futuregarage"],
    "synthwave": ["synthwave", "retrowave", "outrun", "darksynth", "synthrock"],
    "vaporwave / future funk": ["vaporwave", "futurefunk", "vaporfunk", "mallsoft"],
    "metal": ["metal", "heavymetal", "metalcore", "deathmetal", "blackmetal", "powermetal", "progressivemetal",
              "thrashmetal", "symphonicmetal", "nu metal", "numetal", "melodicdeathmetal"],
    "punk": ["punk", "poppunk", "punkrock", "emo", "hardcorepunk", "skatepunk", "postpunk"],
    "indie rock": ["indierock", "indiepunk", "garagerock", "postrock", "mathrock"],
    "indie pop": ["indiepop", "dreampop", "bedroompop", "twee", "jangle pop", "janglepop"],
    "folk": ["folk", "indiefolk", "folkrock", "neofolk", "psychedelicfolk", "folktronica", "singersongwriter"],
    "classical": ["classical", "orchestral", "piano", "modernclassical", "contemporaryclassical", "neoclassical", "baroque"],
    "jazz": ["jazz", "smoothjazz", "jazzfusion", "bebop", "nujazz", "vocaljazz", "jazzpop"],
    "edm": ["edm", "dance", "electrodance", "bigroom", "dancepop", "electronicdance"],
    "trance": ["trance", "progressivetrance", "psytrance", "uplifting trance", "upliftingtrance", "vocaltrance"],
    "ambient": ["ambient", "downtempo", "newage", "darkambient", "drone", "chillout", "chill", "chillwave",
                "chillsynth", "relaxing", "lounge", "trip hop", "triphop"],
    "chiptune": ["chiptune", "8bit", "bitpop", "chipmusic", "nintendocore"],
    "hyperpop": ["hyperpop", "digicore", "glitchpop", "pcmusic", "bubblegumbass"],
    "city pop": ["citypop", "shibuyakei"],
    "anime": ["anime", "animemusic", "animesong"],
    "synthpop": ["synthpop", "electropop", "newwave", "futurepop"],
    "pop rock": ["poprock", "powerpop", "softrock"],
    "latin": ["latin", "reggaeton", "salsa", "latinpop", "bachata", "urbanlatin"],
    "breakcore": ["breakcore", "speedcore", "gabber", "happyhardcore", "hardcoredance", "idm"],
    "hard dance": ["hardstyle", "hardhouse", "frenchcore", "uptempohardcore"],
    "future bass": ["futurebass", "kawaiifuturebass", "melodicbass"],
    "disco / funk": ["disco", "funk", "nudisco", "boogie", "funkhouse"],
    "reggae": ["reggae", "dub", "ska", "dancehall"],
    "blues": ["blues", "bluesrock", "electricblues"],
    "japanese": ["japanese", "japan"],
    "c-pop": ["cpop", "chinese", "mandopop", "cantopop", "chinesepop"],
}

# Umbrella tags: kept as a genre only when an artist has nothing more specific.
GENERIC = {
    "electronic", "pop", "rock", "indie", "alternative", "japanese", "japan", "american", "usa", "british", "uk",
    "canadian", "chinese", "french", "swedish", "german", "australian", "european", "instrumental",
    "femalevocalists", "malevocalists", "seenlive", "experimental", "electro", "alternativerock", "vocal",
    "singer", "female", "male", "mellow", "sad", "happy", "cute", "upbeat", "party", "energetic",
}

_FAMILY_OF = {member: name for name, members in FAMILIES.items() for member in (re.sub(r"[^a-z0-9]", "", m.lower()) for m in members)}


def canon(tag: str) -> str:
    return re.sub(r"[^a-z0-9]", "", tag.lower())


def _keys(tags: list[str], display: dict[str, Counter]) -> list[str]:
    """Ordered unique genre keys for an artist's tags (family display name, or the canonical tag)."""
    out: list[str] = []
    for t in tags:
        c = canon(t)
        if not c:
            continue
        key = _FAMILY_OF.get(c, c)
        display[key][_FAMILY_OF.get(c) or t.strip().lower()] += 1
        if key not in out:
            out.append(key)
    return out


def assign_genres(
    tags: list[list[str]],
    minutes: list[float],
    links: list[list] | None = None,
    min_artists: int = 12,
    max_genres: int = 40,
    look_at: int = 4,
) -> tuple[list[str], list[int | None], list[bool]]:
    """Returns `(genre_names, genre_index_per_artist, inferred_flag_per_artist)`.

    `genre_names` is ordered by total minutes (so index order doubles as legend order); an artist's
    index is None when no genre could be found even from its neighbours. `links` are
    `[i, j, match]` similarity pairs between artist indices."""
    n = len(tags)
    display: dict[str, Counter] = defaultdict(Counter)
    keys = [_keys(t, display) for t in tags]
    name_of = {k: (k if k in FAMILIES else display[k].most_common(1)[0][0]) for k in display}

    def pick(i: int, allowed: set[str]) -> str | None:
        cand = [k for k in keys[i][:look_at] if k in allowed]
        specific = [k for k in cand if k not in GENERIC and name_of.get(k, k) not in GENERIC]
        return (specific or cand or [None])[0]

    # Genres need enough artists to be a cluster at all.
    count = Counter(k for ks in keys for k in set(ks[:look_at]))
    allowed = {k for k, c in count.items() if c >= min_artists}

    # Assign, then drop genres that ended up too small or beyond the cap, and assign again.
    for _ in range(3):
        chosen = [pick(i, allowed) for i in range(n)]
        mins: Counter = Counter()
        people: Counter = Counter()
        for i, g in enumerate(chosen):
            if g is not None:
                mins[g] += minutes[i]
                people[g] += 1
        keep = {g for g, c in people.items() if c >= max(4, min_artists // 2)}
        # Rank by how many artists form the cluster (not minutes): small-listening clusters such as
        # country or lo-fi are still real regions of the map.
        keep = set(sorted(keep, key=lambda g: -people[g])[:max_genres])
        if keep == allowed:
            break
        allowed = keep
    chosen = [pick(i, allowed) for i in range(n)]

    # Artists with no usable tag borrow the weighted majority genre of their similar artists.
    inferred = [False] * n
    if links:
        nbrs: dict[int, list[tuple[int, float]]] = defaultdict(list)
        for i, j, m in links:
            nbrs[i].append((j, m))
            nbrs[j].append((i, m))
        for _ in range(2):
            updates: dict[int, str] = {}
            for i in range(n):
                if chosen[i] is not None or i not in nbrs:
                    continue
                vote: Counter = Counter()
                for j, m in nbrs[i]:
                    if chosen[j] is not None:
                        vote[chosen[j]] += m
                if vote:
                    updates[i] = vote.most_common(1)[0][0]
            for i, g in updates.items():
                chosen[i] = g
                inferred[i] = True

    totals: Counter = Counter()
    for i, g in enumerate(chosen):
        if g is not None:
            totals[g] += minutes[i]
    order = [g for g, _ in totals.most_common()]
    index = {g: x for x, g in enumerate(order)}
    names = [name_of.get(g, g) for g in order]
    return names, [index.get(g) if g is not None else None for g in chosen], inferred
