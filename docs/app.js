/* Cornerman — reads fights.json and paints the poster.
   No framework, no build step: this file is what runs. */

const FEED = 'fights.json';
const STALE_HOURS = 30;      // scans run every 6h; a day-plus of silence is a fault

const state = { events: [], sport: 'all', bigOnly: false, includedOnly: false, q: '', generated: null };

const $ = sel => document.querySelector(sel);
const listEl = $('#list');
const emptyEl = $('#empty');
const statusEl = $('#status');

/* ---------- dates ---------- */

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/* Day-precision rows (boxing) carry a nominal UTC midnight. Parsing that as an
   instant drags the card back a day for anyone west of Greenwich, so rebuild
   those from their calendar parts as local midnight instead. */
const ZONE = 'America/Chicago';
function partsInZone(date) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: ZONE, year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(date);
  return Object.fromEntries(parts.map(p => [p.type, Number(p.value)]));
}
function zoneInstant(year, month, day, hour = 0) {
  let instant = Date.UTC(year, month - 1, day, hour);
  for (let i = 0; i < 3; i++) {
    const p = partsInZone(new Date(instant));
    instant += Date.UTC(year, month - 1, day, hour) - Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
  }
  return new Date(instant);
}
function calendarParts(e) {
  const p = partsInZone(when(e));
  return { day: p.day, month: p.month, year: p.year };
}
const RIGHTS_MAX_AGE = 72 * 3600e3;
function refreshAvailability(event, now = Date.now()) {
  if (!Array.isArray(event.segments) || !event.segments.length) {
    return { ...event, availability: 'unconfirmed', watch: (event.watch || []).map(w => ({ ...w, confirmed: false, covered: false })) };
  }
  const segments = event.segments.map(segment => {
    const verified = Date.parse(segment.verifiedAt);
    const fresh = Number.isFinite(verified) && verified <= now && now - verified <= RIGHTS_MAX_AGE && segment.region === 'US' && !segment.stale;
    const platforms = (segment.platforms || []).map(platform => {
      const platformVerified = Date.parse(platform.verifiedAt || segment.verifiedAt);
      const confirmed = fresh && Number.isFinite(platformVerified) && platformVerified <= now && now - platformVerified <= RIGHTS_MAX_AGE && !platform.stale && platform.confirmed === true;
      return { ...platform, confirmed, covered: confirmed && platform.covered === true };
    });
    return { ...segment, platforms, start: fresh ? segment.start : null, stale: !fresh, covered: fresh && platforms.some(p => p.covered), subscriptionCovered: fresh && platforms.some(p => p.covered && (p.subscriptionCovered || /subscription|included/i.test(p.access || '') || (/fight\s*pass/i.test(p.name || '') && p.access === 'free'))) };
  });
  const coverageComplete = event.coverageComplete === true && segments.every(s => !s.stale);
  const allCovered = coverageComplete && segments.every(s => s.covered);
  const coveredPlatforms = segments.flatMap(s => s.platforms.filter(p => p.covered));
  const anySubscription = segments.some(s => s.subscriptionCovered);
  const freeYoutubeOnly = coveredPlatforms.length > 0 && coveredPlatforms.every(p => /youtube/i.test(p.name || '') && !/subscription/i.test(p.access || ''));
  const hasCovered = coveredPlatforms.length > 0;
  const hasConfirmedAlternative = segments.some(s => s.platforms.some(p => p.confirmed && !p.covered));
  const availability = allCovered && anySubscription ? 'included'
    : allCovered && freeYoutubeOnly ? 'free'
    : hasCovered ? 'partial'
    : hasConfirmedAlternative ? 'other_service'
    : 'unconfirmed';
  const watchByKey = new Map();
  segments.forEach(s => s.platforms.forEach(p => {
    const key = `${p.name || ''}|${p.url || ''}`;
    const old = watchByKey.get(key);
    if (!old || p.confirmed) watchByKey.set(key, { name: p.name, url: p.url, kind: p.kind, access: p.access, confirmed: p.confirmed, covered: p.covered });
  }));
  const freshStarts = segments.filter(s => s.start && !s.stale);
  const earliestBroadcastStart = freshStarts.map(s => s.start).sort((a, b) => Date.parse(a) - Date.parse(b))[0] || null;
  const mainCardStart = freshStarts.find(s => /main\s*card/i.test(s.name || ''))?.start || null;
  const fallbackDate = event.eventDay || event.date;
  return {
    ...event, segments, coverageComplete, availability, watch: [...watchByKey.values()],
    earliestBroadcastStart, mainCardStart,
    scheduledStart: event.scheduledStart || null,
    date: earliestBroadcastStart || event.scheduledStart || fallbackDate,
    datePrecision: earliestBroadcastStart || event.scheduledStart ? 'time' : 'day',
  };
}
function when(e) {
  const date = e.earliestBroadcastStart || e.scheduledStart || e.date;
  if (!e.earliestBroadcastStart && !e.scheduledStart && e.datePrecision !== 'time') {
    const [y, m, d] = String(e.date).slice(0, 10).split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d, 18)); // stable event-day anchor; never used as an announced time
  }
  return new Date(date);
}
function hasTimedStart(e) { return !!(e.earliestBroadcastStart || e.scheduledStart || (e.datePrecision === 'time' && e.date)); }
function startLabel(e) { return e.earliestBroadcastStart ? 'Broadcast starts' : (e.scheduledStart || e.datePrecision === 'time') ? 'Scheduled start · unconfirmed' : 'Date'; }

