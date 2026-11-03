"""Synthetic normal-browser batch tests; no actual Taobao or host tool access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from collect_taobao import configure_browser, collect_browser, resume_browser
from collection_state import collect, commit_page, initialize, merge_orders
from journal_io import load, save
from test_taobao_adapter import synthetic_list, synthetic_order, synthetic_row


class SinglePage:
    """Minimal one-page browser; js() returns the same fabricated raw payload."""
    def __init__(self, raw):
        self.raw = raw; self.calls = 0
    def js(self, script):
        self.calls += 1
        return json.dumps(self.raw, ensure_ascii=False)


class Clock:
    def __init__(self): self.now, self.waits = 100., []
    def __call__(self): return self.now
    def sleep(self, seconds): self.waits.append(seconds); self.now += seconds


class Browser:
    def __init__(self, pages=3):
        self.page, self.calls, self.actions, self.pages = 1, 0, [], {}
        for n in range(1, pages+1):
            raw = synthetic_list()
            raw.update(route_status='ready', orders=[synthetic_order(str(9000000000000000000+n))])
            raw['pagination'] = {'active':str(n), 'next_disabled':n==pages,
                                 'page_items':[str(n),str(n+1)] if n<pages else [str(n)]}
            self.pages[n] = raw
    def js(self, script): self.calls += 1; return json.dumps(self.pages[self.page], ensure_ascii=False)
    def advance(self, bu, target): self.actions.append(target); self.page=target


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.clock=Clock()
        save(self.root/'project_meta.json', {'platform':'taobao', 'requested_range':{'start':'2025-01-01','end':'2025-12-31'}})
    def tearDown(self): self.temp.cleanup()
    def configure(self, bu): return configure_browser(bu,self.root,'synthetic-account',clock=self.clock,sleep=self.clock.sleep)
    def batch(self, bu, **kwargs):
        return collect_browser(bu,self.root,bu.advance,clock=self.clock,sleep=self.clock.sleep,**kwargs)

    def test_first_page_is_saved_before_any_pagination_or_filter(self):
        bu=Browser(); result=self.configure(bu)
        self.assertTrue(result['first_page_saved']);self.assertEqual(result['saved_orders'],1)
        self.assertEqual(bu.actions,[]);self.assertEqual(load(self.root/'collection-state.json')['next_cursor'],'2')
        self.assertEqual(len(list((self.root/'collection-cache').glob('*.json'))),1)

    def test_31_pages_use_one_setup_and_six_bounded_batches(self):
        bu=Browser(31);self.configure(bu); batches=[]
        for _ in range(6): batches.append(self.batch(bu,max_pages=5,deadline_seconds=45))
        self.assertEqual(batches[-1]['status'],'complete');self.assertEqual(batches[-1]['saved_orders'],31)
        self.assertEqual(bu.actions,list(range(2,32)))
        self.assertEqual(len(load(self.root/'collection-state.json')['pages']),31)
        self.assertTrue(all(x['processed_pages']==5 for x in batches))
        self.assertTrue(all('虚构' not in json.dumps(x,ensure_ascii=False) for x in batches))
        self.assertGreaterEqual(sum(self.clock.waits),4*30)

    def test_fresh_process_resume_does_not_reread_or_skip_saved_pages(self):
        bu=Browser(5);self.configure(bu);self.batch(bu,max_pages=1)
        # Web page is still page 2 after committing it. New Python state reads cursor 3.
        result=self.batch(bu,max_pages=3)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['saved_orders'],5)
        self.assertEqual(bu.actions,[2,3,4,5])

    def test_loading_old_content_does_not_get_committed_as_new_page(self):
        bu=Browser();self.configure(bu)
        bu.pages[2]['orders']=deepcopy(bu.pages[1]['orders'])
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['status'],'handoff');self.assertEqual(result['saved_orders'],1)
        self.assertEqual(load(self.root/'collection-state.json')['next_cursor'],'2')
        calls=bu.calls;self.batch(bu,max_pages=1);self.assertEqual(bu.calls,calls)

    def test_status_changes_cannot_disguise_stale_order_ids(self):
        bu=Browser();self.configure(bu)
        bu.pages[2]['orders']=deepcopy(bu.pages[1]['orders'])
        bu.pages[2]['orders'][0]['status']='交易关闭'
        self.assertEqual(self.batch(bu,max_pages=1)['status'],'handoff')
        self.assertEqual(len(load(self.root/'orders.json')),1)

    def test_duplicate_source_ids_stop_cleanly_without_skipping_a_page(self):
        bu=Browser();self.configure(bu)
        bu.pages[2]['orders'].append(deepcopy(bu.pages[2]['orders'][0]))
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['status'],'handoff');self.assertEqual(result['next_cursor'],'2')
        self.assertEqual(result['saved_orders'],1)

    def test_obscured_click_failure_stops_once_preserving_first_page(self):
        bu=Browser();self.configure(bu)
        def obscured(*args):bu.actions.append('attempt');raise TimeoutError('do not include private page text')
        result=collect_browser(bu,self.root,obscured,clock=self.clock,sleep=self.clock.sleep)
        self.assertEqual(result['status'],'handoff');self.assertEqual(bu.actions,['attempt'])
        self.assertNotIn('private page text',json.dumps(result))
        self.assertEqual(result['next_cursor'],'2')
        self.assertEqual(resume_browser(bu,self.root,'normal UI obstruction resolved',clock=self.clock,sleep=self.clock.sleep)['status'],'ready')
        self.assertEqual(self.batch(bu)['status'],'complete')

    def test_page_numbers_and_short_page_are_not_end_evidence(self):
        bu=Browser(3);self.configure(bu)
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['status'],'ready');self.assertEqual(result['next_cursor'],'3')
        self.assertEqual(self.batch(bu)['status'],'complete')

    def test_unknown_next_state_does_not_guess_terminal(self):
        bu=Browser();bu.pages[1]['pagination']['next_disabled']=None
        self.assertEqual(self.configure(bu)['status'],'handoff');self.assertFalse((self.root/'orders.json').exists())

    def test_empty_page_requires_boundary_review_not_auto_completion(self):
        bu=Browser(2);self.configure(bu);bu.pages[2]['orders']=[];bu.pages[2]['route_status']='empty_or_unrecognized'
        result=self.batch(bu)
        self.assertEqual(result['status'],'verify_boundary');self.assertEqual(result['saved_orders'],1)

    def test_wrong_position_and_wrong_identity_are_not_silently_restarted(self):
        bu=Browser(5);self.configure(bu);bu.page=4
        self.assertEqual(self.batch(bu)['reason'],'resume_position_required')
        self.assertEqual(bu.actions,[])
        with self.assertRaises(ValueError):configure_browser(bu,self.root,'another-account',clock=self.clock,sleep=self.clock.sleep)

    def test_small_time_budget_yields_without_advancing(self):
        bu=Browser();self.configure(bu)
        result=self.batch(bu,deadline_seconds=1)
        self.assertEqual(result['status'],'cooldown');self.assertEqual(bu.actions,[])
        self.assertEqual(result['next_cursor'],'2')

    def test_invalid_page_payload_never_advances_checkpoint(self):
        bu=Browser();self.configure(bu);bu.pages[2]['orders'][0]['order_id_text']='bad';bu.pages[2]['orders'][0]['detail_url']=None
        self.assertEqual(self.batch(bu)['status'],'handoff')
        self.assertEqual(load(self.root/'collection-state.json')['next_cursor'],'2')

    def test_invalid_batch_budget_is_rejected_before_browser_actions(self):
        bu=Browser();self.configure(bu);calls=bu.calls
        for args in ({'max_pages':11},{'max_pages':0},{'deadline_seconds':121}):
            with self.assertRaises(ValueError):self.batch(bu,**args)
        self.assertEqual(bu.calls,calls)

    def test_item_url_basis_is_bound_reused_and_cannot_change(self):
        raw = synthetic_list()
        raw['route_status'] = 'ready'
        order = synthetic_order('9000000000000000010', rows=[synthetic_row()])
        order['rows'][0]['item_url'] = 'https://item.taobao.com/item.htm?id=555555555555'
        raw['orders'] = [order]
        raw['pagination'] = {'active':'1', 'next_disabled':True, 'page_items':['1']}
        bu = SinglePage(raw)
        result = configure_browser(bu, self.root, 'synthetic-account',
                                   item_id_basis='item_url',
                                   clock=self.clock, sleep=self.clock.sleep)
        self.assertTrue(result['first_page_saved'])
        self.assertEqual(load(self.root/'browser-collection.json')['item_id_basis'],
                         'item_url')
        saved = load(self.root/'orders.json')[0]
        self.assertEqual(saved['items'][0]['item_id'], '555555555555')
        self.assertEqual(saved['items'][0]['item_id_basis'], 'item_url_id')

        # The bound basis cannot be switched later on the same project.
        with self.assertRaises(ValueError):
            configure_browser(SinglePage(raw), self.root, 'synthetic-account',
                              item_id_basis='row_index',
                              clock=self.clock, sleep=self.clock.sleep)
        with self.assertRaises(ValueError):
            configure_browser(SinglePage(raw), self.root, 'synthetic-account',
                              item_id_basis='guess',
                              clock=self.clock, sleep=self.clock.sleep)


class CacheTests(unittest.TestCase):
    def test_cached_page_replay_does_not_wait_or_call_the_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initialize(root,'alias','2025-01-01','2025-12-31')
            state=load(root/'collection-state.json');state['next_allowed_at']=999999;save(root/'collection-state.json',state)
            key=hashlib.sha256(b'1').hexdigest()
            save(root/'collection-cache'/f'{key}.json',{'account_key':'alias','cursor':'1','next_cursor':None,'end_verified':True,'orders':[],
                'evidence':{'source_url':'https://buyer.example.test/orders','note':'synthetic cached evidence'}})
            result=collect(root,lambda _:self.fail('must replay without network'),clock=lambda:100,
                           sleep=lambda _:self.fail('cache must not wait for network cooldown'))
            self.assertEqual(result['cache_hits'],1);self.assertEqual(result['status'],'complete')

    def test_corrupt_cache_is_preserved_and_blocks_network_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initialize(root,'alias','2025-01-01','2025-12-31')
            key=hashlib.sha256(b'1').hexdigest();p=root/'collection-cache'/f'{key}.json';p.parent.mkdir();p.write_text('{broken',encoding='utf-8')
            result=collect(root,lambda _:self.fail('do not replace corrupt evidence silently'))
            self.assertEqual(result['reason'],'invalid_cached_page');self.assertEqual(p.read_text(encoding='utf-8'),'{broken')

    def test_list_replay_does_not_erase_detail_precision_or_known_money(self):
        old={'order_id':'1','placed_at':'2025-05-19T12:30:00+08:00','date_precision':'second',
             'paid_amount':'10.00','refund_amount':'2.00','amount_basis':'original_paid','items':[]}
        new={**old,'placed_at':'2025-05-19T00:00:00+08:00','date_precision':'day',
             'paid_amount':None,'refund_amount':None,'amount_basis':'unknown'}
        merged=merge_orders([old],[new])[0]
        self.assertEqual(merged['placed_at'],old['placed_at']);self.assertEqual(merged['paid_amount'],'10.00')
        self.assertEqual(merged['refund_amount'],'2.00');self.assertEqual(merged['amount_basis'],'original_paid')


if __name__=='__main__':unittest.main()
