# Cornerman

Personal combat-sports schedule for the United States, shown in **America/Chicago**.
The original poster design, fighter artwork, full fight cards, search, Google Calendar
links, offline app and ESPN/ONE coverage remain. The default view shows **all events**.

The scanner and alerts run on GitHub; no home computer needs to stay awake. Python
3.12+ standard library and plain JavaScript; no database, framework, paid data API
or LLM is required.

## Coverage and evidence

The horizon remains 180 days. Fight Pass's rolling catalogue is usually shorter;
promotion calendars supplement it. The next 30 days are the priority, not a claim
of completeness. See the automatically generated [coverage report](docs/coverage.json)
and the dated [verification report](VERIFICATION.md).

| Source | Purpose / limits |
|---|---|
| ESPN UFC, PFL, Bellator and `other` scoreboards | Existing discovery, bout order, fighters and artwork; empty regional feeds do not establish absence |
| ONE's official events calendar | Existing numbered, Friday Fights and other cards; generic YouTube/Prime suggestions remain **unconfirmed** without US event-specific evidence |
| UFC official upcoming calendar and event pages | Early prelims, prelims, main card, actual Unix timestamps and individual broadcaster links; supports both published page layouts |
| UFC Fight Pass public guest live schedule | Paginated live events across promotions and disciplines, language duplicates merged; filters out press conferences, weigh-ins and studio shows |
| Cage Warriors official WordPress REST calendar | Dated events; front-end bot blocking fallback. Calendar's general Fight Pass partnership is never applied to every event |
| LFA / Eternal official structured event calendars | Upcoming regional cards. All-day midnight placeholders are dates, not broadcast times |
| Fury official event sections | Segment times and their own watch links; currently includes separate OnlyFans prelims / Fight Pass main cards |
| CFFC official ticket calendar and event descriptions | Dated events and first-bell schedule; venue times alone do not verify stream availability |
| Battlefield official upcoming calendar | Event-specific Fight Pass main-card confirmation, unknown time kept unknown |
| Lux official calendar and countdown | Upcoming event schedule; a countdown does not establish a broadcaster |
| UFC BJJ official calendar | Additional numbered grappling cards; excludes registration-only local tournaments |

Fight Pass currently supplies additional verified live listings for UAE Warriors,
Samourai MMA, Combat FC, Tuff-N-Uff, INKA MMA, ARES, Anthony Pettis FC, WOW and
other promotions **when they appear in its live catalogue**. Promotion names do
not grant streaming rights. LFA's published US listings currently name VICE TV /
FloCombat, not an included Fight Pass subscription. Future CFFC, Lux and other
cards may have dates but unannounced viewing access. Fight Pass Invitational,
kickboxing and Muay Thai are supported when a dated sporting event is published;
no future event is invented when the source has none.

The Fight Pass adapter discovers the public web-client key and creates a normal
guest session, as its website does. It uses no subscriber login, stores no token
or public-client key, checks the server's guest market is **US**, and accepts
only event-specific normal Fight Pass subscription plans. An unrecognized plan
stays unconfirmed. PPV is never marked included. A non-US runner records a failed
provider rather than applying another region's rights.

## Viewing metadata

Configured services are Paramount+ and UFC Fight Pass subscriptions, plus verified
free YouTube content. Other services remain visible without an assumed subscription.
Event availability is `included`, `partial`, `free`, `other_service` or `unconfirmed`.
The optional **I can watch** checkbox includes full, partial and free access;
category filtering organizes the broader catalogue. Both filters default to off/all.

One event holds multiple `segments`, each with a name, nullable `start`, platforms,
`sourceUrl`, `verifiedAt`, US region and subscription coverage. Platforms have
`name`, `url`, `kind`, `access`, `confirmed` and `covered`; supplemental sources may
also carry platform-level provenance. A partial-card listing does not establish
complete coverage. Separate sources for a segment retain both platforms when their
published start times agree. Official UFC event pages take precedence for timing.

- `earliestBroadcastStart`: earliest verified segment viewing start.
- `mainCardStart`: verified start of the main card, when published.
- `scheduledStart`: generic calendar / first-bell time; broadcast unconfirmed.
- `eventDay`: published event date when an exact instant is unavailable.
- `date` / `datePrecision`: backward-compatible display fields derived from these.

There is no promised headlining-fight start time. Google Calendar uses the first
verified broadcast, or explicitly labeled scheduled time, and an all-day entry
when time is unknown. Expand **Viewing breakdown** for sources, verification dates,
per-segment times and access. **Full card** still expands individual bouts.

## Reliability

Scans run every six hours. The hourly notification clock also refreshes the feed
when it is six hours old, covering unreliable scheduled scan triggers. All writers
share `cornerman-write` workflow concurrency and check out current main after queuing.

`scanner/state/providers.json` persists each provider's last good observations.
A provider failure retains observations for at most seven days; omitted events
on a healthy calendar expire after 48 hours. Explicit cancellations/postponements
are excluded, numbered identities survive rescheduling, and old events expire.
Viewing rights become unconfirmed after 72 hours, independently of cache retention;
the app and notification generator recheck freshness even when offline. JSON writes
are atomic. A corrupt state file fails visibly rather than resetting deduplication.

