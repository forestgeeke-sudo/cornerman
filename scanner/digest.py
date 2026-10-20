"""Deterministic, spoiler-free calendar digest; no guesses about broadcast times."""
from datetime import date, datetime, time, timedelta, timezone
from .model import TZ, access, instant

APP_URL = 'https://forestgeeke-sudo.github.io/cornerman/'
LIMIT = 4096


def event_day(event):
    try:
        return date.fromisoformat((event.get('eventDay') or event.get('date', ''))[:10])
    except (TypeError, ValueError):
        return None


def start(event):
    return instant(event.get('earliestBroadcastStart')) or instant(event.get('scheduledStart')) or instant(event.get('date'))


def select_events(events, at):
    """All starts in the inclusive next 48h, supplemented to the next five overall.

    Date-only events intersect the window by local calendar day, never by an invented start.
    """
    at = at.astimezone(TZ)
    end = (at.astimezone(timezone.utc) + timedelta(hours=48)).astimezone(TZ)
    upcoming = []
    for e in events:
        if e.get('status') in ('cancelled', 'postponed', 'completed', 'final'):
            continue
        moment, day = start(e), event_day(e)
        if moment:
            if moment < at:
                continue
            key = moment
            near = moment <= end
        elif day:
            if day < at.date():
                continue
            key = datetime.combine(day, time.min, tzinfo=TZ)
            near = day <= end.date()
        else:
            continue
        upcoming.append((key, str(e.get('id', '')), e, near))
    upcoming.sort(key=lambda x: (x[0], x[1]))
    selected = {i for i, item in enumerate(upcoming) if item[3]}
    for i in range(len(upcoming)):
        if len(selected) >= 5:
            break
        selected.add(i)
    return [item[2] for i, item in enumerate(upcoming) if i in selected]


def clock(value):
    return value.astimezone(TZ).strftime('%a %b %d, %-I:%M %p %Z')


def event_text(e):
    lines = [e.get('name', 'Unnamed event')]
    broadcast = instant(e.get('earliestBroadcastStart'))
    scheduled = instant(e.get('scheduledStart')) or instant(e.get('date'))
    if broadcast:
        lines.append('First broadcast: ' + clock(broadcast))
    elif scheduled:
        lines.append('Scheduled: ' + clock(scheduled) + '; broadcast time unconfirmed')
    else:
        lines.append(f"{event_day(e)} — time unconfirmed")
    main = instant(e.get('mainCardStart'))
    if main:
        lines.append('Main card: ' + clock(main))
    labels = {'included': 'Included in your subscriptions', 'partial': 'Partly included; check segments',
              'free': 'Free viewing confirmed', 'other_service': 'Other service / separate payment',
              'unconfirmed': 'Viewing access unconfirmed'}
    lines.append(labels.get(e.get('availability'), labels['unconfirmed']))
    for s in e.get('segments', []):
        platforms = []
        for p in s.get('platforms', []):
            state = ('unconfirmed' if s.get('stale') or not p.get('confirmed') else
                     'included' if p.get('covered') and p.get('access') == 'subscription' else
                     'free' if p.get('access') == 'free' else 'separate payment')
            platforms.append(f"{p.get('name', 'Unknown service')} ({state})")
        moment = instant(s.get('start')) if not s.get('stale') else None
        lines.append(f"{s.get('name', 'Segment')}: " + (clock(moment) if moment else 'time unconfirmed')
                     + ' — ' + (', '.join(platforms) or 'service unconfirmed'))
    return '\n'.join(lines)


def fresh_event(event, at):
    """Recheck rights at generation time; a legacy timestamp is only a schedule."""
    value = dict(event)
    if not value.get('scheduledStart') and instant(value.get('date')):
        value['scheduledStart'] = value['date']
    return access(value, at)


def build_digest(events, at):
    chosen = select_events([fresh_event(e, at) for e in events], at)
    heading = f"Cornerman — {at.astimezone(TZ):%A, %B %d}\nAll events in the next 48 hours; at least the next five when available."
    blocks = [f'{i}. {event_text(e)}' for i, e in enumerate(chosen, 1)]
    return '\n\n'.join([heading] + (blocks or ['No upcoming events found.']) + [APP_URL])


def split_message(message, limit=LIMIT):
    """Lossless UTF-8 split, preferring line boundaries; never exceeds ntfy's byte cap."""
    parts, current = [], ''
    for line in message.splitlines(keepends=True):
        if current and len((current + line).encode()) > limit:
            parts.append(current)
            current = ''
        for char in line:
            if len((current + char).encode()) > limit:
                parts.append(current)
                current = ''
            current += char
    if current:
        parts.append(current)
    return parts or ['']
