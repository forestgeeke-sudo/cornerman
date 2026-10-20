"""Event identity, evidence and US subscription access. No promotion-level rights."""
import copy
import hashlib
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SUBSCRIPTIONS = {'Paramount+', 'UFC Fight Pass'}
TZ = ZoneInfo('America/Chicago')
RIGHTS_TTL = timedelta(days=3)


def instant(value):
    if not value or len(value) <= 10:
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, TypeError):
        return None


def stamp(d):
    return d.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def identity(e):
    """Numbered identities survive date/opponent changes; unnumbered use day."""
    org = e['org'].lower()
    name = e['name'].lower()
    aliases = {'cage warriors': r'(?:cage warriors|cw)\s*(\d+)',
               'eternal mma': r'eternal(?: mma)?\s*(\d+)',
               'ufc bjj': r'ufc bjj\s*(\d+)',
               'ufc fight pass invitational': r'(?:ufc )?fight pass invitational\s*(\d+)',
               'ufc': r'\bufc\s+(\d+)\b', 'lfa': r'\blfa\s*(\d+)',
               'cffc': r'\bcffc\s*(\d+)', 'lux fight league': r'\blux\s*0*(\d+)',
               'uae warriors': r'uae warriors\s*(\d+)',
               'battlefield fight league': r'\bbfl\s*(\d+)'}
    pattern = aliases.get(org)
    m = re.search(pattern, name) if pattern else None
    if m:
        return org, str(int(m[1]))
    normalized = re.sub(r'[^a-z0-9]', '', name.split(':')[0])
    # UFC fight nights from ESPN and UFC use different subtitles/numbers.
    if org == 'ufc' and 'fight night' in name:
        normalized = 'fightnight'
    return org, normalized, e.get('eventDay', e.get('date', '')[:10])


def new_event(name, org, day, url, sport='mma'):
    slug = re.sub('[^a-z0-9]+', '-', name.lower()).strip('-')
    return {'id': f'{slug}-{hashlib.sha256(url.encode()).hexdigest()[:8]}',
            'name': name, 'org': org, 'sport': sport, 'tier': 'other',
            'headline': name, 'date': day[:10], 'eventDay': day[:10],
            'datePrecision': 'day', 'scheduledStart': None,
            'earliestBroadcastStart': None, 'mainCardStart': None,
            'segments': [], 'coverageComplete': False, 'watch': [],
            'card': [], 'art': None, 'venue': None, 'location': None,
            'link': url, 'note': None, 'status': 'scheduled'}


def segment(name, start, platforms, url, verified, complete=False):
    """platforms are already resolved service objects with event-specific evidence."""
    return {'name': name, 'start': start, 'platforms': platforms,
            'sourceUrl': url, 'verifiedAt': stamp(verified),
            'region': 'US', 'complete': complete}


