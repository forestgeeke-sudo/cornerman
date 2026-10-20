import concurrent.futures
import multiprocessing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
from scanner import notify


def lock_process(path, calls, job, now, ready):
    if not ready.wait(10):
        raise RuntimeError('process gate timeout')
    path = Path(path)
    with notify.locked(path):
        state = notify.load_state(path)
        def sender(*args):
            with open(calls, 'a') as out:
                out.write('sent\n')
        notify.deliver([job], state, 'unused', now,
                       lambda s: notify.save_state(s, path), sender)


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 13, tzinfo=timezone.utc)
        self.job = {'key': 'digest:2026-10-20:1', 'title': 'Digest', 'body': 'Hello', 'at': '2026-10-20T14:00:00Z', 'priority': 'default'}

    def test_due_delay_and_local_day(self):
        jobs = notify.plan({'events': []}, self.now)
        self.assertEqual(jobs[0]['key'], 'digest:2026-10-20:1')
        self.assertEqual(jobs[0]['at'], '2026-10-20T09:00:00-05:00')
        self.assertFalse(notify.plan({'events': []}, self.now.replace(hour=12)))
        winter = notify.plan({'events': []}, datetime(2026, 11, 2, 14, tzinfo=timezone.utc))
        self.assertTrue(winter[0]['at'].endswith('-06:00'))

    def test_reserve_before_send_and_dedupe(self):
        state = {'deliveries': {}}
        saved = []
        def persist(s):
            saved.append(json.loads(json.dumps(s)))
        def send(*args):
            self.assertEqual(saved[-1]['deliveries'][self.job['key']]['status'], 'pending')
        notify.deliver([self.job], state, 'url', self.now, persist, send)
        notify.deliver([self.job], state, 'url', self.now, persist, lambda *a: self.fail('duplicate'))
        self.assertEqual(state['deliveries'][self.job['key']]['status'], 'sent')

    def test_push_state_failure_prevents_send(self):
        def fail(s):
            raise RuntimeError('push failed')
        with self.assertRaises(RuntimeError):
            notify.deliver([self.job], {'deliveries': {}}, 'url', self.now, fail, lambda *a: self.fail('sent'))

    def test_definite_rejection_retries(self):
        state = {'deliveries': {}}
        def reject(*args):
            raise urllib.error.HTTPError('url', 429, 'rate limit', {}, None)
        self.assertEqual(notify.deliver([self.job], state, 'url', self.now, lambda s: None, reject), 1)
        self.assertEqual(state['deliveries'][self.job['key']]['status'], 'retryable')
        notify.deliver([self.job], state, 'url', self.now, lambda s: None, lambda *a: None)
        self.assertEqual(state['deliveries'][self.job['key']]['status'], 'sent')

    def test_ambiguous_not_retried(self):
        state = {'deliveries': {}}
        def timeout(*args):
            raise TimeoutError()
        notify.deliver([self.job], state, 'url', self.now, lambda s: None, timeout)
        notify.deliver([self.job], state, 'url', self.now, lambda s: None, lambda *a: self.fail('duplicate'))
        self.assertEqual(state['deliveries'][self.job['key']]['status'], 'pending')

    def test_dry_run_no_secret_or_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / 'feed.json'
            feed.write_text('{"events": []}')
            with patch.object(notify, 'FEED', feed), patch.object(notify, 'locked', side_effect=AssertionError('state mutation')), patch.dict(os.environ, {'NTFY_URL': '', 'CORNERMAN_NOW': self.now.isoformat()}):
                self.assertEqual(notify.main(['dry-run']), 0)

    def test_test_no_production_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / 'feed.json'
            feed.write_text('{"events": []}')
            with patch.object(notify, 'FEED', feed), patch.object(notify, 'locked', side_effect=AssertionError('state mutation')), patch.object(notify, 'push') as push, patch.dict(os.environ, {'NTFY_URL': 'url'}):
                self.assertEqual(notify.main(['test']), 0)
                self.assertTrue(push.call_args.kwargs['test'])

    def test_parallel_lock_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            calls = []
            def run():
                with notify.locked(path):
                    state = notify.load_state(path)
                    notify.deliver([self.job], state, 'url', self.now, lambda s: notify.save_state(s, path), lambda *a: calls.append(1))
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                list(pool.map(lambda _: run(), range(2)))
            self.assertEqual(calls, [1])

    def test_no_dayof_no_unknown_imminent(self):
        e = {'id': 'ufc', 'org': 'UFC', 'tier': 'numbered', 'name': 'UFC', 'date': '2026-10-20T18:00:00Z'}
        jobs = notify.plan({'events': [e]}, self.now)
        self.assertTrue(all(j['key'].startswith('digest:') for j in jobs))

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text('broken')
            with self.assertRaises(ValueError):
                notify.load_state(path)

    def test_delayed_request_has_exact_epoch(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(notify.urllib.request, 'urlopen', return_value=Response()) as post:
            notify.push('https://ntfy.sh/topic', self.job, self.now)
            request = post.call_args.args[0]
            self.assertEqual(request.get_header('Delay'), str(int(notify.instant(self.job['at']).timestamp())))
            self.assertLessEqual(len(request.data), 4096)

    def test_sent_outcome_save_failure_leaves_pending_reservation(self):
        state = {'deliveries': {}}
        durable = {}
        calls = []
        def persist(s):
            if s['deliveries'][self.job['key']]['status'] == 'sent':
                raise RuntimeError('outcome push failed')
            durable.update(json.loads(json.dumps(s)))
        with self.assertRaises(RuntimeError):
            notify.deliver([self.job], state, 'url', self.now, persist, lambda *a: calls.append(1))
        notify.deliver([self.job], durable, 'url', self.now, lambda s: None, lambda *a: calls.append(2))
        self.assertEqual(calls, [1])

    def test_daily_parts_snapshot_in_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / 'feed.json'
            state = Path(tmp) / 'state.json'
            feed.write_text('{"events": []}')
            with patch.object(notify, 'FEED', feed), patch.object(notify, 'STATE', state), patch.object(notify, 'locked', return_value=notify.locked(state)), patch.object(notify, 'load_state', return_value={'version': 2, 'deliveries': {}}), patch.dict(os.environ, {'NTFY_URL': 'url', 'CORNERMAN_NOW': self.now.isoformat()}):
                # The frozen plan is persisted alongside the first reservation.
                with patch.object(notify, 'deliver', side_effect=lambda jobs, s, *a: (self.assertIn('2026-10-20', s['digests']) or 0)):
                    self.assertEqual(notify.main(['run']), 0)

    def test_imminent_can_schedule_across_midnight(self):
        now = datetime.fromisoformat('2026-10-21T04:40:00+00:00')
        e = {'id': 'ufc', 'name': 'UFC', 'org': 'UFC', 'tier': 'numbered', 'date': '2026-10-21', 'earliestBroadcastStart': '2026-10-21T07:00:00Z'}
        e['segments'] = [{'name': 'Main card', 'start': e['earliestBroadcastStart'], 'region': 'US', 'verifiedAt': now.isoformat(), 'platforms': [{'name': 'Paramount+', 'access': 'subscription'}]}]
        self.assertIn('ufc:imminent', [j['key'] for j in notify.plan({'events': [e]}, now)])

    def test_http_timeout_is_ambiguous(self):
        state = {'deliveries': {}}
        def reject(*args):
            raise urllib.error.HTTPError('url', 408, 'timeout', {}, None)
        notify.deliver([self.job], state, 'url', self.now, lambda s: None, reject)
        self.assertEqual(state['deliveries'][self.job['key']]['status'], 'pending')


    def test_late_digest_excludes_already_started(self):
        now = datetime.fromisoformat('2026-10-20T22:00:00+00:00')  # 17:00 CDT
        es = [{'id': 'past', 'name': 'Already started', 'date': '2026-10-20T18:00:00Z'},
              {'id': 'future', 'name': 'Upcoming card', 'date': '2026-10-21'}]
        body = ''.join(j['body'] for j in notify.plan({'events': es}, now) if j['key'].startswith('digest:'))
        self.assertNotIn('Already started', body)
        self.assertIn('Upcoming card', body)

    def test_frozen_digest_does_not_change_on_late_retry(self):
        state = {'deliveries': {}}
        first = notify.freeze_digest(state, [self.job], self.now)
        changed = dict(self.job, body='New afternoon events')
        again = notify.freeze_digest(state, [changed], self.now.replace(hour=22))
        self.assertEqual(again, first)
        self.assertEqual(again[0]['body'], 'Hello')

    def test_stale_rights_suppress_imminent_and_claims(self):
        e = {'id': 'u', 'org': 'UFC', 'tier': 'numbered', 'name': 'Old rights card',
             'date': '2026-10-20T15:00:00Z', 'coverageComplete': True,
             'segments': [{'name': 'Main card', 'start': '2026-10-20T15:00:00Z',
                           'verifiedAt': '2026-10-16T13:00:00Z', 'region': 'US',
                           'platforms': [{'name': 'Paramount+', 'access': 'subscription', 'covered': True, 'confirmed': True}]}]}
        jobs = notify.plan({'events': [e]}, self.now)
        self.assertFalse(any(':imminent' in j['key'] for j in jobs))
        self.assertNotIn('Included in your subscriptions', ''.join(j['body'] for j in jobs))

    def test_prune_retains_ambiguous_and_recent_history(self):
        state = {'deliveries': {
            'old-sent': {'status': 'sent', 'updated': '2026-08-01T00:00:00Z'},
            'old-rejected': {'status': 'retryable', 'updated': '2026-08-01T00:00:00Z'},
            'old-pending': {'status': 'pending', 'updated': '2026-08-01T00:00:00Z'},
            'old-reserved': {'status': 'reserved', 'updated': '2026-08-01T00:00:00Z'},
            'recent': {'status': 'sent', 'updated': self.now.isoformat()}},
            'digests': {'2026-08-01': [self.job], '2026-10-20': [self.job]}}
        self.assertTrue(notify.prune_state(state, self.now))
        self.assertEqual(set(state['deliveries']), {'old-pending', 'old-reserved', 'recent'})
        self.assertEqual(set(state['digests']), {'2026-10-20'})

    def test_separate_processes_lock_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, calls = str(Path(tmp) / 'state.json'), str(Path(tmp) / 'calls.txt')
            ctx = multiprocessing.get_context('spawn')
            ready = ctx.Event()
            processes = [ctx.Process(target=lock_process, args=(path, calls, self.job, self.now, ready)) for _ in range(2)]
            try:
                for process in processes:
                    process.start()
                ready.set()
                for process in processes:
                    process.join(10)
                    self.assertEqual(process.exitcode, 0)
                self.assertEqual(Path(calls).read_text(), 'sent\n')
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join()
                    process.close()
