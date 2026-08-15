"""Where to watch: maps a broadcaster name onto something you can click.

Broadcaster strings come back from the feeds in a dozen spellings ("ESPN+",
"ESPN Plus", "espn+"), so match on a normalised key rather than exactly.
"""

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
}

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


def resolve_all(names):
    """Resolve a list of broadcaster names, de-duplicated, order preserved."""
    out, seen = [], set()
    for n in names:
        r = resolve(n)
        if r and r["name"] not in seen:
            seen.add(r["name"])
            out.append(r)
    return out
