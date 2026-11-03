"""Synthetic offline tests for the normal-browser Taobao adapter.

All payloads are fabricated to mirror the observed DOM shape; they contain no
real order ids, account names or personal data.
"""
import json
import unittest

from taobao_adapter import (
    LIST_PAGE_SCRIPT, DETAIL_PAGE_SCRIPT,
    extract_order_id, parse_paid_amount, parse_quantity, parse_spec,
    build_item_id, is_success_status, normalize_list_page, normalize_detail,
    merge_detail_into_order, apply_date_filter,
    parse_item_url_id, resolve_item_identities,
)


def synthetic_row(name="虚构测试花盆", price="￥10.00￥12.00x1",
                  spec="虚构灰色款", image="https://img.example.test/a_200x200.jpg"):
    return {
        "image_url": image,
        "item_url": "https://item.example.test/item.htm?id=100",
        "name": name,
        "info_lines": [spec, "虚构服务标签 7天无理由"],
        "price_text": price,
    }


def synthetic_order(oid="9000000000000000001", date="2025-05-19",
                    status="交易成功", payment="实付款￥10.00含运费:￥0.00手机订单",
                    rows=None):
    return {
        "order_date": date,
        "order_id_text": "订单号: " + oid,
        "shop": "虚构测试店铺",
        "status": status,
        "detail_url": "https://trade.example.test/detail.htm?biz_order_id=" + oid,
        "payment_text": payment,
        "operations_text": "虚构操作",
        "rows": rows if rows is not None else [synthetic_row()],
    }


def synthetic_list():
    return {
        "source_url": "https://buyertrade.taobao.com/trade/itemlist/list_bought_items.htm",
        "pagination": {"active": "1", "page_items": ["1", "2"], "next_disabled": False},
        "orders": [
            synthetic_order(rows=[synthetic_row("虚构花盆A"), synthetic_row("虚构花盆B")]),
            synthetic_order("9000000000000000002", "2025-05-18", "交易关闭",
                            "实付款￥20.00含运费:￥0.00"),
            synthetic_order("9000000000000000003", "2025-05-17", "卖家已发货",
                            "实付款￥30.00含运费:￥0.00",
                            rows=[synthetic_row("虚构大件", "￥30.00￥40.00x30")]),
        ],
    }


class FieldParsingTests(unittest.TestCase):
    def test_extract_order_id_text_and_url(self):
        self.assertEqual(extract_order_id("订单号: 9000000000000000001",
                                          "https://x/detail.htm?biz_order_id=9000000000000000001"),
                         "9000000000000000001")
        self.assertEqual(extract_order_id("订单号: 9000000000000000001"),
                         "9000000000000000001")
        self.assertEqual(extract_order_id("", "https://x/detail.htm?bizOrderId=9000000000000000002"),
                         "9000000000000000002")

    def test_extract_order_id_mismatch_and_missing(self):
        with self.assertRaises(ValueError):
            extract_order_id("订单号: 9000000000000000001",
                             "https://x/detail.htm?biz_order_id=9000000000000000009")
        with self.assertRaises(ValueError):
            extract_order_id("无编号", None)

    def test_amount_quantity_spec_and_item_id(self):
        self.assertEqual(parse_paid_amount("实付款￥59.77含运费:￥0.00"), "59.77")
        self.assertIsNone(parse_paid_amount("没有金额"))
        self.assertEqual(parse_quantity("￥1￥2x30"), 30)
        self.assertEqual(parse_quantity("￥1 × 3"), 3)
        for value in (None, "无数量", "x0", "x1 x2"):
            with self.assertRaises(ValueError):
                parse_quantity(value)
        self.assertEqual(parse_spec(["规格款", "服务"]), "规格款")
        self.assertIsNone(parse_spec([]))
        self.assertEqual(build_item_id("9000000000000000001", 0), "9000000000000000001-00")
        self.assertTrue(is_success_status("交易成功"))
        self.assertFalse(is_success_status("交易关闭"))

    def test_parse_item_url_id_accepts_only_trusted_https_links(self):
        self.assertEqual(parse_item_url_id("https://item.taobao.com/item.htm?id=678901234567"),
                         "678901234567")
        self.assertEqual(
            parse_item_url_id("https://detail.tmall.com/item.htm?id=123456789012&skuId=9"),
            "123456789012")
        for bad in (
            "http://item.taobao.com/item.htm?id=123456789012",          # not https
            "https://item.taobao.com/item.htm?x=1",                     # no id
            "https://item.taobao.com/item.htm?id=12345",                # too short
            "https://item.taobao.com/item.htm?id=12345678901234567890", # too long
            "https://item.taobao.com/item.htm?id=abc1234567",           # not digits
            "https://user:pass@item.taobao.com/item.htm?id=123456789012",  # credentials
            "", None,
        ):
            self.assertIsNone(parse_item_url_id(bad), bad)

    def test_resolve_item_identities_requires_complete_unique_ids(self):
        rows = [{"item_url": "https://item.example.test/item.htm?id=111111111111"},
                {"item_url": "https://item.example.test/item.htm?id=222222222222"}]
        self.assertEqual(resolve_item_identities(rows),
                         ["111111111111", "222222222222"])
        duplicate = rows + [{"item_url": "https://item.example.test/item.htm?id=111111111111"}]
        self.assertIsNone(resolve_item_identities(duplicate))
        missing = [{"item_url": "https://item.example.test/"}] + rows[1:]
        self.assertIsNone(resolve_item_identities(missing))
        self.assertIsNone(resolve_item_identities([]))


