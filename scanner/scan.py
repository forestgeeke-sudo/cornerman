#!/usr/bin/env python3
"""Cornerman scanner: build docs/fights.json from public schedule feeds.

Runs on GitHub Actions, not on anyone's desktop. Stdlib only on purpose --
no dependency can rot out from under a job that runs unattended for months.

Sources:
  MMA    ESPN's public scoreboard JSON (UFC, PFL, Bellator). Key-free.
  ONE    onefc.com/events (Wikipedia's list lags and skips Friday Fights).
  Boxing boxing-schedule.com, parsed for the factual bits only: date,
         matchup, venue, broadcaster.
"""

import gzip
import json
import os
import re
import sys
import time
import html
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sources

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "fights.json"
HORIZON_DAYS = 180

# ESPN's API rejects browser-shaped user agents with a 403 and serves
# self-identifying clients happily, so don't "fix" this by pretending to be
# Chrome -- that is the failure case, not the workaround.
UA_API = "Cornerman/1.0 (+https://github.com/forestgeeke-sudo/cornerman)"
UA_WEB = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Headshots are on ESPN's image CDN, keyed by the competitor id the scoreboard
# already returns. Constructing the URL costs no extra API call. Missing photos
# 404; the UI hides them. Combiner keeps the files small enough for a card.
HEADSHOT = ("https://a.espncdn.com/combiner/i"
            "?img=/i/headshots/mma/players/full/{id}.png&w=280&h=360")


def portrait(competitor, name):
    cid = str(competitor.get("id") or "")
    if not cid.isdigit():
        return None
    return {"name": name, "url": HEADSHOT.format(id=cid)}


# org=None means "derive the promotion from the event title". ESPN's "other"
# bucket is a genuine catch-all -- it carries real cards (Road to UFC, Super
# RIZIN) that have no dedicated feed, labelled only "Other" with no broadcaster.
ESPN_LEAGUES = [
    ("ufc", "UFC"),
    ("pfl", "PFL"),
    ("bellator", "Bellator"),
    ("other", None),
]