def access(e, now):
    e = copy.deepcopy(e)
    segments = e.setdefault('segments', [])
    all_watch = {}
    for s in segments:
        verified = instant(s.get('verifiedAt'))
        fresh = bool(verified and now - verified <= RIGHTS_TTL and s.get('region') == 'US')
        s['stale'] = not fresh
        for p in s.get('platforms', []):
            pv = instant(p.get('verifiedAt')) if p.get('verifiedAt') else verified
            p_fresh = bool(pv and now - pv <= RIGHTS_TTL)
            confirmed = fresh and p_fresh and p.get('access') in ('subscription', 'free', 'paid', 'ppv')
            p['covered'] = bool(confirmed and p.get('kind') != 'ppv' and (
                p.get('access') == 'subscription' and p['name'] in SUBSCRIPTIONS
                or p.get('access') == 'free' and p['name'] in SUBSCRIPTIONS | {'YouTube'}))
            p['confirmed'] = confirmed
            all_watch[p['name']] = p
        s['covered'] = any(p['covered'] for p in s.get('platforms', []))
        s['subscriptionCovered'] = any(p['covered'] and p['name'] in SUBSCRIPTIONS
                                       for p in s.get('platforms', []))
    # Unverified legacy watch chips remain discoverable but cannot imply access.
    e['watch'] = list(all_watch.values()) if segments else e.get('watch', [])
    covered = [s for s in segments if s['covered']]
    fully = bool(segments and e.get('coverageComplete') and len(covered) == len(segments))
    if fully:
        e['availability'] = 'included' if any(s['subscriptionCovered'] for s in covered) else 'free'
    elif covered:
        e['availability'] = 'partial'
    elif any(p.get('confirmed') for s in segments for p in s.get('platforms', [])):
        e['availability'] = 'other_service'
    else:
        e['availability'] = 'unconfirmed'
    starts = [s['start'] for s in segments if instant(s.get('start')) and not s['stale']]
    e['earliestBroadcastStart'] = min(starts, key=instant) if starts else None
    e['mainCardStart'] = next((s.get('start') for s in segments
                               if s['name'] == 'Main card' and not s['stale']), None)
    if e['earliestBroadcastStart']:
        e['date'] = e['earliestBroadcastStart']
        e['datePrecision'] = 'time'
    elif e.get('scheduledStart'):
        e['date'] = e['scheduledStart']
        e['datePrecision'] = 'time'
    else:
        e['date'] = e.get('eventDay', e['date'][:10])
        e['datePrecision'] = 'day'
    return e


def merge_events(events, now):
    """Provider order is precedence (ESPN first, official event pages last)."""
    merged = {}
    ids = {}
    cancelled = set()
    for incoming in events:
        e = copy.deepcopy(incoming)
        key = ids.get(e['id'], identity(e))
        ids[e['id']] = key
        if e.get('status') in ('cancelled','postponed','completed'):
            cancelled.add(key)
        elif e.get('status') == 'rescheduled':
            cancelled.discard(key)
        if key not in merged:
            merged[key] = e
            continue
        old = merged[key]
        # Keep IDs/artwork/bouts for existing calendar links and full-card UI.
        for field in ('card', 'art'):
            if old.get(field) and not e.get(field):
                e[field] = old[field]
        old_id = old['id']
        if e.get('segments') and old.get('segments'):
            # Two event-specific sources may carry the same segment. Preserve
            # both services only when their segment times agree, carrying each
            # platform's own evidence time so cache retention cannot renew it.
            for new_seg in e['segments']:
                same = next((s for s in old['segments'] if s['name']==new_seg['name']
                             and s.get('start') and s.get('start')==new_seg.get('start')),None)
                if same:
                    ps={p['name']:p for p in new_seg.get('platforms',[])}
                    for p in same.get('platforms',[]):
                        if p['name'] not in ps:
                            q=copy.deepcopy(p)
                            q.setdefault('verifiedAt',same.get('verifiedAt'))
                            q.setdefault('sourceUrl',same.get('sourceUrl'))
                            ps[p['name']]=q
                    new_seg['platforms']=list(ps.values())
        if not e.get('segments') and old.get('segments'):
            e['segments'] = old['segments']
            e['coverageComplete'] = old.get('coverageComplete', False)
        if not e.get('scheduledStart') and old.get('scheduledStart'):
            e['scheduledStart'] = old['scheduledStart']
        evidence = {v['provider']: v for v in old.get('sources', [])}
        evidence.update({v['provider']: v for v in e.get('sources', [])})
        old.update({k: v for k, v in e.items() if v is not None})
        old['id'] = old_id
        old['sources'] = list(evidence.values())
    result = []
    for key,e in merged.items():
        if key in cancelled:continue
        e = access(e, now)
        d = instant(e['date'])
        if e.get('status') in ('cancelled', 'postponed'):
            continue
        if d and d + timedelta(hours=8) < now:
            continue
        if not d and e['date'][:10] < (now.astimezone(TZ) - timedelta(days=1)).date().isoformat():
            continue
        result.append(e)
    return sorted(result, key=lambda e: e['date'])
