#!/usr/bin/env python3
"""Build the existing static Cornerman feed from complementary public schedules.

ESPN and ONE are retained. Official UFC segments, the public US Fight Pass
catalogue and regional calendars supplement discovery. Stdlib only; unattended
GitHub Actions retain bounded last-good provider observations on failure.
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
import providers
from health import ProviderCache, write_json
from model import merge_events, instant, stamp

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "fights.json"
HORIZON_DAYS = 180

# ESPN's API rejects browser-shaped user agents with a 403 and serves
# self-identifying clients happily, so don't "fix" this by pretending to be
# Chrome -- that is the failure case, not the workaround.
UA_API = "Cornerman/1.0 (+https://github.com/forestgeeke-sudo/cornerman)"
UA_WEB = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# ESPN's MMA headshots are 600×436. Keep that ratio — a portrait box
# stretches them. Combiner is only for file size.
HEADSHOT = ("https://a.espncdn.com/combiner/i"
            "?img=/i/headshots/mma/players/full/{id}.png&w=350&h=254")


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

    for w in event_watch:
        w.update(confirmed=False, covered=False)

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

    raw_status = (ev.get('status') or comps[0].get('status') or {}).get('type') or {}
    status_name = raw_status.get('name', '').lower()
    status = ('cancelled' if 'cancel' in status_name else 'postponed' if 'postpon' in status_name
              else 'completed' if raw_status.get('completed') else 'scheduled')
    return {
        "id": f"{org.lower()}-{ev.get('id')}",
        "sport": "mma",
        "status": status,
        "org": org,
        "tier": classify_ufc(name) if org == "UFC" else "other",
        "name": name,
        "headline": headline,
        "date": ev.get("date"),
        "datePrecision": "time",
        "scheduledStart": ev.get("date"),
        "eventDay": ev.get("date", "")[:10],
        "segments": [],
        "coverageComplete": False,
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
        raise RuntimeError(f"ONE request failed: {type(e).__name__}") from e

    start, stop = page.find('id="upcoming"'), page.find('id="past"')
    if start < 0:
        raise ValueError("ONE page layout changed -- no upcoming section")
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
            "scheduledStart": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eventDay": when.strftime("%Y-%m-%d"),
            "segments": [],
            "coverageComplete": False,
            "venue": venue,
            "location": location,
            "watch": sources.resolve_all(
                ["YouTube"] if friday else ["Prime Video"]),
            "card": [],
            "art": None,
            "note": None,
            "link": href.split("?")[0],
        })
    for e in events:
        for w in e["watch"]:
            w.update(confirmed=False, covered=False)
    if not events:
        raise ValueError("ONE upcoming section contained no dated events")
    print(f"  ONE: {len(events)} events")
    return events


# --------------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=HORIZON_DAYS)
    print(f"Scanning {now:%Y-%m-%d} -> {end:%Y-%m-%d}")
    previous = json.loads(OUT.read_text()) if OUT.exists() else {}
    cache = ProviderCache(ROOT / 'scanner/state/providers.json', now, previous)
    events = []
    for i, (slug, org) in enumerate(ESPN_LEAGUES):
        if i: time.sleep(1.8)
        url=f'https://site.api.espn.com/apis/site/v2/sports/mma/{slug}/scoreboard?dates={now:%Y%m%d}-{end:%Y%m%d}'
        def read_espn(url=url, org=org):
            data=json.loads(fetch(url))
            if not isinstance(data.get('events'),list):raise ValueError('ESPN events array missing')
            if org in ('UFC','PFL') and not data['events']:raise ValueError('ESPN primary calendar unexpectedly empty')
            return [e for raw in data['events'] if (e:=parse_espn_event(raw,org)) and e.get('date')]
        events += cache.run('espn:'+slug,url,read_espn)
    events += cache.run('one',ONE_URL,lambda:scan_one(now,end))
    web=lambda url:fetch(url,ua=UA_WEB)
    calendars=[
      ('lfa','https://www.lfa.com/events/',lambda:providers.bounded(providers.parse_structured(web('https://www.lfa.com/events/'),'LFA','https://www.lfa.com/events/',now),now,end)),
      ('eternal','https://eternalmma.com/events/',lambda:providers.bounded(providers.parse_structured(web('https://eternalmma.com/events/'),'Eternal MMA','https://eternalmma.com/events/',now),now,end)),
      ('cage-warriors','https://cagewarriors.com/cage-warriors-events/',lambda:providers.fetch_cw(web,now,end)),
      ('lux','https://luxfightleague.com/eventos/',lambda:providers.fetch_lux(web,now,end)),
      ('fury','https://www.furyfc.tv/events',lambda:providers.bounded(providers.parse_fury(web('https://www.furyfc.tv/events'),now),now,end)),
      ('cffc','https://cffc.tv/tickets',lambda:providers.fetch_cffc(web,now,end)),
      ('bfl','https://battlefieldfl.com/bfl-event-type/upcoming-events/',lambda:providers.bounded(providers.parse_bfl(web('https://battlefieldfl.com/bfl-event-type/upcoming-events/'),now),now,end)),
      ('ufc-bjj','https://www.ufc.com/ufcbjj',lambda:providers.bounded(providers.parse_bjj(web('https://www.ufc.com/ufcbjj'),now),now,end)),
      ('fightpass',providers.FP_SITE+'/upcoming',lambda:providers.fetch_fightpass(web,now,end)),
      ('ufc',providers.UFC_INDEX,lambda:providers.scan_ufc(web,now,end)),
    ]
    for name,url,reader in calendars:events += cache.run(name,url,reader)
    deduped=merge_events(events,now)
    deduped=[e for e in deduped if e['date'][:10]<=end.date().isoformat()]
    if not deduped and previous.get('events') and not any(d['status']=='ok' for d in cache.diagnostics):
        print('ERROR: all providers failed; preserving last good feed',file=sys.stderr)
        return 1
    payload={'schemaVersion':2,'generated':stamp(now),'region':'US','timezone':'America/Chicago',
             'subscriptions':['Paramount+','UFC Fight Pass'],'freeServices':['YouTube'],
             'counts':{sport:sum(e['sport']==sport for e in deduped) for sport in sorted({e['sport'] for e in deduped})},
             'providers':cache.diagnostics,'events':deduped}
    cache.save()
    write_json(OUT,payload)
    checklist=['UFC','Cage Warriors','LFA','Fury Fighting Championship','CFFC','Lux Fight League',
               'Eternal MMA','UAE Warriors','Battlefield Fight League','Samourai MMA','UFC BJJ','UFC Fight Pass Invitational']
    orgs=sorted(set(checklist)|{e['org'] for e in deduped})
    coverage={'verifiedAt':stamp(now),'horizonDays':HORIZON_DAYS,'priorityDays':30,
              'providers':cache.diagnostics,'promotions':[]}
    for org in orgs:
        es=[e for e in deduped if e['org']==org]
        coverage['promotions'].append({'promotion':org,'events':len(es),
            'next30Days':sum(e['date'][:10]<=(now+timedelta(days=30)).date().isoformat() for e in es),
            'watchable':sum(e['availability'] in ('included','partial','free') for e in es),
            'unconfirmed':sum(e['availability']=='unconfirmed' for e in es),
            'sources':sorted({s['provider'] for e in es for s in e.get('sources',[])}),
            'gap':None if es else 'No upcoming listing verified by connected calendars; not proof of no events'})
    coverage['limitations']=[
      'Fight Pass publishes a rolling live catalogue, often shorter than 180 days; promotion calendars extend discovery.',
      'A normal subscription is verified from event-specific US guest purchase options; PPV is never included.',
      'ONE legacy watch chips remain unconfirmed until event-specific US segment evidence is available.',
      'Samourai discovery currently relies on the Fight Pass catalogue; no independent live calendar adapter.',
      'Cage Warriors front-end blocks automated requests; official WordPress REST fallback is monitored.',
      'Venue first-bell times are scheduledStart, not verified broadcast starts.',
      'No schedule can prove completeness. Failed observations expire after 7 days, rights after 3 days, omitted listings after 48 hours.'
    ]
    write_json(ROOT/'docs/coverage.json',coverage)
    print(f'Wrote {OUT}: {len(deduped)} events')
    return 0


if __name__ == "__main__":
    sys.exit(main())
