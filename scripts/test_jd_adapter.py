"""Synthetic offline JD normalization tests; no real account or network data."""
import copy
import unittest

from jd_adapter import (LIST_PAGE_SCRIPT, extract_order_id, is_success_status,
                        normalize_list_page, parse_item_url_id,
                        parse_observed_amount, parse_quantity,
                        resolve_item_identities, validate_list_url)


def synthetic_row(name='Synthetic plant pot', quantity='共 1 件', sku='12345678'):
    return {'name': name, 'quantity_text': quantity,
            'item_url': f'https://item.jd.com/{sku}.html' if sku else None,
            'image_url': 'https://img10.360buyimg.com/n0/s500x500_jfs/synthetic.png'}


def synthetic_order(oid='900000000000000001', status='已完成', rows=None):
    return {'order_id_text': '订单号：' + oid, 'order_date': '2026-11-08 12:34:56',
            'status': status, 'payment_text': '¥ 22 . 90', 'detail_url': None,
            'is_split_order': False, 'parent_order_id_text': None,
            'rows': rows if rows is not None else [synthetic_row()]}


def synthetic_list():
    return {'source_url': 'https://order.jd.hk/center/list.action',
            'route_status': 'ready', 'selected_period': '近3个月订单',
            'pagination': {'active': '1', 'next_disabled': False},
            'orders': [synthetic_order(), synthetic_order('900000000000000002', '等待收货')]}


