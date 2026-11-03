"""Offline regression of the merged collector against the unchanged renderer."""
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

from build_journal import build, prepare
from check_project import check
from collection_state import initialize, commit_page, collect
from journal_io import load, save
from manage_media import plan, download
from taobao_adapter import normalize_list_page
from test_build_journal import fixture, synthetic_png
from test_taobao_adapter import synthetic_list


class Response(io.BytesIO):
    def __init__(self, url, data):
        super().__init__(data)
        self.url = url
    def geturl(self):
        return self.url


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        rows = normalize_list_page(synthetic_list(), 'alias', '1', 'synthetic')['orders']
        self.row = rows[0]
    def tearDown(self):
        self.temp.cleanup()

    def test_all_item_images_are_bound_deduped_and_cached_without_changing_bytes(self):
        rows = []
        for n in range(9):
            row = copy.deepcopy(self.row)
            row['order_id'] = str(9000000000000000100 + n)
            row['items'] = [row['items'][0]]
            row['items'][0]['source_url'] = 'https://img.example.test/%s.png' % (n % 6)
            rows.append(row)
        save(self.root / 'orders.json', rows)
        result = plan(self.root, ['img.example.test'])
        self.assertEqual((result['jobs'], result['unique_urls']), (9, 6))
        lock, barrier = threading.Lock(), threading.Barrier(3)
        class Good:
            calls = active = peak = 0
            def open(self, req, **kwargs):
                with lock:
                    self.calls += 1
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                    first = self.calls <= 3
                if first:
                    barrier.wait(timeout=5)
                time.sleep(.01)
                with lock:
                    self.active -= 1
                return Response(req.full_url, synthetic_png())
        opener = Good()
        result = download(self.root, opener=opener)
        self.assertTrue(result['ok'], result)
        self.assertEqual((opener.calls, opener.peak, result['completed_jobs']), (6, 3, 9))
        saved = load(self.root / 'orders.json')
        paths = {r['items'][0]['image_path'] for r in saved}
        self.assertEqual(len(paths), 1)
        self.assertEqual((self.root / next(iter(paths))).read_bytes(), synthetic_png())
        self.assertTrue(download(self.root, opener=opener)['ok'])
        self.assertEqual(opener.calls, 6)

    def test_denial_stops_new_work_without_losing_collected_orders(self):
        rows = []
        for n in range(10):
            row = copy.deepcopy(self.row)
            row['order_id'] = str(9000000000000000200 + n)
            row['items'] = [row['items'][0]]
            row['items'][0]['source_url'] = 'https://img.example.test/%d.png' % n
            rows.append(row)
        save(self.root / 'orders.json', rows)
        plan(self.root, ['img.example.test'])
        class Denied:
            calls = 0
            def open(self, req, **kwargs):
                self.calls += 1
                raise urllib.error.HTTPError(req.full_url, 429, 'limited', {}, None)
        opener = Denied()
        result = download(self.root, opener=opener)
        self.assertFalse(result['ok'])
        self.assertLessEqual(opener.calls, 3)
        self.assertEqual(len(load(self.root / 'orders.json')), 10)

    def test_invalid_response_missing_source_and_redirect_do_not_count_as_downloaded(self):
        for content, redirect in ((b'<html>login</html>', None), (synthetic_png(), 'https://other.example.test/a')):
            save(self.root / 'orders.json', [self.row])
            plan(self.root, ['img.example.test'])
            class Bad:
                def open(self, req, **kwargs):
                    return Response(redirect or req.full_url, content)
            self.assertFalse(download(self.root, opener=Bad())['ok'])
        row = copy.deepcopy(self.row)
        row['items'][0].update(source_url=None, origin=None)
        row['items'] = [row['items'][0]]
        save(self.root / 'orders.json', [row])
        self.assertEqual(len(plan(self.root, ['img.example.test'])['missing_sources']), 1)
        self.assertFalse(download(self.root)['ok'])

    def test_crash_replays_cached_page_without_network_or_duplicates(self):
        initialize(self.root, 'alias', '2025-01-01', '2025-12-31')
        batch = normalize_list_page(synthetic_list(), 'alias', '1', 'synthetic', next_cursor='2')
        def interrupted(path, value):
            if Path(path).name == 'collection-state.json':
                raise OSError('synthetic crash before checkpoint')
            return save(path, value)
        with patch('collection_state.save', side_effect=interrupted):
            with self.assertRaises(OSError):
                commit_page(self.root, batch)
        result = collect(self.root, lambda _: self.fail('cached page must not request network'),
                         max_pages=1, clock=lambda: 0)
        self.assertEqual((result['next_cursor'], result['cache_hits']), ('2', 1))
        self.assertEqual(len(load(self.root / 'orders.json')), 1)

    def test_collected_orders_feed_original_collage_calendar_share_and_plans(self):
        fixture(self.root, 'taobao')
        initialize(self.root, 'alias', '2016-01-01', '2026-10-30')
        batch = normalize_list_page(synthetic_list(), 'alias', '1', 'synthetic')
        batch['end_verified'] = True
        # Replace only the synthetic fixture's placeholder record.
        save(self.root / 'orders.json', [])
        commit_page(self.root, batch)
        plan(self.root, ['img.example.test'])
        class Good:
            def open(self, req, **kwargs):
                return Response(req.full_url, synthetic_png())
        self.assertTrue(download(self.root, opener=Good())['ok'])
        rows = load(self.root / 'orders.json')
        oid, image = rows[0]['order_id'], rows[0]['items'][0]['image_path']
        story = load(self.root / 'story.json')
        for entry in [story['overview'], *story['themes'], *story['findings'], *story['plans']]:
            entry['source_ids'] = [oid]
        story['themes'][0]['excerpt'] = rows[0]['items'][0]['name']
        story['visuals'] = {image: {'kind': 'object', 'title': '合成花盆'}}
        save(self.root / 'story.json', story)
        self.assertTrue(check(self.root, 'taobao', 'data')['ok'])
        before = (self.root / 'story.json').read_bytes()
        out = Path(self.temp.name) / 'built'
        build(self.root, out, 'collage')
        data = prepare(self.root, 'collage')
        self.assertEqual(len(data['story']['plans']), 1)
        self.assertGreater(len(data['story']['overview']['images']), 0)
        self.assertTrue((out / image).is_file())
        runtime = (out / 'journal-data.js').read_text(encoding='utf-8')
        self.assertIn('data:image/png;base64,', runtime)
        for name in ('scrapbook.css', 'scrapbook.js', 'app.js', 'core.js'):
            self.assertEqual((out / name).read_bytes(),
                             (Path(__file__).resolve().parents[1] / 'assets/starter' / name).read_bytes())
        self.assertEqual((self.root / 'story.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