/* Timed cards drop 3 hours after the bell. Date-only cards (boxing with no
   announced time) stay through that local day, then 3 hours into the next
   morning so an evening card isn't gone at midnight. */
const LIVE_MS = 8 * 3600e3;
function liveUntil(e) {
  const confirmed = (e.segments || []).flatMap(s => s.start && s.verifiedAt && !s.stale ? [new Date(s.start).getTime()] : []);
  const d = hasTimedStart(e) ? when(e).getTime() : 0;
  const latest = Math.max(d, ...confirmed, 0);
  if (latest) return latest + LIVE_MS;
  const p = partsInZone(when(e));
  return zoneInstant(p.year, p.month, p.day + 1, 3).getTime();
}
function isLive(e, now = Date.now()) {
  return liveUntil(e) > now;
}

/* Boxing rows carry a date but no announced start time, so don't invent one. */
function whenText(e, long) {
  const d = when(e);
  const p = partsInZone(d);
  const date = new Date(Date.UTC(p.year, p.month - 1, p.day));
  const day = `${DAYS[date.getUTCDay()]} ${MONS[p.month - 1]} ${p.day}`;
  if (!hasTimedStart(e)) return long ? `${day} · time TBA` : day;
  const t = d.toLocaleTimeString('en-US', { timeZone: ZONE, hour: 'numeric', minute: '2-digit' });
  return `${day} · ${t}`;
}

function countdownText(d) {
  const ms = d - Date.now();
  if (ms <= 0) return 'Live or done';
  const mins = Math.floor(ms / 6e4);
  const days = Math.floor(mins / 1440);
  const hrs = Math.floor((mins % 1440) / 60);
  if (days > 0) return `<strong>${days}</strong> day${days > 1 ? 's' : ''} <strong>${hrs}</strong> hr${hrs === 1 ? '' : 's'} away`;
  if (hrs > 0) return `<strong>${hrs}</strong> hr${hrs > 1 ? 's' : ''} <strong>${mins % 60}</strong> min away`;
  return `<strong>${mins}</strong> min away`;
}

/* ---------- watch chips ---------- */

/* Chrome --app on Linux/Wayland turns window.open(..., 'popup=yes,width=…')
   into a few-pixel window jammed off the top-left of the screen. Clicking
   that then hands the URL to the OS, which on Fedora opens GNOME Calendar
   instead of Google Calendar in a browser.

   The desktop installer registers x-cornerman: and launches a real Chrome
   window (no --app). Phones must not go through that — a normal https tap
   is what opens the Google Calendar app. */
