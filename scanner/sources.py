"""Where to watch: maps a broadcaster name onto something you can click.

Broadcaster strings come back from the feeds in a dozen spellings ("ESPN+",
"ESPN Plus", "espn+"), so match on a normalised key rather than exactly.
"""

import re

# key -> (display name, url, kind)
SERVICES = {
    "paramount+": ("Paramount+", "https://www.paramountplus.com/", "streaming"),
    "paramountplus": ("Paramount+", "https://www.paramountplus.com/", "streaming"),
    "cbs": ("CBS", "https://www.cbs.com/live-tv/", "tv"),
    "dazn": ("DAZN", "https://www.dazn.com/", "streaming"),
    "espn+": ("ESPN+", "https://plus.espn.com/", "streaming"),
    "espnplus": ("ESPN+", "https://plus.espn.com/", "streaming"),
    "espn": ("ESPN", "https://www.espn.com/watch/", "tv"),
    "espn2": ("ESPN2", "https://www.espn.com/watch/", "tv"),
    "ufcfightpass": ("UFC Fight Pass", "https://ufcfightpass.com/", "streaming"),
    "fightpass": ("UFC Fight Pass", "https://ufcfightpass.com/", "streaming"),
    "primevideo": ("Prime Video", "https://www.amazon.com/gp/video/storefront", "streaming"),
    "amazonprimevideo": ("Prime Video", "https://www.amazon.com/gp/video/storefront", "streaming"),
    "netflix": ("Netflix", "https://www.netflix.com/", "streaming"),
    "tntsports": ("TNT Sports", "https://www.tntsports.co.uk/", "tv"),
    "skysports": ("Sky Sports", "https://www.skysports.com/", "tv"),
    "skysportsbox": ("Sky Sports Box Office", "https://www.skysports.com/box-office", "ppv"),
    "hulu": ("Hulu", "https://www.hulu.com/", "streaming"),
    "max": ("Max", "https://www.max.com/", "streaming"),
    "peacock": ("Peacock", "https://www.peacocktv.com/", "streaming"),
    "youtube": ("YouTube", "https://www.youtube.com/", "streaming"),
    "triller": ("Triller TV", "https://triller.tv/", "streaming"),
    "fox": ("FOX", "https://www.fox.com/live/", "tv"),
    "fs1": ("FS1", "https://www.foxsports.com/live", "tv"),
    "daznppv": ("DAZN PPV", "https://www.dazn.com/", "ppv"),
    "daznpayperview": ("DAZN PPV", "https://www.dazn.com/", "ppv"),
    "probox": ("ProBox TV", "https://www.proboxtv.com/", "streaming"),
    "proboxtv": ("ProBox TV", "https://www.proboxtv.com/", "streaming"),
    "tycsports": ("TyC Sports", "https://www.tycsports.com/", "tv"),
    "tiktoklive": ("TikTok LIVE", "https://www.tiktok.com/live", "streaming"),
    "tiktok": ("TikTok LIVE", "https://www.tiktok.com/live", "streaming"),
    "nolimitboxing": ("No Limit Boxing", None, "other"),
    "matchtv": ("Match TV", None, "tv"),
    "rizintv": ("RIZIN.TV", "https://www.rizin.tv/", "streaming"),
    "abema": ("ABEMA", "https://abema.tv/", "streaming"),
    "onefc": ("ONE (onefc.com)", "https://www.onefc.com/", "streaming"),
}

# ESPN lumps smaller promotions into an "other" bucket and lists no broadcaster
# for them. These are the promotions worth naming, matched against the event
# title, with the service that actually carries them in the US.
PROMOTIONS = [
    (r"road to ufc",       "UFC",   ["UFC Fight Pass"]),
    (r"\brizin\b",         "RIZIN", ["RIZIN.TV"]),
    (r"\bone\b.*(?:fight night|championship)|^one[ :]", "ONE", ["Prime Video"]),
    (r"cage warriors",     "Cage Warriors", ["UFC Fight Pass"]),
    (r"\blfa\b|legacy fighting", "LFA", ["UFC Fight Pass"]),
    (r"invicta",           "Invicta FC", ["UFC Fight Pass"]),
    (r"\bksw\b",           "KSW", []),
    (r"oktagon",           "Oktagon", []),
]

# Placeholder strings the sources use when a broadcaster isn't announced yet.
UNANNOUNCED = {"tba", "tbc", "tbd", "n/a", "na", "none", "unknown"}


def _key(name):
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch == "+")


def resolve(name):
    """Turn a raw broadcaster string into {name, url, kind}."""
    name = (name or "").strip()
    if not name:
        return None
    k = _key(name)
    if k in UNANNOUNCED:
        return {"name": "Not announced", "url": None, "kind": "unannounced"}
    if k in SERVICES:
        disp, url, kind = SERVICES[k]
        return {"name": disp, "url": url, "kind": kind}
    # Unknown broadcaster: keep the name, we just have nowhere to point.
    return {"name": name, "url": None, "kind": "other"}


def identify(event_name):
    """Name the promotion behind an event title, and how to watch it.

    Used for ESPN's catch-all bucket, which carries real events but labels
    them only "Other" with no broadcaster.
    """
    for pattern, org, watch in PROMOTIONS:
        if re.search(pattern, event_name or "", re.I):
            return org, watch
    return None, []


def resolve_all(names):
    """Resolve a list of broadcaster names, de-duplicated, order preserved."""
    out, seen = [], set()
    for n in names:
        r = resolve(n)
        if r and r["name"] not in seen:
            seen.add(r["name"])
            out.append(r)
    return out
