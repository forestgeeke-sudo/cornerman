#!/usr/bin/env python3
"""Push fight-day alerts to a phone via ntfy.

Deliberately narrow: only UFC numbered cards and the weekly Fight Night get
through. Everything else -- Contender Series, PFL, all boxing -- still shows up
in the app but never buzzes a phone.

Two alerts per qualifying card:
  day-of   on the morning of the event
  imminent shortly before the main event walks

A small state file stops the hourly job from sending the same alert twice.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "docs" / "fights.json"
STATE = Path(__file__).resolve().parent / "state" / "notified.json"

NOTIFY_TIERS = {"numbered", "fight_night"}
LOCAL_TZ = ZoneInfo(os.environ.get("CORNERMAN_TZ", "America/Chicago"))
MORNING_HOUR = int(os.environ.get("CORNERMAN_MORNING_HOUR", "9"))
IMMINENT_MINUTES = int(os.environ.get("CORNERMAN_IMMINENT_MINUTES", "90"))

# Keys older than this are dropped so the state file can't grow forever.
STATE_TTL_DAYS = 30


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STATE_TTL_DAYS)).isoformat()
    pruned = {k: v for k, v in state.items() if v >= cutoff}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(pruned, indent=1, sort_keys=True) + "\n")


def push(url, title, body, tags, priority="default", click=None):
    headers = {
        "Title": title,
        "Tags": tags,
        "Priority": priority,
    }
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def main():
    ntfy = os.environ.get("NTFY_URL", "").strip()
    if not ntfy:
        print("NTFY_URL not set -- nothing to notify.", file=sys.stderr)
        return 0

    dry = os.environ.get("CORNERMAN_DRY_RUN") == "1"

    try:
        feed = json.loads(FEED.read_text())
    except (OSError, ValueError) as e:
        print(f"ERROR: cannot read feed: {e}", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    local_now = now.astimezone(LOCAL_TZ)
    state = load_state()
    sent = 0

    for e in feed.get("events", []):
        if e.get("org") != "UFC" or e.get("tier") not in NOTIFY_TIERS:
            continue

        try:
            start = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue

        local_start = start.astimezone(LOCAL_TZ)
        mins_out = (start - now).total_seconds() / 60
        watch = ", ".join(w["name"] for w in e.get("watch") or []) or "Not announced"
        main_event = (e["card"][0]["fighters"] if e.get("card") else None)
        bout = " vs ".join(main_event) if main_event else e.get("headline", "")
        where = ", ".join(x for x in (e.get("venue"), e.get("location")) if x)

        alerts = []

        # Morning of, once the local clock passes the morning hour.
        if (local_start.date() == local_now.date()
                and local_now.hour >= MORNING_HOUR
                and mins_out > 0):
            alerts.append((
                "dayof",
                f"Fight day: {e['name']}",
                f"{bout}\n"
                f"Main event {local_start:%-I:%M %p %Z}\n"
                f"Watch on {watch}"
                + (f"\n{where}" if where else ""),
                "boxing_glove,calendar",
                "default",
            ))

        # Shortly before the walk.
        if 0 < mins_out <= IMMINENT_MINUTES:
            alerts.append((
                "imminent",
                f"Starting soon: {bout}",
                f"{e['name']} — main event in about {int(mins_out)} min\n"
                f"Watch on {watch}",
                "boxing_glove,alarm_clock",
                "high",
            ))

        for kind, title, body, tags, prio in alerts:
            key = f"{e['id']}:{kind}"
            if key in state:
                continue
            if dry:
                print(f"[dry-run] would send {key}: {title} | {body.splitlines()[0]}")
            else:
                try:
                    push(ntfy, title, body, tags, prio,
                         click=(e.get("watch") or [{}])[0].get("url"))
                    print(f"sent {key}: {title}")
                except urllib.error.URLError as err:
                    print(f"WARN: push failed for {key}: {err}", file=sys.stderr)
                    continue
            state[key] = now.isoformat()
            sent += 1

    if not dry:
        save_state(state)
    print(f"{sent} alert(s) {'simulated' if dry else 'sent'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
