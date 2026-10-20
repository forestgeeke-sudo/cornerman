#!/usr/bin/env python3
"""Daily digest + UFC eve / imminent alerts, with durable at-most-once reservations.

ntfy has no idempotency key. A reserved/pending delivery after a crash or ambiguous
HTTP outcome is intentionally NOT retried. Explicit HTTP rejections are retryable.
--git-state pushes each reservation before sending; never send after failed push.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scanner.digest import APP_URL, build_digest, event_day, event_text, fresh_event, split_message
from scanner.model import TZ, instant

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / 'docs/fights.json'
STATE = ROOT / 'scanner/state/notified.json'
WINDOW = timedelta(minutes=70)


def utc_now():
    raw = os.environ.get('CORNERMAN_NOW')
    result = instant(raw) if raw else datetime.now(timezone.utc)
    if result is None:
        raise ValueError('CORNERMAN_NOW requires an aware ISO timestamp')
    return result


def morning(now):
    raw = os.environ.get('CORNERMAN_DIGEST_TIME', '09:00')
    parsed = time.fromisoformat(raw)
    if len(raw) != 5 or parsed.tzinfo:
        raise ValueError('CORNERMAN_DIGEST_TIME must be HH:MM')
    return datetime.combine(now.astimezone(TZ).date(), parsed, tzinfo=TZ)


def plan(feed, now):
    jobs = []
    due = morning(now)
    if due <= now + WINDOW:
        message = build_digest(feed.get('events', []), max(now, due))
        parts = split_message(message)
        for i, body in enumerate(parts, 1):
            jobs.append({'key': f'digest:{due.date()}:{i}', 'title': f'Cornerman morning — {due.date()} ({i}/{len(parts)})',
                         'body': body, 'at': due.isoformat(), 'priority': 'default'})
    for raw in feed.get('events', []):
        e = fresh_event(raw, now)
        if e.get('org') != 'UFC' or e.get('tier') not in ('numbered', 'fight_night') or e.get('status') in ('cancelled', 'postponed', 'completed', 'final'):
            continue
        day = event_day(e)
        first = instant(e.get('earliestBroadcastStart'))
        if first:
            day = first.astimezone(TZ).date()
        if not day:
            continue
        eve = datetime.combine(day - timedelta(days=1), time(int(os.environ.get('CORNERMAN_EVE_HOUR', '12'))), tzinfo=TZ)
        times = [('eve', eve, 'Tomorrow: ', 'default')]
        if first:
            times.append(('imminent', first - timedelta(minutes=int(os.environ.get('CORNERMAN_IMMINENT_MINUTES', '90'))), 'Starting soon: ', 'high'))
        for kind, at, prefix, priority in times:
            # No stale catch-up after the local day or after the broadcast starts.
            if at > now + WINDOW or (at < now and at.astimezone(TZ).date() != now.astimezone(TZ).date()) or first and first <= now:
                continue
            current = fresh_event(raw, max(now, at))
            if kind == 'imminent' and not current.get('earliestBroadcastStart'):
                continue
            bodies = split_message(event_text(current) + '\n' + APP_URL)
            for i, body in enumerate(bodies, 1):
                suffix = '' if i == 1 else f':part{i}'
                jobs.append({'key': f"{e['id']}:{kind}{suffix}", 'title': prefix + e['name'], 'body': body, 'at': at.isoformat(), 'priority': priority})
    return jobs


def freeze_digest(state, jobs, now):
    """Once reserved, a local day's digest payload and part count stay immutable."""
    day = now.astimezone(TZ).date().isoformat()
    digests = [j for j in jobs if j['key'].startswith('digest:')]
    if not digests:
        return jobs
    frozen = state.setdefault('digests', {}).setdefault(day, digests)
    return frozen + [j for j in jobs if not j['key'].startswith('digest:')]


def load_state(path=STATE):
    if not path.exists():
        return {'version': 2, 'deliveries': {}}
    state = json.loads(path.read_text())  # Corrupt state must fail closed, never reset dedupe.
    if state.get('version') == 2:
        if not isinstance(state.get('deliveries'), dict):
            raise ValueError('Invalid delivery state')
        return state
    return {'version': 2, 'deliveries': {key: {'status': 'sent', 'updated': val} for key, val in state.items()}}


def prune_state(state, now):
    """Keep 45 days of outcomes/snapshots; never discard ambiguous reservations."""
    cutoff = now - timedelta(days=45)
    old = [key for key, item in state['deliveries'].items()
           if item.get('status') in ('sent', 'retryable')
           and instant(item.get('updated')) and instant(item['updated']) < cutoff]
    for key in old:
        del state['deliveries'][key]
    snapshots = state.get('digests', {})
    expired = []
    for day in snapshots:
        try:
            if datetime.fromisoformat(day).date() < cutoff.astimezone(TZ).date():
                expired.append(day)
        except ValueError:
            continue
    for day in expired:
        del snapshots[day]
    return bool(old or expired)


