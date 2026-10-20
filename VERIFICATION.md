# Coverage verification — October 20, 2026

Live public-source verification and automated fixture tests for this change. The current feed has **59 distinct events**, compared with **22** in the original feed. All original IDs, non-empty bout cards and fighter artwork were preserved. The 180-day horizon is unchanged.

| Promotion | Events | Next 30 days | Full/partial accessible | Unconfirmed access |
|---|---:|---:|---:|---:|
| APFC / IFL | 1 | 1 | 1 | 0 |
| ARES FC | 1 | 1 | 1 | 0 |
| Anthony Pettis FC | 1 | 1 | 1 | 0 |
| Battlefield Fight League | 1 | 0 | 1 | 0 |
| CFFC | 3 | 1 | 0 | 3 |
| Cage Warriors | 6 | 2 | 1 | 5 |
| Combat FC | 1 | 1 | 1 | 0 |
| Eternal MMA | 4 | 2 | 1 | 3 |
| Fury Fighting Championship | 4 | 2 | 3 | 1 |
| INKA MMA | 1 | 1 | 1 | 0 |
| LFA | 5 | 3 | 0 | 3 |
| Lux Fight League | 1 | 1 | 0 | 1 |
| ONE | 13 | 5 | 0 | 13 |
| PFL | 2 | 1 | 0 | 2 |
| Peter Welch's Athletics | 1 | 1 | 1 | 0 |
| Samourai MMA | 1 | 1 | 1 | 0 |
| Tuff-N-Uff | 1 | 1 | 1 | 0 |
| UAE Warriors | 1 | 1 | 1 | 0 |
| UFC | 8 | 4 | 8 | 0 |
| UFC BJJ | 2 | 1 | 1 | 1 |
| UFC Fight Pass Invitational | 0 | 0 | 0 | 0 |
| WOW FC | 1 | 1 | 1 | 0 |

## Real listings checked

- [UFC 333 official page](https://www.ufc.com/event/ufc-333): October 24, **9 AM CDT early prelims** on Paramount+ and Fight Pass; **11 AM CDT prelims** on Paramount+; **1 PM CDT main card** on Paramount+. The Unix timestamps, not the misleading local-wall-time `datetime=...Z` attributes, are parsed.
- [UFC official calendar](https://www.ufc.com/events): all eight listed upcoming events discovered, including the additional February 6 card absent from the original ESPN feed. Both event-page broadcast layouts work. UFC 335 and UFC 336 fixtures also verify the standard-time offset.
- [Fight Pass live catalogue](https://ufcfightpass.com/upcoming): all three pages retrieved with the website's public guest flow; server market verified as US. Language versions and repeated stream listings collapse into whole events; press conferences, weigh-ins and studio programmes are excluded. Event-specific normal subscription purchase options establish access.
- Regional live listings found without ESPN: UAE Warriors 74, Combat FC 14, Tuff-N-Uff 158, INKA MMA 62, Eternal MMA 111, ARES 44, Anthony Pettis FC 26, Samourai MMA 22, Fury FC 126 and others. UFC BJJ 13 is a grappling event; the official UFC BJJ calendar also supplies the later UFC BJJ 14 date with viewing unconfirmed.
- [Fury official event sections](https://www.furyfc.tv/events): Challenger Series 17/18 link prelims to OnlyFans and main cards to Fight Pass. No free YouTube assertion is made. A footer YouTube link cannot establish coverage for any event.
- [LFA official calendar](https://www.lfa.com/events/): US VICE TV / North American FloCombat evidence retained. LFA 245's announced 9 PM ET is 8 PM Central; all-day midnight placeholders remain date-only.
- [Cage Warriors official calendar](https://cagewarriors.com/cage-warriors-events/): six future events recovered through its official REST calendar. Only CW 214's event-specific Fight Pass wording confirms inclusion; the site-wide partnership does not confirm other cards.
- [CFFC official tickets](https://cffc.tv/tickets): NextGen 5, CFFC 162 and CFFC 163 dates/first bell schedules discovered. Streaming rights remain unconfirmed when the ticket page does not specify them.
- [Battlefield official upcoming calendar](https://battlefieldfl.com/bfl-event-type/upcoming-events/): BFL 89 dated December 3 with event-specific Fight Pass main-card wording; no start time invented.
- [Lux official calendar](https://luxfightleague.com/eventos/): upcoming LUX 064 discovered through its actual countdown timestamp; broadcast unknown.

## Failures and gaps

- Cage Warriors' REST endpoint worked during the audit, then began returning HTTP 403. Its six last-good observations and original verification time are retained, and the failure is visible in the feed/report. Future successful runs refresh them; they expire after seven days of failure. Other sources continue.
- Lux's older LUX 063 page lacks a usable current countdown. The provider is degraded with that exact URL in `docs/coverage.json`; the upcoming LUX 064 observation remains usable.
- No upcoming Fight Pass Invitational was verified in the current connected live catalogue. Kickboxing/Muay Thai categories are supported, but no unlisted future card is invented.
- Future CFFC, Lux, later Eternal and several Cage Warriors dates lack verified US broadcast details. Samourai currently relies on Fight Pass catalogue discovery. Far-future rights/times are frequently unpublished.
- Existing ONE and PFL listings remain visible. ONE's generic YouTube/Prime suggestions are displayed as unconfirmed; there is no verified upcoming free YouTube segment in this snapshot.
- ntfy outcomes are not an exactly-once transaction: definitive rejected sends retry, but ambiguous timeout/crash reservations require reconciliation to avoid duplicates. Actual Android delivery and the next routine tick require cloud/on-device observation.

## Automated and rendered checks

- **47 Python tests**: actual UFC 333/335/336 and Fight Pass/LFA/Eternal/CW/Fury fixture contracts, US rights, PPV exclusion, event-scoped YouTube, full/partial/free/unknown access, stale rights, explicit cancellation/rescheduling, duplicate language/date shifts, provider retention/expiry, all events in 48 hours, fill-to-five, no-event digest, UTF-8 multipart preservation, delivery retries, immutable per-day payloads, durable reservations, and real multiprocess lock contention.
- **6 Node tests**, passing with both UTC and Pacific/Auckland device timezones: default all-events view, sport/subscription filters, date-only Google Calendar links, Chicago date/month and DST/year transitions, stale and mixed-fresh rights.
- **13 Alert Maker tests**: existing appointment notification behavior plus cross-repo dispatch, dry-run, opt-out and failure reporting.
- Headless Chromium at **390 × 844**: all 59 event cards render, no horizontal overflow, watchability filter narrows results, UFC 333 expands all 14 bouts and the correct segment breakdown, and Google Calendar begins at 14:00 UTC. All six rendered smoke checks passed. Screenshot visually reviewed; poster styling retained.
- Python compilation, JavaScript syntax and whitespace/diff checks passed. No real test notification was sent during local verification.

Fixtures retain factual parser fragments and provenance in `tests/fixtures/provenance.json`; no tokens, subscriber logins, or notification topic are committed. The generated JSON report is the current machine-readable diagnostic record.
