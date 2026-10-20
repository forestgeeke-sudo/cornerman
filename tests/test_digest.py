import unittest
from datetime import datetime, timedelta, timezone
from scanner.digest import build_digest, select_events, split_message


def event(i, at=None, **kw):
    return {'id': str(i), 'name': f'Event {i}', 'date': at or '2026-10-21', **kw}


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 14, tzinfo=timezone.utc)

    def test_all_48h_and_boundary(self):
        es = [event(i, (self.now + timedelta(hours=i)).isoformat()) for i in range(1, 50)]
        self.assertEqual(len(select_events(es, self.now)), 48)

    def test_fill_five_date_only(self):
        es = [event(i, f'2026-10-{21+i:02}') for i in range(7)]
        self.assertEqual(len(select_events(es, self.now)), 5)
        text = build_digest(es, self.now)
        self.assertIn('time unconfirmed', text)
        self.assertNotIn('Main event', text)

    def test_generic_schedule_not_broadcast(self):
        text = build_digest([event(1, '2026-10-21T14:00:00Z')], self.now)
        self.assertIn('broadcast time unconfirmed', text)
        self.assertNotIn('First broadcast:', text)

    def test_lossless_unicode_split(self):
        message = ('Fight 🥊 é\n' * 2000) + 'last event'
        parts = split_message(message)
        self.assertGreater(len(parts), 1)
        self.assertEqual(''.join(parts), message)
        self.assertTrue(all(len(p.encode()) <= 4096 for p in parts))

    def test_dst_elapsed_48_hours(self):
        now = datetime.fromisoformat('2026-10-31T14:00:00+00:00')
        es = [event(i, (now + timedelta(hours=i)).isoformat()) for i in range(1, 51)]
        self.assertEqual(len(select_events(es, now)), 48)

    def test_no_spoilers_and_cancelled(self):
        text = build_digest([event(1, result='winner surprise'), event(2, status='cancelled')], self.now)
        self.assertNotIn('surprise', text)
        self.assertNotIn('Event 2', text)


    def test_rights_rechecked_at_generation_time(self):
        e = event(1, '2026-10-21T14:00:00Z', coverageComplete=True,
                  availability='included', segments=[{
                      'name': 'Main card', 'start': '2026-10-21T14:00:00Z',
                      'region': 'US', 'verifiedAt': '2026-10-16T13:59:00Z',
                      'platforms': [{'name': 'Paramount+', 'access': 'subscription',
                                     'covered': True, 'confirmed': True}]}])
        text = build_digest([e], self.now)
        self.assertNotIn('Included in your subscriptions', text)
        self.assertIn('Viewing access unconfirmed', text)
        self.assertIn('Paramount+ (unconfirmed)', text)
        self.assertNotIn('First broadcast:', text)
        self.assertEqual(e['availability'], 'included')  # Input feed remains untouched.

    def test_fresh_rights_still_included(self):
        e = event(1, '2026-10-21T14:00:00Z', coverageComplete=True,
                  segments=[{'name': 'Main card', 'start': '2026-10-21T14:00:00Z',
                             'region': 'US', 'verifiedAt': self.now.isoformat(),
                             'platforms': [{'name': 'Paramount+', 'access': 'subscription'}]}])
        text = build_digest([e], self.now)
        self.assertIn('Included in your subscriptions', text)
        self.assertIn('First broadcast:', text)
