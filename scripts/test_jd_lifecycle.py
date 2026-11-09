"""Independent synthetic regressions for status changes and safe product references."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_journal import build
from check_project import check
from collection_state import initialize, commit_page, collect
from journal_io import load, save
from test_jd_engine import jd_fixture


class JDLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'source'
        self.rows = jd_fixture(self.root)
        initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='jd')

    def tearDown(self):
        self.temp.cleanup()

    def batch(self, rows):
        return {'platform': 'jd', 'account_key': 'synthetic-alias', 'cursor': '1', 'next_cursor': '2',
                'orders': rows, 'evidence': {'source_url': 'https://order.jd.hk/center/list.action',
                                           'note': 'Synthetic status reobservation.'}}

    def cancelled(self):
        value = copy.deepcopy(self.rows[0])
        value.update(raw_status='已取消', is_success=False)
        return value

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_cancelled_old_success_no_longer_counted_but_history_and_media_retained(self):
        state = commit_page(self.root, self.batch([self.cancelled()]), clock=lambda: 0)
        self.assertEqual([o['order_id'] for o in load(self.root / 'orders.json')], [self.rows[1]['order_id']])
        receipt = load(next((self.root / 'collection-invalidations').glob('*.json')))
        self.assertEqual(receipt['previous_orders'][0]['raw_status'], '已完成')
        self.assertEqual(receipt['observed_non_success'][0]['raw_status'], '已取消')
        cached = load(next((self.root / 'collection-cache').glob('*.json')))
        self.assertIs(cached['orders'][0]['is_success'], False)
        self.assertEqual(state['pages'][0]['invalidated_orders'], 1)
        self.assertTrue((self.root / self.rows[0]['items'][0]['image_path']).is_file())

    def test_unknown_missing_or_contradictory_status_stops_without_file_changes(self):
        for changes in ({'raw_status': '需要复核的新状态', 'is_success': False},
                        {'raw_status': '', 'is_success': False}, {'raw_status': None, 'is_success': False},
                        {'raw_status': '等待收货', 'is_success': True}, {'raw_status': '已完成', 'is_success': False},
                        {'is_success': None}):
            value = {**self.rows[0], **changes}
            before = self.snapshot()
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'status'):
                commit_page(self.root, self.batch([value]), clock=lambda: 0)
            self.assertEqual(before, self.snapshot())

    def test_invalidations_replay_safely_at_each_write_boundary(self):
        for fail_name in ('collection-invalidations', 'orders.json', 'collection-state.json'):
            with self.subTest(boundary=fail_name), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                rows = jd_fixture(root)
                initialize(root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='jd')
                row = {**rows[0], 'is_success': False, 'raw_status': '已取消'}
                def interrupted(path, value):
                    path = Path(path)
                    if path.name == fail_name or path.parent.name == fail_name:
                        raise OSError('synthetic interruption')
                    return save(path, value)
                with patch('collection_state.save', side_effect=interrupted), self.assertRaises(OSError):
                    commit_page(root, self.batch([row]), clock=lambda: 0)
                result = collect(root, lambda _: self.fail('replay must use saved page'), max_pages=1, clock=lambda: 0)
                self.assertEqual(result['cache_hits'], 1)
                self.assertEqual(len(load(root / 'orders.json')), 1)
                receipt = load(next((root / 'collection-invalidations').glob('*.json')))
                self.assertEqual(receipt['previous_orders'][0]['raw_status'], '已完成')
                self.assertIs(receipt['observed_non_success'][0]['is_success'], False)

    def test_waiting_receipt_cannot_masquerade_as_completed_in_import(self):
        rows = copy.deepcopy(self.rows)
        rows[0].update(raw_status='等待收货', is_success=True)
        save(self.root / 'orders.json', rows)
        result = check(self.root, 'jd')
        self.assertFalse(result['ok'])
        self.assertTrue(any('exactly 已完成' in e for e in result['errors']))
        with self.assertRaisesRegex(ValueError, 'exactly 已完成'):
            build(self.root, Path(self.temp.name) / 'blocked', 'collage')

    def test_canonical_product_link_survives_checkpoint_and_safe_export(self):
        rows = copy.deepcopy(self.rows)
        url = 'https://item.jd.com/12345678.html'
        rows[0]['items'][0]['product_url'] = url
        commit_page(self.root, self.batch(rows), clock=lambda: 0)
        self.assertEqual(load(self.root / 'orders.json')[0]['items'][0]['product_url'], url)
        output = Path(self.temp.name) / 'output'
        build(self.root, output, 'collage')
        self.assertEqual(load(output / 'orders.json')[0]['items'][0]['product_url'], url)

    def test_unsafe_product_link_stops_commit_export_and_checker(self):
        urls = ('https://item.jd.com/12345678.html?pcdk=not-a-real-token',
                'https://item.jd.com/12345678.html#fragment', 'https://evil.test/12345678.html',
                'https://user:pass@item.jd.com/12345678.html', 'http://item.jd.com/12345678.html')
        for url in urls:
            rows = copy.deepcopy(self.rows)
            rows[0]['items'][0]['product_url'] = url
            with self.subTest(url=url):
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, 'product_url'):
                    commit_page(self.root, self.batch(rows), clock=lambda: 0)
                self.assertEqual(before, self.snapshot())
                save(self.root / 'orders.json', rows)
                self.assertFalse(check(self.root, 'jd')['ok'])
                with self.assertRaisesRegex(ValueError, 'product_url'):
                    build(self.root, Path(self.temp.name) / 'blocked', 'collage')
                save(self.root / 'orders.json', self.rows)


if __name__ == '__main__':
    unittest.main()