function inChromelessDesktop() {
  if (window.matchMedia('(pointer: coarse)').matches) return false;
  if (window.matchMedia('(display-mode: standalone)').matches) return true;
  try { return window.toolbar && window.toolbar.visible === false; }
  catch { return false; }
}

function openOutsideApp(url) {
  if (inChromelessDesktop()) {
    location.assign('x-cornerman:?u=' + encodeURIComponent(url));
    return;
  }
  const opened = window.open(url, '_blank');
  if (opened) opened.opener = null;
}

function chips(watch) {
  const frag = document.createDocumentFragment();
  (watch || []).forEach(w => {
    const el = document.createElement(w.url ? 'a' : 'span');
    el.className = `chip chip--${w.kind || 'other'}`;
    el.textContent = w.confirmed ? w.name : `${w.name} (unconfirmed)`;
    if (!w.confirmed) { el.classList.add('chip--unannounced'); el.title = `${w.name} — unconfirmed`; }
    if (w.url) {
      el.href = w.url;
      el.target = '_blank';
      el.rel = 'noopener noreferrer';
      el.title = w.confirmed ? `Open ${w.name}` : `Open ${w.name} — unconfirmed`;
    }
    frag.appendChild(el);
  });
  if (!frag.childNodes.length) {
    const el = document.createElement('span');
    el.className = 'chip chip--unannounced';
    el.textContent = 'Not announced';
    frag.appendChild(el);
  }
  return frag;
}

/* ---------- Google Calendar ---------- */

const gcalUtc = d => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
const gcalDay = d => { const p = partsInZone(d); return `${p.year}${String(p.month).padStart(2, '0')}${String(p.day).padStart(2, '0')}`; };

function googleCalUrl(e) {
  const d = when(e);
  const where = [e.venue, e.location].filter(Boolean).join(', ');
  const watch = (e.watch || []).map(w => w.name).join(', ') || 'Not announced';
  const details = [
    `Watch on: ${watch}`,
    hasTimedStart(e) ? `${startLabel(e)}: ${whenText(e, true)}` : 'Start time unannounced',
    e.mainCardStart ? `Main card scheduled: ${whenText({ date: e.mainCardStart, datePrecision: 'time' }, true)}` : '',
    ...((e.segments || []).map(s => `${s.name}: ${s.start ? whenText({ date: s.start, datePrecision: 'time' }, true) : 'time TBA'} — ${(s.platforms || []).map(p => `${p.name} (${p.access || 'unconfirmed'})`).join(', ') || 'availability unconfirmed'}`)),
    ...((e.segments || []).map(s => s.sourceUrl ? `Viewing source: ${s.sourceUrl}` : '')),
    e.link ? `Event source: ${e.link}` : '',
    hasTimedStart(e) ? 'Calendar end time is an estimate.' : '',
    '', 'Added by Cornerman',
  ].filter(Boolean).join('\n');

  let dates;
  if (hasTimedStart(e)) {
    const ends = [d.getTime() + 3 * 3600e3, Date.parse(e.scheduledEnd || '')];
    (e.segments || []).filter(s => !s.stale && s.start).forEach(s => ends.push(Date.parse(s.start) + 3 * 3600e3));
    const end = new Date(Math.max(...ends.filter(Number.isFinite)));
    dates = `${gcalUtc(d)}/${gcalUtc(end)}`;
  } else {
    const next = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1, d.getUTCHours()));
    dates = `${gcalDay(d)}/${gcalDay(next)}`;
  }

  /* dates must keep a raw `/` — `%2F` makes Google Calendar drop the times.
     `/calendar/render?action=TEMPLATE` is the create-event URL; `/event` is
     for opening an existing shared event and just 404s a blank page. */
  const q = [
    'action=TEMPLATE',
    `text=${encodeURIComponent(e.name || '')}`,
    `dates=${dates}`,
    `details=${encodeURIComponent(details)}`,
    `location=${encodeURIComponent(where || watch)}`,
  ].join('&');
  return `https://calendar.google.com/calendar/render?${q}`;
}