def fetch(url, timeout=30, ua=UA_API):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept-Encoding": "gzip",
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def warn(msg):
    print(f"WARN: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# MMA
# --------------------------------------------------------------------------

def classify_ufc(name):
    """Which UFC events are worth waking a phone up for.

    Numbered cards and the weekly Fight Night are; Contender Series and the
    rest are not. Anything unrecognised gets 'other' so it stays quiet.
    """
    n = name.lower()
    if re.search(r"\bufc\s+\d{2,4}\b", n):
        return "numbered"
    if "contender series" in n:
        return "contender"
    if "fight night" in n or "on abc" in n or "on espn" in n:
        return "fight_night"
    # "Noche UFC", "UFC Fight Pass Invitational" etc. -- a real card, but not
    # one of the two tiers the notifier is scoped to.
    return "other"


def parse_espn_event(ev, org):
    comps = ev.get("competitions") or []
    if not comps:
        return None

    name = ev.get("name") or ev.get("shortName") or "Untitled card"
    fallback_watch = []
    if org is None:
        org, fallback_watch = sources.identify(name)
        if org is None:
            return None      # unrecognised catch-all entry: better absent than mislabelled

    # ESPN returns bouts in running order: the main event is last.
    bouts = list(reversed(comps))

    venue, location = None, None
    for c in comps:
        v = c.get("venue") or {}
        if v.get("fullName"):
            venue = v["fullName"]
            addr = v.get("address") or {}
            location = ", ".join(x for x in (
                addr.get("city"), addr.get("state") or addr.get("country")) if x)
            break

    def broadcasters(node):
        names = []
        for b in node.get("broadcasts") or []:
            names.extend(b.get("names") or [])
        for g in node.get("geoBroadcasts") or []:
            nm = (g.get("media") or {}).get("shortName")
            if nm:
                names.append(nm)
        return names

    event_watch = (sources.resolve_all(broadcasters(comps[0]))
                   or sources.resolve_all(fallback_watch))

    card = []
    for i, c in enumerate(bouts):
        fighters, portraits = [], []
        for cm in c.get("competitors") or []:
            a = cm.get("athlete") or {}
            nm = a.get("displayName")
            if not nm:
                continue
            fighters.append(nm)
            shot = portrait(cm, nm)
            if shot:
                portraits.append(shot)
        if len(fighters) < 2:
            continue
        slot = "main" if i == 0 else ("comain" if i == 1 else "undercard")
        card.append({
            "order": i + 1,
            "slot": slot,
            "weight": (c.get("type") or {}).get("abbreviation"),
            "fighters": fighters,
            "watch": sources.resolve_all(broadcasters(c)) or event_watch,
            "portraits": portraits,
        })

    headline = name.split(":", 1)[1].strip() if ":" in name else (
        " vs. ".join(card[0]["fighters"]) if card else name)

    link = None
    for l in ev.get("links") or []:
        if l.get("href"):
            link = l["href"]
            break

    return {
        "id": f"{org.lower()}-{ev.get('id')}",
        "sport": "mma",
        "org": org,
        "tier": classify_ufc(name) if org == "UFC" else "other",
        "name": name,
        "headline": headline,
        "date": ev.get("date"),
        "datePrecision": "time",
        "venue": venue,
        "location": location,
        "watch": event_watch,
        "card": card,
        "art": (card[0].get("portraits") or None) if card else None,
        "note": None,
        "link": link,
    }


def scan_mma(start, end):
    events = []
    rng = f"{start:%Y%m%d}-{end:%Y%m%d}"
    for i, (slug, org) in enumerate(ESPN_LEAGUES):
        # Serial + a pause. A parallel burst 403'd ESPN's IP for 10+ minutes.
        if i:
            time.sleep(1.8)
        url = f"https://site.api.espn.com/apis/site/v2/sports/mma/{slug}/scoreboard?dates={rng}"
        try:
            data = json.loads(fetch(url))
        except Exception as e:
            warn(f"{org} feed failed: {e}")
            continue
        got = 0
        for ev in data.get("events") or []:
            parsed = parse_espn_event(ev, org)
            if parsed and parsed["date"]:
                events.append(parsed)
                got += 1
        print(f"  {org or 'Other promotions'}: {got} events")
    return events


# --------------------------------------------------------------------------
# Boxing
# --------------------------------------------------------------------------

BOX_URL = "https://boxing-schedule.com/"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def _text(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def scan_boxing(today, end):
    """Pull date / matchup / venue / broadcaster out of the schedule page.

    Only facts are extracted -- no descriptive copy is carried over.
    """
    try:
        page = fetch(BOX_URL, ua=UA_WEB)
    except Exception as e:
        warn(f"boxing feed failed: {e}")
        return []

    blocks = re.findall(
        r'<div class="events__single">(.*?)</div>\s*</div>\s*</div>', page, re.S)
    if not blocks:
        warn("boxing page layout changed -- no event blocks matched")
        return []

    events = []
    for b in blocks:
        def grab(cls, tags="div|h3|h4|ul|a|span"):
            m = re.search(
                r'class="[^"]*%s[^"]*"[^>]*>(.*?)</(?:%s)>' % (cls, tags), b, re.S)
            return _text(m.group(1)) if m else ""

        raw_date = grab("events__date")
        title = grab("events__title")
        if not raw_date or not title:
            continue

        m = re.search(r"(\d{1,2})\s*([A-Za-z]{3})", raw_date)
        if not m:
            continue
        day, mon = int(m.group(1)), MONTHS.get(m.group(2).lower()[:3])
        if not mon:
            continue
        # The page omits the year; roll forward from today.
        year = today.year if mon >= today.month else today.year + 1
        try:
            when = datetime(year, mon, day, tzinfo=timezone.utc)
        except ValueError:
            continue
        if when.date() < today.date() or when > end:
            continue

        # Inside the meta list each <li> is tagged by an icon: a video camera
        # marks the broadcaster, a map pin the venue. The broadcaster name is
        # wrapped in an affiliate <a>, so take the li's text and throw the
        # href away -- links come from our own service table instead.
        bcast, place = "", ""
        for li in re.findall(r"<li\b[^>]*>(.*?)</li>", b, re.S):
            if "fa-video" in li:
                bcast = _text(li)
            elif "fa-map-marker" in li:
                place = _text(li)

        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
        events.append({
            "id": f"box-{when:%Y%m%d}-{slug}",
            "sport": "boxing",
            "org": "Boxing",
            "tier": "other",
            "name": title,
            "headline": title,
            "date": when.strftime("%Y-%m-%dT00:00:00Z"),
            "datePrecision": "day",
            "venue": None,
            "location": place or None,
            "watch": sources.resolve_all([x.strip() for x in re.split(r"[/,&]| and ", bcast) if x.strip()]),
            "card": [],
            "art": None,
            "note": None,
            "link": BOX_URL,
        })
    print(f"  Boxing: {len(events)} events")
    return events


# --------------------------------------------------------------------------
# ONE Championship
# --------------------------------------------------------------------------

ONE_URL = "https://www.onefc.com/events/"


def scan_one(today, end):
    """Upcoming cards from ONE's own events page.

    ESPN has no ONE feed. Wikipedia's scheduled-events table lags by weeks
    and omits Friday Fights, so this reads the timestamps ONE publishes.
    """
    try:
        page = fetch(ONE_URL, ua=UA_WEB)
    except Exception as e:
        warn(f"ONE feed failed: {e}")
        return []

    start, stop = page.find('id="upcoming"'), page.find('id="past"')
    if start < 0:
        warn("ONE page layout changed -- no upcoming section")
        return []
    chunk = page[start:stop if stop > start else None]

    events, seen = [], set()
    for m in re.finditer(
            r'<a class="title" href="([^"]+)" title="([^"]+)"', chunk):
        href, title = m.group(1), html.unescape(m.group(2)).strip()
        if href in seen:
            continue
        tail = chunk[m.end():m.end() + 2000]
        ts = re.search(r'data-timestamp="(\d+)"', tail)
        if not ts:
            continue
        when = datetime.fromtimestamp(int(ts.group(1)), timezone.utc)
        if when.date() < today.date() or when > end:
            continue

        loc_m = re.search(r'<div class="location">([^<]*)</div>', tail)
        place = html.unescape(loc_m.group(1)).strip() if loc_m else ""
        venue = location = None
        if place:
            venue, location = (place.rsplit(", ", 1) if ", " in place
                               else (place, None))

        seen.add(href)
        slug = href.rstrip("/").rsplit("/", 1)[-1][:48]
        headline = title.split(":", 1)[1].strip() if ":" in title else title
        friday = "friday fights" in title.lower()
        events.append({
            "id": f"one-{when:%Y%m%d}-{slug}",
            "sport": "mma",
            "org": "ONE",
            "tier": "contender" if friday else "other",
            "name": title,
            "headline": headline,
            "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datePrecision": "time",
            "venue": venue,
            "location": location,
            "watch": sources.resolve_all(
                ["YouTube"] if friday else ["Prime Video"]),
            "card": [],
            "art": None,
            "note": None,
            "link": href.split("?")[0],
        })
    print(f"  ONE: {len(events)} events")
    return events


# --------------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=HORIZON_DAYS)
    print(f"Scanning {now:%Y-%m-%d} -> {end:%Y-%m-%d}")

    # ESPN is the backbone (UFC/PFL) and always has cards on the books, so an
    # empty result there means the feed is broken, not that MMA stopped. Count
    # it on its own -- the smaller sources must not be able to satisfy the
    # guard on ESPN's behalf.
    espn_events = scan_mma(now, end)
    events = espn_events + scan_one(now, end) + scan_boxing(now, end)

    if not espn_events:
        print("ERROR: ESPN returned no events; refusing to overwrite a good feed.",
              file=sys.stderr)
        return 1

    seen, deduped = set(), []
    for e in sorted(events, key=lambda e: e["date"]):
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        deduped.append(e)

    payload = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {
            "mma": sum(1 for e in deduped if e["sport"] == "mma"),
            "boxing": sum(1 for e in deduped if e["sport"] == "boxing"),
        },
        "events": deduped,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"Wrote {OUT} -- {len(deduped)} events "
          f"({payload['counts']['mma']} MMA, {payload['counts']['boxing']} boxing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