class JDFields(unittest.TestCase):
    def test_exact_status(self):
        self.assertTrue(is_success_status('已完成'))
        for other in ('等待收货', '已取消', '待付款', '交易成功', '已完成 待审核', '', None):
            self.assertFalse(is_success_status(other))

    def test_order_id_strings_and_ambiguity(self):
        self.assertEqual(extract_order_id('订单号：900000000000000001'), '900000000000000001')
        self.assertEqual(extract_order_id('900000000000000001'), '900000000000000001')
        for value in ('2026-11-08', '订单号123', '订单号123456 订单号234567', '', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                extract_order_id(value)

    def test_observed_amount_never_paid(self):
        self.assertEqual(parse_observed_amount('¥ 22 . 90'), '22.90')
        self.assertEqual(parse_observed_amount('￥0.00'), '0.00')
        for value in (None, '', '¥10 ¥20', '原价￥30现价￥20', '-10', 'NaN'):
            self.assertIsNone(parse_observed_amount(value))
        with self.assertRaises(ValueError):
            parse_observed_amount(22.9)

    def test_quantity_not_default_one(self):
        self.assertEqual(parse_quantity('共 12 件'), 12)
        for value in (None, '', '共 0 件', '共 1.5 件', '共1件 共2件', 'x2'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_quantity(value)

    def test_only_actual_jd_product_link_can_offer_sku(self):
        self.assertEqual(parse_item_url_id('https://item.jd.com/12345678.html'), '12345678')
        for value in ('https://evil.test/12345678.html', 'http://item.jd.com/12345678.html',
                      'https://item.jd.com/recommend/12345678.html', 'https://item.jd.com/abc.html',
                      'https://user:pass@item.jd.com/12345678.html', None):
            self.assertIsNone(parse_item_url_id(value))
        self.assertIsNone(resolve_item_identities([synthetic_row(), synthetic_row()]))
        self.assertIsNone(resolve_item_identities([synthetic_row(sku=None)]))

    def test_order_list_source_is_strict(self):
        for host in ('order.jd.com', 'order.jd.hk'):
            self.assertEqual(validate_list_url(f'https://{host}/center/list.action'), f'https://{host}/center/list.action')
        for value in ('https://order.jd.com.evil.test/center/list.action',
                      'http://order.jd.com/center/list.action', 'https://order.jd.com/other',
                      'https://user:pass@order.jd.com/center/list.action',
                      'https://order.jd.com:8443/center/list.action', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_list_url(value)


class JDNormalization(unittest.TestCase):
    def normalize(self, raw=None):
        return normalize_list_page(raw or synthetic_list(), 'synthetic-local-alias', '1', 'Synthetic observation', next_cursor='2')

    def test_platform_time_and_missing_detail_link(self):
        batch = self.normalize()
        order = batch['orders'][0]
        self.assertEqual(batch['platform'], 'jd')
        self.assertEqual(order['platform'], 'jd')
        self.assertEqual(order['placed_at'], '2026-11-08T12:34:56+08:00')
        self.assertEqual(order['date_precision'], 'second')
        self.assertEqual(order['url'], batch['evidence']['source_url'])
        self.assertIsNone(order['paid_amount'])
        self.assertIsNone(order['refund_amount'])
        self.assertEqual(order['amount_basis'], 'unknown')
        self.assertEqual(order['observed_amount'], '22.90')
        self.assertFalse(batch['orders'][1]['is_success'])
        self.assertEqual(order['items'][0]['image_path'], None)
        self.assertEqual(order['items'][0]['source_url'], synthetic_row()['image_url'])
        self.assertEqual(order['items'][0]['product_url'], 'https://item.jd.com/12345678.html')

    def test_product_url_is_distinct_from_order_source_and_strips_tracking(self):
        raw = synthetic_list()
        raw['orders'][0]['rows'][0]['item_url'] += '?pcdk=SECRET_TRACKING#trace'
        order = self.normalize(raw)['orders'][0]
        self.assertEqual(order['items'][0]['product_url'], 'https://item.jd.com/12345678.html')
        self.assertEqual(order['url'], raw['source_url'])
        self.assertNotIn('SECRET_TRACKING', str(order))

    def test_split_banner_is_relationship_not_another_paid_order(self):
        raw = synthetic_list()
        for order in raw['orders']:
            order.update(is_split_order=True, parent_order_id_text='订单号：900000000000000099')
        batch = self.normalize(raw)
        self.assertEqual(len(batch['orders']), 2)
        self.assertTrue(all(o['parent_order_id'] == '900000000000000099' for o in batch['orders']))
        self.assertTrue(all(o['paid_amount'] is None for o in batch['orders']))
        raw['orders'][0]['parent_order_id_text'] = None
        self.assertTrue(self.normalize(raw)['orders'][0]['split_relation_uncertain'])
        raw['orders'][0]['parent_order_id_text'] = raw['orders'][0]['order_id_text']
        with self.assertRaises(ValueError):
            self.normalize(raw)

    def test_multi_item_identity_uses_sku_only_when_all_unique(self):
        raw = synthetic_list()
        raw['orders'][0]['rows'] = [synthetic_row(sku='12345678'), synthetic_row(sku='23456789')]
        items = self.normalize(raw)['orders'][0]['items']
        self.assertEqual([i['item_id'] for i in items], ['12345678', '23456789'])
        raw['orders'][0]['rows'][1]['item_url'] = raw['orders'][0]['rows'][0]['item_url']
        items = self.normalize(raw)['orders'][0]['items']
        self.assertTrue(all(i['item_id_basis'] == 'order_row_index' for i in items))
        self.assertEqual(len({i['item_id'] for i in items}), 2)

    def test_fail_closed_on_missing_fields_and_duplicate_cards(self):
        mutations = [
            lambda r: r['orders'][0].update(order_date='2026-02-30 12:00:00'),
            lambda r: r['orders'][0].update(status=''),
            lambda r: r['orders'][0].update(order_id_text=''),
            lambda r: r['orders'][0]['rows'][0].update(name=''),
            lambda r: r['orders'][0]['rows'][0].update(quantity_text=''),
            lambda r: r['orders'].append(copy.deepcopy(r['orders'][0])),
            lambda r: r['orders'][0].update(detail_url='https://evil.test/private'),
        ]
        for mutation in mutations:
            raw = synthetic_list(); mutation(raw)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.normalize(raw)

    def test_missing_price_and_image_are_explicit_unknown(self):
        raw = synthetic_list()
        raw['orders'][0].update(payment_text=None)
        raw['orders'][0]['rows'][0]['image_url'] = None
        order = self.normalize(raw)['orders'][0]
        self.assertIsNone(order['observed_amount'])
        self.assertIsNone(order['items'][0]['source_url'])
        self.assertIsNone(order['items'][0]['origin'])

    def test_lazy_placeholder_remains_unavailable_for_normal_reobservation(self):
        raw = synthetic_list()
        raw['orders'][0]['rows'][0].update(image_url=None, image_pending=True)
        item = self.normalize(raw)['orders'][0]['items'][0]
        self.assertEqual(item['image_status'], 'unavailable')
        self.assertIn('normally scroll', item['image_error'])

    def test_dom_script_never_reads_page_blob_or_contacts(self):
        for forbidden in ('document.cookie', 'outerHTML', 'innerHTML', 'deliveryAndExpress', 'localStorage', '.click('):
            self.assertNotIn(forbidden, LIST_PAGE_SCRIPT)


if __name__ == '__main__':
    unittest.main()