/* ---------- filtering ---------- */

/* "Big cards" means skip the Contender Series developmental shows. */
function isBig(e) {
  return e.tier !== 'contender';
}

function haystack(e) {
  return [e.name, e.headline, e.org, e.venue, e.location,
          ...(e.card || []).flatMap(b => b.fighters),
          ...(e.watch || []).map(w => w.name)]
    .filter(Boolean).join(' ').toLowerCase();
}

function visible() {
  const q = state.q.trim().toLowerCase();
  return state.events.filter(e => {
    if (state.bigOnly && !isBig(e)) return false;
    if (state.sport !== 'all' && e.sport !== state.sport) return false;
    if (state.includedOnly && !['included', 'partial', 'free'].includes(e.availability)) return false;
    if (q && !haystack(e).includes(q)) return false;
    return true;
  });
}

/* ---------- faces ---------- */

function paintFaces(container, art) {
  container.textContent = '';
  const shots = (art || []).filter(p => p && p.url).slice(0, 2);
  if (!shots.length) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  container.classList.toggle('faces--solo', shots.length === 1);
  let live = shots.length;
  shots.forEach((p, i) => {
    if (i === 1) {
      const vs = document.createElement('span');
      vs.className = 'faces__vs';
      vs.textContent = 'vs';
      vs.setAttribute('aria-hidden', 'true');
      container.appendChild(vs);
    }
    const img = document.createElement('img');
    img.src = (p.url || '').replace(/([?&]w=)280(&h=)360/, '$1350$2254');
    img.alt = p.name || '';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', () => {
      img.remove();
      live -= 1;
      if (live <= 0) container.hidden = true;
    });
    container.appendChild(img);
  });
}

/* ---------- rendering ---------- */

function renderHero() {
  const hero = $('#hero');
  // The headline slot is for a real card, not a developmental show.
  const pick = state.events.find(e => e.sport === 'mma' && e.tier !== 'contender')
            || state.events.find(e => e.sport === 'mma')
            || state.events[0];
  if (!pick) { hero.hidden = true; return; }

  hero.hidden = false;
  $('#heroKicker').textContent = pick.org === 'UFC' ? 'Next UFC card' : 'Next up';
  // The matchup gets its own line below, so the title keeps only the card's
  // name ("UFC 330") rather than repeating "Makhachev vs. Machado Garry".
  $('#heroOrg').textContent = pick.name.split(':')[0].trim();
  $('#heroBout').textContent = pick.card && pick.card.length
    ? pick.card[0].fighters.join('  vs  ')
    : pick.headline;
  $('#heroWhen').textContent = `${startLabel(pick)}: ${whenText(pick, true)}`;
  $('#heroWhere').textContent = [pick.venue, pick.location].filter(Boolean).join(', ') || '—';
  const w = $('#heroWatch');
  w.textContent = '';
  w.appendChild(chips(pick.watch));
  $('#heroIcs').href = googleCalUrl(pick);
  paintFaces($('#heroFaces'), pick.art);

  const tick = () => { $('#heroCount').innerHTML = hasTimedStart(pick) ? countdownText(when(pick)) : 'Date announced · start time TBA'; };
  tick();
  clearInterval(renderHero._t);
  renderHero._t = setInterval(tick, 30000);
}

