"""Offline synthetic JD fixtures only. This is not a live-account result."""
import copy
import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from build_journal import build, prepare
from check_project import check
from collection_state import initialize, commit_page, collect, merge_orders
from journal_io import load, save
from privacy_filter import safe_metadata


def fixture_png(shade=128):
    def chunk(tag, value):
        return struct.pack('>I', len(value)) + tag + value + struct.pack('>I', zlib.crc32(tag + value) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 80, 80, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + bytes([shade]) * 80) * 80)) + chunk(b'IEND', b''))


def jd_fixture(root):
    """A valid physical PNG fixture and two invented orders, never real purchases."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'images').mkdir(exist_ok=True)
    (root / 'images/fixture.png').write_bytes(fixture_png())
    save(root / 'project_meta.json', {'schema_version': 1, 'platform': 'jd', 'title': '京东合成夹具手帐',
        'mode': 'selected', 'timezone': 'Asia/Shanghai', 'requested_range': {'start': '2025-01-01', 'end': '2026-12-31'},
        'plan_year': 2027, 'synthetic_demo': True})
    save(root / 'coverage.json', [{'year': 2025, 'status': 'selected'}, {'year': 2026, 'status': 'selected'}])
    rows = []
    for n, (category, name, day) in enumerate((('居家', '合成测试收纳盒', '2025-05-19'), ('文具', '合成测试铅笔', '2026-08-03')), 1):
        rows.append({'platform': 'jd', 'order_id': f'fixture-jd-{n}', 'placed_at': day + 'T12:00:00+08:00',
            'raw_status': '已完成', 'is_success': True, 'currency': 'CNY', 'paid_amount': '10.00',
            'refund_amount': None, 'amount_basis': 'original_paid', 'category': category,
            'url': 'https://order.jd.hk/center/list.action', 'items': [{'item_id': f'fixture-item-{n}',
                'name': name, 'spec': None, 'quantity': 1, 'image_path': 'images/fixture.png',
                'image_status': 'saved', 'origin': 'user_provided', 'provided_reference': '合成测试图片，非真实账号采集'}]})
    save(root / 'orders.json', rows)
    ids = [r['order_id'] for r in rows]
    save(root / 'story.json', {
        'overview': {'headline': '合成夹具里的两样物件', 'text': '这是离线回归夹具，用于检查真实模板、图片和交互，不是真实消费经历。',
            'source_ids': ids, 'image_paths': ['images/fixture.png']},
        'themes': [{'id': 'fixture-theme', 'title': '检查已收录的物件', 'text': '两条虚构订单分别用于日历与跨年搜索检查。',
            'source_ids': ids, 'image_paths': ['images/fixture.png'], 'layout': 'A'}],
        'findings': [{'title': '两类测试物件', 'text': '合成夹具包含居家与文具，用于品类筛选检查。', 'source_ids': ids}],
        'plans': [{'id': 'fixture-plan', 'title': '核对已有物件清单', 'reason': '这两条合成记录用于检查建议、编辑和保存。',
            'source_ids': ids, 'month': '', 'done': False}],
        'visuals': {'images/fixture.png': {'kind': 'object', 'title': '合成测试物件'}}})
    return rows


class JDEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'source'
        self.rows = jd_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_jd_build_keeps_platform_images_calendar_plans_and_share(self):
        self.assertTrue(check(self.root, 'jd')['ok'])
        before = self.snapshot()
        output = Path(self.temp.name) / 'output'
        result = build(self.root, output, 'collage')
        self.assertEqual(result['records'], 2)
        runtime = (output / 'journal-data.js').read_text('utf-8')
        data = json.loads(runtime[len('window.JOURNAL_DATA = '):].strip().rstrip(';'))
        self.assertEqual(data['meta']['platform'], 'jd')
        self.assertTrue(all(r['platform'] == 'jd' for r in load(output / 'orders.json')))
        self.assertEqual(len(data['records']), 2)
        self.assertEqual(len(data['story']['plans']), 1)
        self.assertEqual(len(data['share_images']), 1)
        self.assertTrue(data['share_images'][0]['data_url'].startswith('data:image/png;base64,'))
        self.assertEqual((output / 'images/fixture.png').read_bytes(), fixture_png())
        self.assertGreater(load(output / 'media-report.json')['overview_image_slots'], 0)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(check(output, 'jd', 'final')['ok'], 'a final share PNG must still be actually exported')

    def test_metadata_is_not_relabelled_taobao(self):
        self.assertEqual(safe_metadata(load(self.root / 'project_meta.json'))['platform'], 'jd')
        self.assertFalse(check(self.root, 'taobao')['ok'])

    def test_observed_order_amount_is_not_promoted_to_paid_amount(self):
        rows = copy.deepcopy(self.rows)
        rows[0].update(paid_amount=None, refund_amount=None, amount_basis='unknown',
            observed_amount='19.00', observed_amount_label='总额', parent_order_id='synthetic-parent')
        save(self.root / 'orders.json', rows)
        self.assertTrue(check(self.root, 'jd')['ok'])
        output = Path(self.temp.name) / 'observed-only'
        build(self.root, output, 'collage')
        exported = load(output / 'orders.json')[0]
        self.assertEqual(exported['observed_amount'], '19.00')
        self.assertEqual(exported['observed_amount_label'], '总额')
        self.assertEqual(exported['parent_order_id'], 'synthetic-parent')
        self.assertIsNone(exported['paid_amount'])
        self.assertEqual(exported['amount_basis'], 'unknown')

    def test_uncertain_split_relation_survives_checkpoint_and_privacy_export(self):
        rows = copy.deepcopy(self.rows)
        rows[0].update(split_relation_uncertain=True, parent_order_id=None)
        rows[1].update(split_relation_uncertain=False, parent_order_id='synthetic-confirmed-parent')
        save(self.root / 'orders.json', [])
        initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='jd')
        commit_page(self.root, self.batch(rows), clock=lambda: 0)
        saved = load(self.root / 'orders.json')
        self.assertIs(saved[0]['split_relation_uncertain'], True)
        self.assertIs(saved[1]['split_relation_uncertain'], False)
        self.assertIsNone(saved[0]['parent_order_id'])
        cached = load(next((self.root / 'collection-cache').glob('*.json')))
        self.assertIs(cached['orders'][0]['split_relation_uncertain'], True)
        output = Path(self.temp.name) / 'uncertain-split-export'
        build(self.root, output, 'collage')
        exported = load(output / 'orders.json')
        self.assertIs(exported[0]['split_relation_uncertain'], True)
        self.assertIs(exported[1]['split_relation_uncertain'], False)
        self.assertIsNone(exported[0]['parent_order_id'])

    def test_missing_or_different_platform_fails_before_build_output(self):
        for platform in (None, 'taobao'):
            rows = copy.deepcopy(self.rows)
            if platform is None:
                rows[0].pop('platform')
            else:
                rows[0]['platform'] = platform
            save(self.root / 'orders.json', rows)
            self.assertFalse(check(self.root, 'jd')['ok'])
            output = Path(self.temp.name) / 'blocked'
            with self.assertRaisesRegex(ValueError, 'platform'):
                build(self.root, output, 'collage')
            self.assertFalse(output.exists())

    def test_jd_keeps_private_order_exclusion_and_source_gate(self):
        private = copy.deepcopy(self.rows[0])
        private.update(order_id='fixture-private')
        (self.root / 'images/private.png').write_bytes(fixture_png(32))
        private['items'][0].update(name='合成测试内裤', image_path='images/private.png')
        save(self.root / 'orders.json', self.rows + [private])
        data = prepare(self.root, 'collage')
        self.assertEqual(data['privacy_report']['excluded_parent_orders'], 1)
        self.assertNotIn('fixture-private', {r['order_id'] for r in data['_export_orders']})
        story = load(self.root / 'story.json')
        story['plans'][0]['source_ids'].append('fixture-private')
        save(self.root / 'story.json', story)
        with self.assertRaisesRegex(ValueError, '隐私边界'):
            prepare(self.root, 'collage')

    def test_jd_keeps_image_and_empty_plan_gates(self):
        for mutation, fragment in ((lambda s: s.pop('visuals'), '未完成页面展示映射'),
                                   (lambda s: s.update(plans=[]), 'story.plans')):
            jd_fixture(self.root)
            story = load(self.root / 'story.json'); mutation(story); save(self.root / 'story.json', story)
            with self.assertRaisesRegex(ValueError, fragment):
                prepare(self.root, 'collage')
            final = check(self.root, 'jd', 'final')
            self.assertTrue(any(fragment in e for e in final['errors']), final)
        jd_fixture(self.root)
        (self.root / 'images/fixture.png').write_text('<html>not a product image</html>', encoding='utf-8')
        self.assertFalse(check(self.root, 'jd')['ok'])
        with self.assertRaisesRegex(ValueError, '图片文件无效'):
            prepare(self.root, 'collage')

    def batch(self, rows=None, platform='jd'):
        return {'platform': platform, 'account_key': 'synthetic-alias', 'cursor': '1', 'next_cursor': '2',
            'orders': self.rows if rows is None else rows,
            'evidence': {'source_url': 'https://order.jd.hk/center/list.action', 'note': 'Synthetic fixture only.'}}

    def test_checkpoint_platform_and_minimal_cache(self):
        save(self.root / 'orders.json', [])
        state = initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='jd')
        self.assertEqual(state['platform'], 'jd')
        batch = self.batch()
        batch['orders'][0]['cookie'] = 'not-a-real-credential'
        batch['orders'][0]['raw_dom'] = '<main>synthetic</main>'
        state = commit_page(self.root, batch, clock=lambda: 0)
        self.assertEqual(state['next_cursor'], '2')
        saved = load(self.root / 'orders.json')
        self.assertEqual(saved[0]['platform'], 'jd')
        cached = load(next((self.root / 'collection-cache').glob('*.json')))
        self.assertEqual(cached['platform'], 'jd')
        self.assertNotIn('cookie', json.dumps(cached))
        self.assertNotIn('raw_dom', json.dumps(cached))

    def test_platform_conflicts_do_not_pollute_old_files(self):
        initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='jd')
        before = self.snapshot()
        for rows, platform in ((self.rows, 'taobao'), ([{**self.rows[0], 'platform': 'taobao'}], 'jd')):
            with self.assertRaisesRegex(ValueError, 'platform'):
                commit_page(self.root, self.batch(rows, platform))
            self.assertEqual(before, self.snapshot())
        with self.assertRaisesRegex(ValueError, 'platform'):
            initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='taobao')
        self.assertEqual(before, self.snapshot())

    def test_changed_metadata_rejects_before_cached_page_or_browser(self):
        initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='jd')
        meta = load(self.root / 'project_meta.json'); meta['platform'] = 'taobao'; save(self.root / 'project_meta.json', meta)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'platform'):
            collect(self.root, lambda _: self.fail('must not read a browser on platform mismatch'))
        self.assertEqual(before, self.snapshot())

    def test_same_id_other_platform_never_overwrites(self):
        old = [{**self.rows[0], 'platform': 'taobao'}]
        incoming = [{**self.rows[0], 'paid_amount': '900.00'}]
        original = copy.deepcopy(old)
        with self.assertRaisesRegex(ValueError, 'platform'):
            merge_orders(old, incoming)
        self.assertEqual(old, original)
        # Different IDs do not accidentally opt this release into mixed projects.
        incoming[0]['order_id'] = 'different-id'
        with self.assertRaisesRegex(ValueError, 'platform'):
            merge_orders(old, incoming)

    def test_jd_metadata_required_and_legacy_checkpoint_cannot_rebind(self):
        (self.root / 'project_meta.json').unlink()
        save(self.root / 'orders.json', [])
        with self.assertRaisesRegex(ValueError, 'project_meta'):
            initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31', platform='jd')
        self.assertFalse((self.root / 'collection-state.json').exists())
        initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31')
        state = load(self.root / 'collection-state.json'); state.pop('platform'); save(self.root / 'collection-state.json', state)
        jd_fixture(self.root)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'platform'):
            collect(self.root, lambda _: self.fail('must fail before reading browser'))
        self.assertEqual(before, self.snapshot())

    def test_legacy_taobao_untagged_rows_still_resume(self):
        meta = load(self.root / 'project_meta.json'); meta['platform'] = 'taobao'; save(self.root / 'project_meta.json', meta)
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row.pop('platform')
            row.update(raw_status='交易成功', url='https://buyertrade.taobao.com/')
        save(self.root / 'orders.json', rows)
        initialize(self.root, 'synthetic-alias', '2025-01-01', '2026-12-31')
        state = load(self.root / 'collection-state.json'); state.pop('platform'); save(self.root / 'collection-state.json', state)
        batch = self.batch(rows); batch.pop('platform')
        committed = commit_page(self.root, batch, clock=lambda: 0)
        self.assertEqual(committed['platform'], 'taobao')
        self.assertEqual(len(load(self.root / 'orders.json')), 2)


if __name__ == '__main__':
    unittest.main()