def save_state(state, path=STATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as out:
        json.dump(state, out, indent=2, sort_keys=True)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
        name = out.name
    os.replace(name, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def locked(path=STATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def git_save():
    """Serialized workflows check out current main; a failed push forbids delivery."""
    rel = str(STATE.relative_to(ROOT))
    subprocess.run(['git', 'add', rel], cwd=ROOT, check=True)
    if subprocess.run(['git', 'diff', '--cached', '--quiet', '--', rel], cwd=ROOT).returncode == 0:
        return
    subprocess.run(['git', 'commit', '-m', 'Record Cornerman notification delivery state', '--', rel], cwd=ROOT, check=True)
    # A failed response may still mean the push succeeded. Repeating the same push is safe.
    for _ in range(3):
        if subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=ROOT).returncode == 0:
            return
    raise RuntimeError('State push failed; no further notifications sent')


def push(url, job, now, test=False):
    headers = {'Title': ('[Test] ' if test else '') + job['title'], 'Tags': 'boxing_glove',
               'Priority': job['priority'], 'Click': APP_URL,
               'Content-Type': 'text/plain; charset=utf-8'}
    at = instant(job['at'])
    if not test and at and at > now:
        headers['Delay'] = str(int(at.timestamp()))
    # HTTP headers are latin-1; ntfy supports RFC 2047 UTF-8 titles.
    from email.header import Header
    headers['Title'] = Header(headers['Title'], 'utf-8', maxlinelen=100000).encode()
    request = urllib.request.Request(url, data=job['body'].encode(), headers=headers, method='POST')
    with urllib.request.urlopen(request, timeout=25) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f'Unexpected HTTP status {response.status}')


def deliver(jobs, state, url, now, persist, sender=push):
    errors = 0
    for job in jobs:
        key = job['key']
        old = state['deliveries'].get(key, {})
        if old.get('status') in ('sent', 'pending', 'reserved'):
            continue
        # Persist the exact multipart payload; changed feeds cannot alter retries.
        item = old if old.get('job') else {'job': job}
        job = item['job']
        item.update(status='pending', updated=now.isoformat())
        state['deliveries'][key] = item
        persist(state)  # MUST be durable remotely before network I/O in production.
        try:
            sender(url, job, now)
        except urllib.error.HTTPError as exc:
            # A gateway/server error can occur after acceptance, so it is ambiguous.
            item.update(status='retryable' if exc.code in (400, 401, 403, 404, 405, 413, 415, 422, 429) else 'pending', error=f'HTTP {exc.code}')
            exc.close()
            errors += 1
        except (OSError, RuntimeError) as exc:
            item.update(status='pending', error=f'Ambiguous delivery: {type(exc).__name__}')
            errors += 1
        else:
            item.update(status='sent')
            item.pop('error', None)
        persist(state)
        print(f"{key}: {item['status']}")
    return 1 if errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run', 'dry-run', 'test'], nargs='?', default='dry-run')
    parser.add_argument('--git-state', action='store_true')
    args = parser.parse_args(argv)
    now = utc_now()
    feed = json.loads(FEED.read_text())
    jobs = plan(feed, now)
    if args.mode == 'dry-run':
        print(json.dumps(jobs, indent=2, ensure_ascii=False))
        return 0
    url = os.environ.get('NTFY_URL', '').strip()
    if not url:
        raise ValueError('NTFY_URL is required for sending')
    if args.mode == 'test':
        message = build_digest(feed.get('events', []), now)
        for i, body in enumerate(split_message(message), 1):
            push(url, {'title': f'Cornerman digest part {i}', 'body': body, 'priority': 'default', 'at': now.isoformat()}, now, test=True)
        return 0
    with locked():
        state = load_state()
        jobs = freeze_digest(state, jobs, now)
        # Finish definitely rejected parts even if the calendar feed has since changed.
        keys = {j['key'] for j in jobs}
        for key, item in state['deliveries'].items():
            if item.get('status') == 'retryable' and key not in keys and item.get('job'):
                # Do not deliver old alerts on later local dates.
                at = instant(item['job']['at'])
                if at and at.astimezone(TZ).date() == now.astimezone(TZ).date():
                    jobs.append(item['job'])
        def persist(value):
            save_state(value)
            if args.git_state:
                git_save()
        if prune_state(state, now):
            persist(state)
        return deliver(jobs, state, url, now, persist)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