function buildCard(e) {
  const node = $('#cardTpl').content.cloneNode(true);
  const art = node.querySelector('.card');
  const d = when(e);
  const dateParts = calendarParts(e);

  art.dataset.sport = e.sport;
  node.querySelector('.card__day').textContent = dateParts.day;
  node.querySelector('.card__mon').textContent = MONS[dateParts.month - 1];
  // Kicker carries the card's identity ("UFC 330", "Dana White's Contender
  // Series"); the heading carries the matchup. Boxing rows are named after the
  // matchup itself, so they just get the sport.
  const label = e.sport === 'mma' ? e.name.split(':')[0].trim() : e.org;
  const bout = e.card && e.card.length ? e.card[0].fighters.join(' vs ') : e.headline;
  node.querySelector('.card__org').textContent = label;
  node.querySelector('.card__bout').textContent =
    bout && bout !== label ? bout : 'Matchups to be announced';

  const meta = [`${startLabel(e)}: ${whenText(e, true)}`, [e.venue, e.location].filter(Boolean).join(', ')]
    .filter(Boolean).join('  ·  ');
  node.querySelector('.card__meta').textContent = meta;

  // Caveats that would otherwise make the date misleading (e.g. Asian cards
  // that air in the US the evening before) ride along with the event.
  if (e.note) {
    const n = document.createElement('p');
    n.className = 'note';
    n.textContent = e.note;
    node.querySelector('.card__meta').after(n);
  }

  node.querySelector('.card__watch').appendChild(chips(e.watch));
  const availability = { included: 'Included', partial: 'Partly included', free: 'Free on YouTube', other_service: 'Other service', unconfirmed: 'Availability unconfirmed' };
  node.querySelector('.availability').textContent = availability[e.availability] || 'Availability unconfirmed';
  const detail = node.querySelector('.viewing');
  if (e.segments && e.segments.length) {
    detail.hidden = false;
    const body = detail.querySelector('.viewing__body');
    e.segments.forEach(s => {
      const section = document.createElement('section');
      const h = document.createElement('h4'); h.textContent = s.name; section.appendChild(h);
      const time = document.createElement('p'); time.textContent = s.start ? `Start: ${whenText({ date: s.start, datePrecision: 'time' }, true)}${s.stale ? ' · may be outdated' : ''}` : 'Start time unconfirmed'; section.appendChild(time);
      const platformList = document.createElement('div'); platformList.className = 'chips';
      (s.platforms || []).forEach(p => {
        const chip = document.createElement(p.url ? 'a' : 'span'); chip.className = `chip chip--${p.kind || 'other'}${p.confirmed ? '' : ' chip--unannounced'}`; chip.textContent = `${p.name} · ${platformAccessLabel(p, s)}`;
        if (p.url) { chip.href = p.url; chip.target = '_blank'; chip.rel = 'noopener noreferrer'; }
        platformList.appendChild(chip);
      });
      if (!platformList.childNodes.length) platformList.textContent = 'Viewing details unconfirmed';
      section.appendChild(platformList);
      if (s.sourceUrl) { const a = document.createElement('a'); a.href = s.sourceUrl; a.textContent = 'Source'; a.target = '_blank'; a.rel = 'noopener noreferrer'; section.appendChild(a); }
      if (s.verifiedAt) { const v = document.createElement('small'); v.textContent = `Verified ${new Date(s.verifiedAt).toLocaleString('en-US', { timeZone: ZONE, dateStyle: 'medium', timeStyle: 'short' })} CT`; section.appendChild(v); }
      body.appendChild(section);
    });
  }
  if (e.mainCardStart) {
    const mainStart = document.createElement('p');
    mainStart.className = 'availability';
    mainStart.textContent = `Main card scheduled: ${whenText({ date: e.mainCardStart, datePrecision: 'time' }, true)}`;
    detail.hidden = false;
    detail.querySelector('.viewing__body').prepend(mainStart);
  }
  node.querySelector('[data-ics]').href = googleCalUrl(e);
  paintFaces(node.querySelector('.card__faces'), e.art);

  const bouts = node.querySelector('.bouts');
  const toggle = node.querySelector('.card__toggle');
  if (e.card && e.card.length > 1) {
    toggle.hidden = false;
    e.card.forEach(b => {
      const li = document.createElement('li');
      const slot = document.createElement('span');
      slot.className = `slot slot--${b.slot}`;
      slot.textContent = b.slot === 'main' ? 'Main' : b.slot === 'comain' ? 'Co-main' : `${b.order}`;
      li.appendChild(slot);

      const names = document.createElement('span');
      names.innerHTML = b.fighters.map(f =>
        f.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
      ).join('<span class="vs"> vs </span>');
      li.appendChild(names);

      if (b.weight) {
        const wt = document.createElement('span');
        wt.className = 'wt';
        wt.textContent = b.weight;
        li.appendChild(wt);
      }
      bouts.appendChild(li);
    });
    toggle.onclick = () => {
      const open = !bouts.hidden;
      bouts.hidden = open;
      toggle.textContent = open ? 'Full card' : 'Hide card';
      toggle.setAttribute('aria-expanded', String(!open));
    };
    toggle.setAttribute('aria-expanded', 'false');
  }
  return node;
}

