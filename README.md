# Cornerman

Upcoming MMA and boxing cards, and where to watch them.

The scanning happens on GitHub's servers, not on your machine. Your computer
being asleep, off, or in another country changes nothing — when you open the
app, the schedule is already current.

## How it fits together

```
GitHub Actions (every 6h)          your desktop
┌──────────────────────┐           ┌──────────────────┐
│ scanner/scan.py      │           │ Cornerman window │
│  ESPN  → MMA         │  writes   │  reads           │
│  boxing-schedule.com │ ────────► │  fights.json     │
└──────────────────────┘           └──────────────────┘
         │                          (works offline from
         │ hourly                    the last good copy)
         ▼
scanner/notify.py → ntfy → your phone
```

Nothing here needs a server, a database, or a paid API key.

## What gets scanned

| Source | Covers | Notes |
|---|---|---|
| ESPN public schedule feed | UFC, PFL, Bellator | Full bout order, weight classes, broadcaster |
| ESPN `other` bucket | Road to UFC, Super RIZIN | Real cards with no dedicated feed; ESPN labels them only "Other" with no broadcaster, so `sources.PROMOTIONS` names the promotion and its service |
| Wikipedia | ONE Championship | ESPN carries no ONE feed at all; ONE is exclusive to Prime Video in the US |
| boxing-schedule.com | Boxing | Date, matchup, venue, broadcaster |

All 48 MMA leagues ESPN tracks were probed: only `ufc`, `pfl` and `other` have
any forward schedule. Cage Warriors, KSW, LFA, RIZIN and Bellator have
dedicated ESPN feeds that are **empty** — kept in `PROMOTIONS` so they resolve
if they ever reappear, but don't expect data from those slugs.

**ONE's dates need care.** ONE's Bangkok cards run in the local morning to hit
US prime time, so the announced local date is a day *ahead* of the US airing.
There's no reliable start time in the source, so those events carry a `note`
saying so rather than having their date silently shifted.

Only factual schedule data is taken: dates, fighters, venues, broadcasters.
Affiliate links in the boxing source are discarded — "where to watch" links
come from `scanner/sources.py`, which maps a broadcaster name to its real site.

**Heads up on user agents.** ESPN's API returns `403` to browser-shaped user
agents and serves self-identifying clients fine. `UA_API` in `scan.py` is
deliberately not pretending to be Chrome. That is also why the browser can't
call ESPN directly and the Actions middle layer genuinely has to exist.

## Phone alerts

Scoped narrowly on purpose — only **UFC numbered cards and the weekly Fight
Night** push to your phone. Contender Series, PFL and all boxing appear in the
app but never buzz you.

Two alerts per qualifying card: one on the morning of, one shortly before the
main event walks. `scanner/state/notified.json` stops repeats.

### Turning alerts on

In the repo's **Settings → Secrets and variables → Actions**:

| Kind | Name | Value |
|---|---|---|
| Secret | `NTFY_URL` | your ntfy topic URL |
| Variable | `NTFY_CONFIGURED` | `true` |
| Variable | `CORNERMAN_TZ` | `America/Chicago` (optional) |

Until `NTFY_CONFIGURED` is `true` the hourly job doesn't run at all. To test
without sending anything, use **Actions → Fight alerts → Run workflow** with
*dry run* left ticked.

## Installing the desktop app

```bash
./install-desktop.sh https://<you>.github.io/cornerman/
```

That drops a launcher and icon into your app menu. It opens in its own window
with no tab strip or URL bar. The same URL works on your phone.

## Running the scanner by hand

```bash
python3 scanner/scan.py                     # rebuild docs/fights.json
CORNERMAN_DRY_RUN=1 NTFY_URL=... python3 scanner/notify.py
```

Stdlib only — there is nothing to install.

## When something breaks

**Feed banner says the scanner is stuck.** Check the Actions tab. A scan that
finds zero MMA events aborts rather than overwriting a good feed with an empty
one, so a failed run leaves yesterday's data in place.

**Boxing disappears but MMA is fine.** `boxing-schedule.com` changed its
markup. The parser looks for `events__single` blocks in `scan_boxing()`. MMA is
unaffected because it comes from a real API.

**Alerts stop.** GitHub disables scheduled workflows on repos with no commits
for 60 days. This one commits every few hours, so that shouldn't trigger — but
it's the first thing to check.
