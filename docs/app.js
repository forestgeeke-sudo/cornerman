/* Cornerman — reads fights.json and paints the poster.
   No framework, no build step: this file is what runs. */

const FEED = 'fights.json';
const STALE_HOURS = 30;      // scans run every 6h; a day-plus of silence is a fault

const state = { events: [], sport: 'all', bigOnly: false, q: '', generated: null };

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
function when(e) {
  if (e.datePrecision !== 'time') {
    const [y, m, d] = e.date.slice(0, 10).split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(e.date);
}

/* Boxing rows carry a date but no announced start time, so don't invent one. */
function whenText(e, long) {
  const d = when(e);
  const day = `${DAYS[d.getDay()]} ${MONS[d.getMonth()]} ${d.getDate()}`;
  if (e.datePrecision !== 'time') return long ? `${day} · time TBA` : day;
  const t = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
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
    el.textContent = w.name;
    if (w.url) {
      el.href = w.url;
      el.target = '_blank';
      el.rel = 'noopener noreferrer';
      el.title = `Open ${w.name}`;
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
const gcalDay = d => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;

function googleCalUrl(e) {
  const d = when(e);
  const where = [e.venue, e.location].filter(Boolean).join(', ');
  const watch = (e.watch || []).map(w => w.name).join(', ') || 'Not announced';
  const details = [
    `Watch on: ${watch}`,
    e.card && e.card.length ? `Main event: ${e.card[0].fighters.join(' vs ')}` : '',
    e.link ? `More: ${e.link}` : '',
    '', 'Added by Cornerman',
  ].filter(Boolean).join('\n');

  let dates;
  if (e.datePrecision === 'time') {
    const end = new Date(d.getTime() + 3 * 3600e3);
    dates = `${gcalUtc(d)}/${gcalUtc(end)}`;
  } else {
    const next = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1);
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

/* "Big cards" means: skip the Contender Series developmental shows, and skip
   boxing that no recognised broadcaster has picked up. */
function isBig(e) {
  if (e.tier === 'contender') return false;
  if (e.sport === 'boxing') {
    return (e.watch || []).some(w => w.kind === 'streaming' || w.kind === 'tv' || w.kind === 'ppv');
  }
  return true;
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
    if (state.sport !== 'all' && e.sport !== state.sport) return false;
    if (state.bigOnly && !isBig(e)) return false;
    if (q && !haystack(e).includes(q)) return false;
    return true;
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
  $('#heroWhen').textContent = whenText(pick, true);
  $('#heroWhere').textContent = [pick.venue, pick.location].filter(Boolean).join(', ') || '—';
  const w = $('#heroWatch');
  w.textContent = '';
  w.appendChild(chips(pick.watch));
  $('#heroIcs').href = googleCalUrl(pick);

  const tick = () => { $('#heroCount').innerHTML = countdownText(when(pick)); };
  tick();
  clearInterval(renderHero._t);
  renderHero._t = setInterval(tick, 30000);
}

function buildCard(e) {
  const node = $('#cardTpl').content.cloneNode(true);
  const art = node.querySelector('.card');
  const d = when(e);

  art.dataset.sport = e.sport;
  node.querySelector('.card__day').textContent = d.getDate();
  node.querySelector('.card__mon').textContent = MONS[d.getMonth()];
  // Kicker carries the card's identity ("UFC 330", "Dana White's Contender
  // Series"); the heading carries the matchup. Boxing rows are named after the
  // matchup itself, so they just get the sport.
  const label = e.sport === 'mma' ? e.name.split(':')[0].trim() : e.org;
  const bout = e.card && e.card.length ? e.card[0].fighters.join(' vs ') : e.headline;
  node.querySelector('.card__org').textContent = label;
  node.querySelector('.card__bout').textContent =
    bout && bout !== label ? bout : 'Matchups to be announced';

  const meta = [whenText(e, true), [e.venue, e.location].filter(Boolean).join(', ')]
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

  node.querySelector('[data-ics]').href = googleCalUrl(e);

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

function render() {
  const rows = visible();
  listEl.textContent = '';
  emptyEl.hidden = rows.length > 0;

  let lastMonth = null;
  rows.forEach(e => {
    const d = when(e);
    const key = `${d.getFullYear()}-${d.getMonth()}`;
    if (key !== lastMonth) {
      lastMonth = key;
      const h = document.createElement('h2');
      h.className = 'month';
      h.textContent = `${MONS[d.getMonth()]} ${d.getFullYear()}`;
      listEl.appendChild(h);
    }
    listEl.appendChild(buildCard(e));
  });
}

/* ---------- wiring ---------- */

document.querySelectorAll('[data-sport]').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('[data-sport]').forEach(b => b.classList.toggle('is-on', b === btn));
    state.sport = btn.dataset.sport;
    render();
  };
});
$('#bigOnly').onchange = ev => { state.bigOnly = ev.target.checked; render(); };

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
    // Drop anything already finished; a card runs a few hours.
    state.events = (data.events || [])
      .filter(e => when(e).getTime() > now - 6 * 3600e3)
      .sort((a, b) => when(a) - when(b));
    state.generated = data.generated;

    const age = (now - new Date(data.generated).getTime()) / 3600e3;
    $('#stamp').textContent = new Date(data.generated)
      .toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
    setStatus(age > STALE_HOURS
      ? `Feed hasn't updated in ${Math.round(age)} hours — the scanner may be stuck.`
      : '', age > STALE_HOURS);

    renderHero();
    render();
  } catch (err) {
    setStatus(`Couldn't load the fight feed (${err.message}). Showing nothing rather than something wrong.`, true);
  }
}

load();
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