function platformAccessLabel(platform, segment) {
  const access = String(platform.access || '').toLowerCase();
  if (!platform.confirmed) return 'Availability unconfirmed';
  if (platform.covered && (segment.subscriptionCovered || /subscription|included/.test(access) || (/fight\s*pass/i.test(platform.name || '') && access === 'free'))) return 'Included';
  if (platform.covered && /youtube/i.test(platform.name || '')) return 'Free on YouTube';
  if (/ppv|pay.per.view|purchase/.test(access)) return 'PPV · extra payment';
  if (platform.covered) return 'Included';
  return 'Separate service';
}

function render() {
  const rows = visible();
  listEl.textContent = '';
  emptyEl.hidden = rows.length > 0;

  let lastMonth = null;
  rows.forEach(e => {
    const d = when(e);
    const p = calendarParts(e);
    const key = `${p.year}-${p.month}`;
    if (key !== lastMonth) {
      lastMonth = key;
      const h = document.createElement('h2');
      h.className = 'month';
      h.textContent = `${MONS[p.month - 1]} ${p.year}`;
      listEl.appendChild(h);
    }
    listEl.appendChild(buildCard(e));
  });
}

/* ---------- wiring ---------- */

$('#bigOnly').onchange = ev => { state.bigOnly = ev.target.checked; render(); };
$('#includedOnly').onchange = ev => { state.includedOnly = ev.target.checked; render(); };
$('#sportFilter').onchange = ev => { state.sport = ev.target.value; render(); };

let qt;
$('#search').oninput = ev => {
  clearTimeout(qt);
  qt = setTimeout(() => { state.q = ev.target.value; render(); }, 120);
};

function setStatus(msg, warn) {
  statusEl.textContent = msg || '';
  statusEl.classList.toggle('is-warn', !!warn);
}

async function load() {
  try {
    const res = await fetch(`${FEED}?t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const now = Date.now();
    state.events = (data.events || []).map(e => refreshAvailability(e, now))
      .filter(e => isLive(e, now))
      .sort((a, b) => when(a) - when(b));
    state.generated = data.generated;

    const age = (now - new Date(data.generated).getTime()) / 3600e3;
    $('#stamp').textContent = new Date(data.generated)
      .toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
    const sourceIssues = (data.providers || []).filter(p => ['failed', 'degraded'].includes(p.status));
    const sourceWarning = sourceIssues.length ? `Some sources could not be refreshed: ${sourceIssues.map(p => p.provider).join(', ')}. See coverage report.` : '';
    const feedWarning = age > STALE_HOURS ? `Feed hasn't updated in ${Math.round(age)} hours — the scanner may be stuck.` : '';
    setStatus([feedWarning, sourceWarning].filter(Boolean).join(' '), !!(feedWarning || sourceWarning));

    renderHero();
    render();
  } catch (err) {
    setStatus(`Couldn't load the fight feed (${err.message}). Showing nothing rather than something wrong.`, true);
  }
}

function dropFinished() {
  const next = state.events.filter(e => isLive(e));
  if (next.length === state.events.length) return;
  state.events = next;
  renderHero();
  render();
}

load();
setInterval(dropFinished, 60e3);
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });

document.addEventListener('click', ev => {
  if (!inChromelessDesktop()) return;
  const a = ev.target.closest('a[href]');
  if (!a) return;
  let url;
  try { url = new URL(a.href, location.href); } catch { return; }
  if (url.origin === location.origin) return;
  ev.preventDefault();
  openOutsideApp(url.href);
});

if ('serviceWorker' in navigator) {
  addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}