`docs/coverage.json` records each provider's attempt, last success, failures,
retained observations, promotion counts and gaps. The UI warns about failed or
degraded providers even if other providers refreshed successfully. A source layout
change must fail a parser contract, not masquerade as an empty event calendar.

## Morning digest and existing UFC alerts

At **09:00 America/Chicago**, the deterministic digest includes every event
starting in the next 48 hours and supplements to approximately the next five
when fewer are near. Date-only events intersecting the window are included with
time unconfirmed. It sorts chronologically, labels included/partial access and
lists segment platforms. It never uses scores, results or winners. No upcoming
confirmed events still produces a concise message.

Long messages are split losslessly into numbered ntfy parts, each under the
4,096-byte limit, preserving every event; each notification opens Cornerman.
UFC numbered / Fight Night eve and imminent alerts remain; the redundant UFC
morning alert is replaced by the digest. Imminent means the first verified
broadcast is approaching, not that a headliner is about to walk out.

### Configuration

Existing Cornerman Actions settings are reused:

| Kind | Name | Value |
|---|---|---|
| Secret | `NTFY_URL` | Existing complete ntfy topic URL; never copy it to another repo |
| Variable | `NTFY_CONFIGURED` | `true` enables the backup schedule |
| Variable | `CORNERMAN_DIGEST_TIME` | Optional `HH:MM`, default `09:00` in America/Chicago |

The viewing region and timezone are deliberately US / America/Chicago throughout
this personal app. The older `CORNERMAN_TZ` variable need not be changed.
`CORNERMAN_EVE_HOUR` (default 12) and `CORNERMAN_IMMINENT_MINUTES` (default 90)
are optional notifier environment settings. No voice alert marker is added.

### Use the existing Alert clock

The companion change in `forestgeeke-sudo/alert-maker` adds
`engine/cornerman.py` to the existing `engine/alert.py tick`. Every hourly clock
tick dispatches Cornerman's `notify.yml` with `mode=run`, using the routine's
existing GitHub authorization. Cornerman alone owns its ntfy secret and state.
A dispatch failure is reported without preventing other Alert Maker alerts.
GitHub's hourly cron remains a best-effort backup.

Deploy Cornerman before the Alert Maker clock change. If the current **Alert clock**
routine already reads current main and its GitHub connection can access both
repositories, its existing `python3 engine/alert.py tick` command needs no change.
Otherwise use the existing Alert Maker cloud environment and this prompt, hourly
at **:03** (a lightweight Claude model is sufficient):

> In forestgeeke-sudo/alert-maker, read the latest main branch and run
> `python3 engine/alert.py tick`. It dispatches due alerts and Cornerman's
> notification pass. Report command/dispatch failures. Do not send a separate
> Cornerman message, call an LLM to interpret event dates or streaming rights,
> edit event data, add commentary to notifications, or fabricate/change any
> schedule fact. Keep all notification secrets in their existing repositories.

The 08:03 tick can queue the 09:00 digest through ntfy's delayed delivery; the
70-minute lookahead also tolerates routine jitter. If both clocks miss that
window, the first successful later tick sends the day's digest late using then-
upcoming events. The phone's ntfy connection/Android delivery remains an external
dependency; exact on-device arrival cannot be guaranteed by the generator.

### State, retries and tests

Production uses `python scanner/notify.py run --git-state`. It pushes an immutable
per-day multipart snapshot and a delivery reservation **before** network I/O,
then pushes the outcome. A push failure prevents a send. Shared Actions concurrency,
current-main checkout and a local process lock prevent overlapping runs from
creating duplicates. Previously sent legacy keys are migrated, not discarded.
Snapshots/sent history are pruned after 45 days; uncertain reservations are retained.

Explicit HTTP rejections (including rate limits) retry on the next pass. ntfy does
not offer an exactly-once publish transaction: a timeout/server error may mean it
accepted the message. These ambiguous deliveries remain `pending` and are **not
automatically resent**, avoiding duplicate phone alerts. Inspect the workflow and
ntfy history before manually changing an uncertain entry to `sent` or `retryable`.
A crash after reservation but before publish can therefore miss a message. This
is the intentional at-most-once tradeoff, not an exactly-once guarantee.

```bash
python scanner/scan.py
python scanner/notify.py dry-run                 # no secret, no network send/state change
python scanner/notify.py test                    # NTFY_URL required; immediate [Test], no production state
CORNERMAN_NOW=2026-10-23T14:00:00Z python scanner/notify.py dry-run
python -m unittest discover -s tests -v
TZ=UTC node --test tests/test_ui.js
TZ=Pacific/Auckland node --test tests/test_ui.js
```

Cloud manual preview: **Actions → Fight alerts → Run workflow → dry-run**.
Choose **test** for an actual test notification without touching production state.
Choose **run** only for a real due production pass. Do not use a fabricated
`CORNERMAN_NOW` with production state or `--git-state`.

## Desktop installation

```bash
./install-desktop.sh https://forestgeeke-sudo.github.io/cornerman/
```

The existing desktop launcher and external Google Calendar handling remain intact.
