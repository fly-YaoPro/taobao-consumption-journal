"""Synthetic normal-browser behavior tests; no platform/account/network access."""
import copy
from pathlib import Path
import hashlib
import tempfile
import unittest

from collect_jd import configure_browser, collect_browser, resume_browser
from journal_io import load, save
from test_jd_adapter import synthetic_list, synthetic_order


class Clock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value
    def sleep(self, seconds): self.value += seconds


class Browser:
    def __init__(self, years=(2026, 2025), pages=2):
        self.data = {}
        for year in years:
            label = f'{year}年订单'
            self.data[label] = {}
            for page in range(1, pages + 1):
                raw = synthetic_list()
                raw.update(selected_period=label, pagination={'active': str(page), 'next_disabled': page == pages})
                raw['orders'] = [synthetic_order(f'900000{year}{page:08d}')]
                raw['orders'][0]['order_date'] = f'{year}-05-19 12:00:00'
                self.data[label][page] = raw
        self.period, self.page = next(iter(self.data)), 1
        self.actions, self.reads, self.transitions = [], 0, []
        self.fail = None
        self.stale_period = self.stale_page = False

    def js(self, script):
        self.reads += 1
        if self.fail: raise RuntimeError(self.fail)
        if self.transitions: return copy.deepcopy(self.transitions.pop(0))
        return copy.deepcopy(self.data[self.period][self.page])

    def select(self, label):
        self.actions.append(('period', label))
        old = copy.deepcopy(self.data[self.period][self.page])
        self.period, self.page = label, 1
        if self.stale_period:
            old['selected_period'] = label
            old['pagination']['active'] = '1'
            self.transitions = [old, old]

    def advance(self, page):
        self.actions.append(('page', self.period, page))
        old = copy.deepcopy(self.data[self.period][self.page])
        self.page = page
        if self.stale_page:
            old['pagination']['active'] = str(page)
            self.transitions = [old, old]


class JDCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.clock = Clock()
        save(self.root / 'project_meta.json', {'platform': 'jd', 'requested_range': {'start':'2025-01-01','end':'2026-12-31'}})
        self.periods = [{'label':f'{y}年订单', 'start':f'{y}-01-01', 'end':f'{y}-12-31'} for y in (2026,2025)]

    def tearDown(self): self.temp.cleanup()
    def configure(self, bu, **extra):
        return configure_browser(bu, self.root, 'synthetic-alias', self.periods, lambda b,l:b.select(l), clock=self.clock, sleep=self.clock.sleep, **extra)
    def batch(self, bu, **extra):
        return collect_browser(bu,self.root,lambda b,l:b.select(l),lambda b,p:b.advance(p),clock=self.clock,sleep=self.clock.sleep, **extra)

    def test_first_page_saved_and_complete_only_after_all_years(self):
        bu=Browser(); initial=self.configure(bu)
        self.assertTrue(initial['first_page_saved']); self.assertEqual(initial['saved_orders'],1)
        self.assertIn(':0:2',initial['next_cursor'])
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['status'],'ready');self.assertEqual(result['periods_verified'],1)
        self.assertEqual(result['selected_period'],'2025年订单')
        result=self.batch(bu)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['periods_verified'],2)
        self.assertEqual(result['saved_orders'],4)
        self.assertEqual(sorted(o['placed_at'] for o in load(self.root/'orders.json')),[o['placed_at'] for o in load(self.root/'orders.json')])

    def test_default_recent_filter_cannot_be_declared_ten_year_coverage(self):
        bu=Browser(); self.periods[0]['label']='近3个月订单'
        with self.assertRaises(ValueError): self.configure(bu)
        self.assertEqual(bu.actions,[]);self.assertFalse((self.root/'collection-state.json').exists())

    def test_gap_overlap_and_label_year_mismatch_rejected(self):
        for mutate in (lambda p:p[1].update(start='2025-01-02'),lambda p:p[0].update(start='2025-12-31'),lambda p:p[0].update(label='2024年订单')):
            original=copy.deepcopy(self.periods);mutate(self.periods)
            with self.assertRaises(ValueError):self.configure(Browser())
            self.periods=original

    def test_checkpoint_binds_account_range_period_order_and_platform(self):
        bu=Browser();self.configure(bu)
        with self.assertRaises(ValueError):configure_browser(bu,self.root,'other-alias',self.periods,lambda b,l:b.select(l))
        with self.assertRaises(ValueError):configure_browser(bu,self.root,'synthetic-alias',list(reversed(self.periods)),lambda b,l:b.select(l))
        meta=load(self.root/'project_meta.json');meta['platform']='taobao';save(self.root/'project_meta.json',meta)
        with self.assertRaises(ValueError):self.batch(bu)

    def test_wrong_existing_order_platform_leaves_new_configuration_absent(self):
        save(self.root/'orders.json',[{'platform':'taobao','order_id':'synthetic-foreign-order'}])
        with self.assertRaises(ValueError):self.configure(Browser())
        self.assertFalse((self.root/'jd-browser-collection.json').exists())
        self.assertFalse((self.root/'collection-state.json').exists())

    def test_wrong_existing_checkpoint_account_leaves_configuration_unchanged(self):
        bu=Browser();self.configure(bu)
        config_before=(self.root/'jd-browser-collection.json').read_bytes()
        state_before=(self.root/'collection-state.json').read_bytes()
        with self.assertRaises(ValueError):configure_browser(bu,self.root,'different-alias',self.periods,lambda b,l:b.select(l))
        self.assertEqual((self.root/'jd-browser-collection.json').read_bytes(),config_before)
        self.assertEqual((self.root/'collection-state.json').read_bytes(),state_before)

    def test_period_label_changes_before_old_year_cards_settle(self):
        bu=Browser();bu.stale_period=True;self.configure(bu)
        self.batch(bu,max_pages=1)
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['saved_orders'],3)
        self.assertEqual(len(load(self.root/'collection-state.json')['pages']),3)

    def test_page_number_changes_before_old_cards_settle(self):
        bu=Browser();self.configure(bu);bu.stale_page=True
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['saved_orders'],2)
        self.assertEqual(len(load(self.root/'collection-state.json')['pages']),2)

    def test_loading_transitional_empty_is_not_terminal(self):
        bu=Browser();self.configure(bu)
        blank=copy.deepcopy(bu.data[bu.period][2]);blank.update(route_status='loading',orders=[],pagination={'active':None,'next_disabled':None})
        old_advance=bu.advance
        def advance(page): old_advance(page);bu.transitions=[blank,blank]
        bu.advance=advance
        self.assertEqual(self.batch(bu,max_pages=1)['saved_orders'],2)

    def test_stuck_cards_block_without_committing_or_skipping(self):
        bu=Browser();self.configure(bu)
        bu.data[bu.period][2]['orders']=copy.deepcopy(bu.data[bu.period][1]['orders'])
        before=load(self.root/'collection-state.json')['next_cursor']
        result=self.batch(bu)
        self.assertEqual(result['status'],'handoff');self.assertEqual(result['next_cursor'],before)
        self.assertEqual(result['saved_orders'],1)

    def test_wrong_annual_records_never_mark_year_complete(self):
        bu=Browser();self.configure(bu);self.batch(bu,max_pages=1)
        for raw in bu.data['2025年订单'].values():raw['orders'][0]['order_date']='2026-05-19 12:00:00'
        result=self.batch(bu)
        self.assertEqual(result['status'],'handoff');self.assertEqual(result['periods_verified'],1)

    def test_empty_year_needs_explicit_normal_ui_verification(self):
        bu=Browser(pages=1);bu.data['2026年订单'][1].update(orders=[],route_status='empty_or_unrecognized')
        self.assertEqual(self.configure(bu)['reason'],'empty_jd_year_requires_normal_ui_verification')
        self.assertFalse((self.root/'orders.json').exists())

    def test_verified_empty_year_can_advance_without_inventing_orders(self):
        bu=Browser(pages=1);bu.data['2026年订单'][1].update(orders=[],route_status='empty_or_unrecognized')
        result=self.configure(bu,verify_empty_period=lambda b,p:{'verified':True,'label':p['label'],'note':'Synthetic normal UI empty-year evidence'})
        self.assertEqual(result['saved_orders'],0);self.assertEqual(result['periods_verified'],1)
        self.assertEqual(self.batch(bu)['status'],'complete')

    def test_observed_normal_empty_year_without_pagination_can_complete_its_period(self):
        bu=Browser(pages=1)
        bu.data['2026年订单'][1].update(orders=[],route_status='empty',empty_message='没有相关订单哦~去首页看看查看全部订单',pagination={'active':None,'next_disabled':None})
        result=self.configure(bu,verify_empty_period=lambda b,p:{'verified':True,'label':p['label'],'note':'Synthetic host independently verified this selected year finished loading and remained normally empty'})
        self.assertTrue(result['first_page_saved']);self.assertEqual(result['periods_verified'],1)
        self.assertEqual(result['saved_orders'],0);self.assertEqual(self.batch(bu)['status'],'complete')

    def test_known_empty_message_without_callback_stays_pending(self):
        bu=Browser(pages=1)
        bu.data['2026年订单'][1].update(orders=[],route_status='empty',empty_message='没有相关订单哦~去首页看看查看全部订单',pagination={'active':None,'next_disabled':None})
        result=self.configure(bu)
        self.assertEqual(result['status'],'handoff')
        self.assertEqual(result['reason'],'empty_jd_year_requires_normal_ui_verification')
        self.assertEqual(result['periods_verified'],0)
        self.assertFalse((self.root/'orders.json').exists())

    def test_empty_verification_requires_exact_label_true_and_actual_text_note(self):
        for proof in ({'verified':True,'label':'2025年订单','note':'Other year'},
                      {'verified':1,'label':'2026年订单','note':'not boolean true'},
                      {'verified':True,'label':'2026年订单','note':''},
                      {'verified':True,'label':'2026年订单','note':123}):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                save(root/'project_meta.json',load(self.root/'project_meta.json'))
                bu=Browser(pages=1)
                bu.data['2026年订单'][1].update(orders=[],route_status='empty',empty_message='没有相关订单哦~去首页看看查看全部订单',pagination={'active':None,'next_disabled':None})
                result=configure_browser(bu,root,'synthetic-alias',self.periods,lambda b,l:b.select(l),verify_empty_period=lambda b,p:proof,clock=self.clock,sleep=self.clock.sleep)
                self.assertEqual(result['status'],'handoff')
                self.assertFalse((root/'orders.json').exists())

    def test_empty_callback_that_finishes_loading_real_cards_cannot_skip_the_year(self):
        bu=Browser(pages=1)
        completed=copy.deepcopy(bu.data['2026年订单'][1])
        bu.data['2026年订单'][1].update(orders=[],route_status='empty',empty_message='没有相关订单哦~去首页看看查看全部订单',pagination={'active':None,'next_disabled':None})
        def verify(b,p):
            b.data['2026年订单'][1]=completed
            return {'verified':True,'label':p['label'],'note':'Synthetic response changed during verification'}
        result=self.configure(bu,verify_empty_period=verify)
        self.assertEqual(result['status'],'handoff')
        self.assertEqual(result['reason'],'empty_jd_year_verification_changed_reobserve')
        self.assertEqual(result['periods_verified'],0)

    def test_unrecognized_blank_structure_never_equals_normal_empty_year(self):
        bu=Browser(pages=1)
        bu.data['2026年订单'][1].update(orders=[],route_status='empty_or_unrecognized',pagination={'active':None,'next_disabled':None})
        result=self.configure(bu)
        self.assertEqual(result['status'],'handoff');self.assertEqual(result['periods_verified'],0)

    def test_unverified_empty_route_without_observed_message_is_rejected(self):
        bu=Browser(pages=1)
        bu.data['2026年订单'][1].update(orders=[],route_status='empty',empty_message='Unknown blank layout',pagination={'active':None,'next_disabled':None})
        self.assertEqual(self.configure(bu)['status'],'handoff')

    def test_unknown_pagination_blocks(self):
        bu=Browser();bu.data[bu.period][1]['pagination']['next_disabled']=None
        self.assertEqual(self.configure(bu)['status'],'handoff')
        self.assertFalse((self.root/'orders.json').exists())

    def test_lazy_placeholder_requires_normal_scroll_not_false_missing_completion(self):
        bu=Browser();bu.data[bu.period][1]['orders'][0]['rows'][0].update(image_pending=True,image_url=None)
        self.assertEqual(self.configure(bu)['reason'],'jd_lazy_images_pending_normal_scroll_and_reobserve')

    def test_normal_scroll_callback_can_load_images_before_save(self):
        bu=Browser();bu.data[bu.period][1]['orders'][0]['rows'][0].update(image_pending=True,image_url=None)
        def prepare(b):b.data[b.period][b.page]['orders'][0]['rows'][0].update(image_pending=False,image_url='https://img10.360buyimg.com/n0/s500x500_jfs/synthetic.png')
        self.assertTrue(self.configure(bu,prepare_page=prepare)['first_page_saved'])
        self.assertTrue(load(self.root/'orders.json')[0]['items'][0]['source_url'])

    def test_budget_respects_cooldown_without_extra_ui_calls(self):
        bu=Browser();self.configure(bu);before=len(bu.actions)
        result=self.batch(bu,deadline_seconds=1)
        self.assertEqual(result['status'],'cooldown');self.assertEqual(len(bu.actions),before)
        for extra in ({'max_pages':0},{'max_pages':11},{'deadline_seconds':121}):
            with self.assertRaises(ValueError):self.batch(bu,**extra)

    def test_resume_requires_pending_year_and_position(self):
        bu=Browser();self.configure(bu);bu.fail='Synthetic tool timeout';self.batch(bu);bu.fail=None
        bu.period='2025年订单'
        result=resume_browser(bu,self.root,'Synthetic verification',clock=self.clock,sleep=self.clock.sleep)
        self.assertEqual(result['reason'],'jd_resume_position_required')
        bu.period='2026年订单'
        self.assertEqual(resume_browser(bu,self.root,'Synthetic verification',clock=self.clock,sleep=self.clock.sleep)['status'],'ready')
        self.assertEqual(self.batch(bu)['status'],'complete')

    def test_empty_year_resume_then_collect_without_pagination_still_requires_verification(self):
        bu=Browser(pages=1)
        bu.data['2025年订单'][1].update(orders=[],route_status='empty',empty_message='没有相关订单哦~去首页看看查看全部订单',pagination={'active':None,'next_disabled':None})
        self.configure(bu)
        blocked=self.batch(bu)
        self.assertEqual(blocked['reason'],'empty_jd_year_requires_normal_ui_verification')
        resumed=resume_browser(bu,self.root,'Synthetic host rechecked this selected empty year',clock=self.clock,sleep=self.clock.sleep)
        self.assertEqual(resumed['status'],'ready')
        without_callback=self.batch(bu)
        self.assertEqual(without_callback['reason'],'empty_jd_year_requires_normal_ui_verification')
        resume_browser(bu,self.root,'Synthetic host rechecked again',clock=self.clock,sleep=self.clock.sleep)
        completed=self.batch(bu,verify_empty_period=lambda b,p:{'verified':True,'label':p['label'],'note':'Synthetic selected year finished loading and normally displayed no orders'})
        self.assertEqual(completed['status'],'complete')
        self.assertEqual(completed['periods_verified'],2)
        self.assertEqual(completed['saved_orders'],1)

    def test_non_success_records_not_in_saved_order_count(self):
        bu=Browser(pages=1);bu.data['2026年订单'][1]['orders'][0]['status']='等待收货'
        self.assertEqual(self.configure(bu)['saved_orders'],0)
        self.assertEqual(self.batch(bu)['saved_orders'],1)

    def test_period_cursor_namespaces_page_caches(self):
        bu=Browser(pages=1);self.configure(bu);self.batch(bu)
        pages=load(self.root/'collection-state.json')['pages']
        self.assertEqual(len(pages),2);self.assertNotEqual(pages[0]['cache'],pages[1]['cache'])
        self.assertTrue(all('jd:' in p['cursor'] for p in pages))

    def test_cache_replay_after_crash_uses_same_period_without_browser_or_cooldown(self):
        bu=Browser();self.configure(bu)
        before=load(self.root/'collection-state.json')
        self.batch(bu,max_pages=1)
        before['next_allowed_at']=999999
        save(self.root/'collection-state.json',before)
        bu.fail='must not read the browser while replaying a complete cache'
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['cache_hits'],1);self.assertEqual(result['processed_pages'],1)
        self.assertEqual(result['saved_orders'],2);self.assertEqual(result['selected_period'],'2025年订单')

    def test_different_period_cached_payload_cannot_replace_pending_cursor(self):
        bu=Browser(pages=1);self.configure(bu)
        state=load(self.root/'collection-state.json')
        wrong=load(self.root/state['pages'][0]['cache'])
        key=hashlib.sha256(state['next_cursor'].encode()).hexdigest()
        save(self.root/'collection-cache'/f'{key}.json',wrong)
        before=state['next_cursor']
        result=self.batch(bu,max_pages=1)
        self.assertEqual(result['status'],'handoff');self.assertEqual(result['next_cursor'],before)
        self.assertEqual(result['saved_orders'],1)


if __name__=='__main__':unittest.main()