class NormalizationTests(unittest.TestCase):
    def test_normalize_list_page_keeps_status_and_builds_rows(self):
        batch = normalize_list_page(synthetic_list(), "account-a", "1",
                                    "虚构测试说明", next_cursor="2")
        self.assertEqual(batch["cursor"], "1")
        self.assertEqual(batch["next_cursor"], "2")
        self.assertEqual(len(batch["orders"]), 3)
        first = batch["orders"][0]
        self.assertEqual(first["placed_at"], "2025-05-19T00:00:00+08:00")
        self.assertEqual(first["raw_placed_at"], "2025-05-19")
        self.assertEqual(first["currency"], "CNY")
        self.assertEqual(first["paid_amount"], "10.00")
        self.assertEqual(first["amount_basis"], "original_paid")
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(first["items"][0]["item_id"], "9000000000000000001-00")
        self.assertEqual(first["items"][0]["item_id_basis"], "order_row_index")
        self.assertEqual(first["items"][0]["image_status"], "unavailable")
        # Non-success orders are retained with their real status.
        self.assertFalse(batch["orders"][1]["is_success"])
        self.assertFalse(batch["orders"][2]["is_success"])
        self.assertEqual(batch["orders"][2]["items"][0]["quantity"], 30)

    def test_normalize_list_page_rejects_bad_source(self):
        bad = synthetic_list()
        bad["source_url"] = "http://insecure.example"
        with self.assertRaises(ValueError):
            normalize_list_page(bad, "account-a", "1", "虚构")

    def test_item_url_basis_uses_real_ids_and_safely_falls_back(self):
        real = synthetic_list()
        rows = real["orders"][0]["rows"]
        rows[0]["item_url"] = "https://item.example.test/item.htm?id=333333333333"
        rows[1]["item_url"] = "https://item.example.test/item.htm?id=444444444444"
        batch = normalize_list_page(real, "account-a", "1", "虚构",
                                    next_cursor="2", item_id_basis="item_url")
        items = batch["orders"][0]["items"]
        self.assertEqual([i["item_id"] for i in items],
                         ["333333333333", "444444444444"])
        self.assertTrue(all(i["item_id_basis"] == "item_url_id" for i in items))

        # Default synthetic rows share id=100 (duplicate): the order keeps row index.
        fallback = normalize_list_page(synthetic_list(), "account-a", "1", "虚构",
                                       item_id_basis="item_url")["orders"][0]["items"]
        self.assertEqual([i["item_id"] for i in fallback],
                         ["9000000000000000001-00", "9000000000000000001-01"])
        self.assertTrue(all(i["item_id_basis"] == "order_row_index" for i in fallback))

        with self.assertRaises(ValueError):
            normalize_list_page(synthetic_list(), "account-a", "1", "虚构",
                                item_id_basis="guess")

    def test_normalize_detail_and_merge(self):
        raw_detail = {
            "source_url": "https://trade.example/detail.htm",
            "main_image": "https://img.example.test/a_200x200.jpg",
            "times": {"创建时间": "2025-05-19 12:30:45", "付款时间": "2025-05-19 12:31:00"},
            "amounts": {"商品总价": "12.00", "实付款": "10.00"},
        }
        detail = normalize_detail(raw_detail)
        self.assertEqual(detail["placed_at"], "2025-05-19T12:30:45+08:00")
        self.assertEqual(detail["paid_amount"], "10.00")
        order = normalize_list_page(synthetic_list(), "account-a", "1", "虚构")["orders"][0]
        merged = merge_detail_into_order(order, detail)
        self.assertEqual(merged["placed_at"], "2025-05-19T12:30:45+08:00")
        self.assertEqual(merged["paid_amount"], "10.00")
        # Disagreement is flagged, not silently overwritten.
        bad = dict(detail)
        bad["paid_amount"] = "99.00"
        flagged = merge_detail_into_order(order, bad)
        self.assertEqual(flagged["amount_basis"], "unknown")
        self.assertTrue(flagged['amount_review_required'])
        self.assertIn("不一致", flagged["amount_note"])


class FakeBrowser:
    """Records the css/click sequence used by the date filter."""
    def __init__(self):
        self.calls = []

    def css(self, selector, match=None):
        self.calls.append(("css", selector))
        return ("loc", selector)

    def click(self, target):
        self.calls.append(("click", target))


class DateFilterTests(unittest.TestCase):
    def test_click_sequence_and_validation(self):
        fake = FakeBrowser()
        with self.assertRaisesRegex(ValueError, 'optional'):
            apply_date_filter(fake, "2025-05-01", "2025-05-31")
        self.assertEqual(fake.calls, [])
        verified = lambda bu, start, end: {'verified':True, 'applied_range':{'start':start,'end':end}}
        self.assertTrue(apply_date_filter(fake, "2025-05-01", "2025-05-31", verified)['verified'])
        with self.assertRaisesRegex(ValueError, 'not verified'):
            apply_date_filter(fake, "2025-05-01", "2025-05-31", lambda *args: {'verified':False})
        with self.assertRaises(ValueError):
            apply_date_filter(FakeBrowser(), "2025-05-31", "2025-05-01")
        with self.assertRaises(ValueError):
            apply_date_filter(FakeBrowser(), "bad", "2025-05-31")


class ScriptPresenceTests(unittest.TestCase):
    def test_scripts_are_read_only(self):
        self.assertIn("trade-bought-list-order-container", LIST_PAGE_SCRIPT)
        self.assertIn("detailInfoContent", DETAIL_PAGE_SCRIPT)
        # The adapter must not attempt to read credentials or cookies.
        self.assertNotIn("cookie", LIST_PAGE_SCRIPT.lower())
        self.assertNotIn("password", DETAIL_PAGE_SCRIPT.lower())


if __name__ == "__main__":
    unittest.main()
