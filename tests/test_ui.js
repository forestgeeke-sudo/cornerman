const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function ui() {
  const elements = new Map();
  const document = {
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, { onchange: null, oninput: null, classList: { toggle() {} }, addEventListener() {} });
      return elements.get(selector);
    },
    addEventListener() {},
  };
  const source = fs.readFileSync(require('node:path').join(__dirname, '../docs/app.js'), 'utf8')
    .replace(/\nload\(\);[\s\S]*$/, '\n');
  const context = { document, window: { matchMedia: () => ({ matches: false }) }, navigator: {}, location: {}, URL, Date, Intl, setInterval() {}, clearInterval() {}, setTimeout() {}, clearTimeout() {}, fetch() {} };
  vm.createContext(context);
  vm.runInContext(source + '\nglobalThis.api = { state, visible, when, whenText, googleCalUrl, hasTimedStart, liveUntil, startLabel, refreshAvailability, calendarParts, platformAccessLabel, zoneInstant };', context);
  return context.api;
}

test('default filtering shows all sports; optional filters narrow results', () => {
  const { state, visible } = ui();
  state.events = [
    { sport: 'mma', availability: 'included', name: 'MMA' },
    { sport: 'boxing', availability: 'other_service', name: 'Boxing' },
    { sport: 'combat_sports', availability: 'unconfirmed', name: 'Uncategorized combat sport' },
  ];
  assert.equal(visible().length, 3);
  state.sport = 'boxing';
  assert.deepEqual(Array.from(visible(), e => e.name), ['Boxing']);
  state.sport = 'combat_sports';
  assert.deepEqual(Array.from(visible(), e => e.name), ['Uncategorized combat sport']);
  state.sport = 'all'; state.includedOnly = true;
  assert.deepEqual(Array.from(visible(), e => e.name), ['MMA']);
});

test('date-only events retain their Chicago date without inventing a timed start', () => {
  const { googleCalUrl, hasTimedStart, whenText, liveUntil } = ui();
  const event = { name: 'TBA card', date: '2027-03-14T00:00:00Z', datePrecision: 'day' };
  assert.equal(hasTimedStart(event), false);
  assert.match(whenText(event, true), /time TBA/);
  assert.match(googleCalUrl(event), /dates=20270314\/20270315/);
  assert.equal(liveUntil(event), Date.parse('2027-03-15T08:00:00Z')); // 3 a.m. CDT after DST starts
});

test('confirmed broadcast start takes precedence over scheduled start and uses Chicago time', () => {
  const { whenText, hasTimedStart, startLabel, liveUntil } = ui();
  const event = { date: '2027-01-01', datePrecision: 'day', earliestBroadcastStart: '2027-01-10T00:30:00Z', scheduledStart: '2027-01-10T01:00:00Z' };
  assert.equal(hasTimedStart(event), true);
  assert.match(whenText(event, true), /Sat Jan 9 · 6:30 PM/);
  assert.equal(startLabel(event), 'Broadcast starts');
  const withSegment = { date: '2027-01-10', datePrecision: 'day', segments: [
    { start: '2027-01-12T00:00:00Z', verifiedAt: '2027-01-01T00:00:00Z', covered: false },
    { start: '2027-01-13T00:00:00Z', verifiedAt: '2027-01-01T00:00:00Z', stale: true },
  ] };
  assert.equal(liveUntil(withSegment), Date.parse('2027-01-12T08:00:00Z'));
  assert.equal(startLabel({ date: '2027-01-10T00:00:00Z', datePrecision: 'time' }), 'Scheduled start · unconfirmed');
});

test('rights older than 72 hours downgrade availability and remove confirmed starts', () => {
  const { refreshAvailability } = ui();
  const now = Date.parse('2027-01-10T00:00:00Z');
  const event = { eventDay: '2027-01-12', coverageComplete: true, earliestBroadcastStart: '2027-01-12T00:00:00Z', mainCardStart: '2027-01-12T02:00:00Z', segments: [
    { name: 'Main card', start: '2027-01-12T02:00:00Z', verifiedAt: '2027-01-05T00:00:00Z', region: 'US', covered: true, subscriptionCovered: true, platforms: [{ name: 'UFC Fight Pass', access: 'subscription', covered: true, confirmed: true }] },
  ] };
  const freshened = refreshAvailability(event, now);
  assert.equal(freshened.availability, 'unconfirmed');
  assert.equal(freshened.segments[0].platforms[0].confirmed, false);
  assert.equal(freshened.segments[0].platforms[0].covered, false);
  assert.equal(freshened.earliestBroadcastStart, null);
  assert.equal(freshened.mainCardStart, null);
  assert.equal(freshened.date, '2027-01-12');
  assert.equal(freshened.datePrecision, 'day');
});

test('mixed fresh and stale rights stay partly included; Chicago month follows event zone', () => {
  const { refreshAvailability, calendarParts, platformAccessLabel } = ui();
  const now = Date.parse('2027-01-10T00:00:00Z');
  const event = { eventDay: '2027-01-12', coverageComplete: true, segments: [
    { name: 'Prelims', start: '2027-01-12T00:00:00Z', verifiedAt: '2027-01-09T00:00:00Z', region: 'US', covered: true, subscriptionCovered: true, platforms: [{ name: 'Fight Pass', access: 'subscription', covered: true, confirmed: true }] },
    { name: 'Main card', start: '2027-01-12T02:00:00Z', verifiedAt: '2027-01-05T00:00:00Z', region: 'US', covered: true, subscriptionCovered: true, platforms: [{ name: 'Fight Pass', access: 'subscription', covered: true, confirmed: true }] },
  ] };
  const result = refreshAvailability(event, now);
  assert.equal(result.availability, 'partial');
  assert.equal(result.segments[0].platforms[0].confirmed, true);
  assert.equal(result.segments[1].platforms[0].confirmed, false);
  assert.equal(result.earliestBroadcastStart, '2027-01-12T00:00:00Z');
  assert.deepEqual(JSON.parse(JSON.stringify(calendarParts({ date: '2027-01-01T01:00:00Z', datePrecision: 'time' }))), { day: 31, month: 12, year: 2026 });
  assert.equal(platformAccessLabel(result.segments[0].platforms[0], result.segments[0]), 'Included');
});

test('Chicago local midnight conversion handles month and year boundaries', () => {
  const { zoneInstant } = ui();
  assert.equal(zoneInstant(2027, 1, 1, 3).toISOString(), '2027-01-01T09:00:00.000Z');
  assert.equal(zoneInstant(2026, 11, 1, 3).toISOString(), '2026-11-01T09:00:00.000Z');
  assert.equal(zoneInstant(2027, 3, 14, 3).toISOString(), '2027-03-14T08:00:00.000Z');
});
