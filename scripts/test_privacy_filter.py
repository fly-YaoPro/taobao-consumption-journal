"""Offline synthetic privacy/export regression tests; no real account data."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from build_journal import build, prepare
from privacy_filter import sensitive_text, product_sensitive
from test_build_journal import fixture, write, synthetic_png


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        fixture(self.root, "taobao")
        self.out = Path(self.temp.name) / "public"

    def tearDown(self):
        self.temp.cleanup()

    def load(self, file):
        return json.loads((self.root / file).read_text(encoding="utf-8"))

    def private_order(self, name="测试私密内裤", oid="withheld-secret-id", image=False):
        order = {"order_id": oid, "placed_at": "2025-05-21T09:00:00+08:00", "is_success": True,
                 "paid_amount": "123.45", "items": [{"item_id": "private-item", "name": name,
                 "image_path": "images/private-product.png" if image else None}]}
        if image:
            (self.root / "images").mkdir(exist_ok=True)
            (self.root / "images/private-product.png").write_bytes(synthetic_png())
        orders = self.load("orders.json") + [order]
        write(self.root, "orders.json", orders)
        return order

    def all_output_text(self):
        return "\n".join(p.read_text(encoding="utf-8") for p in self.out.rglob("*")
                         if p.is_file() and p.suffix in {".json", ".js", ".html"})

    def test_private_underwear_removed_from_every_export_but_raw_untouched(self):
        self.private_order(image=True)
        before = {p.name: p.read_bytes() for p in self.root.glob("*.json")}
        build(self.root, self.out, "collage")
        text = self.all_output_text()
        for token in ("测试私密内裤", "withheld-secret-id", "private-item", "123.45", "private-product.png"):
            self.assertNotIn(token, text)
        self.assertFalse((self.out / "images/private-product.png").exists())
        self.assertEqual(len(json.loads((self.out / "orders.json").read_text(encoding="utf-8"))), 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.glob("*.json")})
        self.assertTrue((self.root / "images/private-product.png").exists())

    def test_ordinary_socks_and_adult_books_not_filtered(self):
        for title in ("纯棉运动袜", "成人英语教材", "胸针收纳盒", "健康生活笔记本", "Brass bookend"):
            self.assertFalse(product_sensitive({"name": title}), title)
        for title in ("女士文胸", "男士平角裤", "成人用品", "私密护理液", "排卵试纸", "cotton underwear", "sports bra"):
            self.assertTrue(product_sensitive({"name": title}), title)

    def test_explicit_item_excludes_whole_mixed_order(self):
        order = self.private_order(name="正常名称但用户不愿展示")
        orders = self.load("orders.json")
        orders[-1]["items"].append({"item_id": "normal-second-item", "name": "普通毛巾"})
        write(self.root, "orders.json", orders)
        write(self.root, "privacy.json", {"exclude_items": [{"order_id": order["order_id"], "item_id": "private-item"}]})
        build(self.root, self.out, "collage")
        self.assertNotIn("普通毛巾", self.all_output_text())
        self.assertFalse((self.out / "privacy.json").exists())

    def test_explicit_order_and_inline_flags_work(self):
        self.private_order(name="某件普通物品")
        write(self.root, "privacy.json", {"exclude_order_ids": ["withheld-secret-id"]})
        self.assertEqual(len(prepare(self.root, "collage")["records"]), 1)
        write(self.root, "privacy.json", {})
        orders = self.load("orders.json")
        orders[-1]["items"][0]["exclude_from_export"] = True
        write(self.root, "orders.json", orders)
        self.assertEqual(len(prepare(self.root, "collage")["records"]), 1)

    def test_missing_exclusion_id_is_not_ignored(self):
        write(self.root, "privacy.json", {"exclude_order_ids": ["wrong-id"]})
        with self.assertRaisesRegex(ValueError, "不一致"):
            build(self.root, self.out, "collage")
        self.assertFalse(self.out.exists())

    def test_mixed_story_reference_stops_and_error_contains_no_private_details(self):
        order = self.private_order()
        story = self.load("story.json")
        story["overview"]["source_ids"].append(order["order_id"])
        write(self.root, "story.json", story)
        with self.assertRaisesRegex(ValueError, "Agent") as caught:
            build(self.root, self.out, "collage")
        self.assertNotIn(order["order_id"], str(caught.exception))
        self.assertNotIn(order["items"][0]["name"], str(caught.exception))
        self.assertFalse(self.out.exists())

    def test_nested_notes_and_plans_cannot_retain_private_sources(self):
        self.private_order()
        for field in ("plans", "findings"):
            story = self.load("story.json")
            original = copy.deepcopy(story)
            story[field][0]["source_ids"].append("withheld-secret-id")
            write(self.root, "story.json", story)
            with self.assertRaises(ValueError):
                prepare(self.root, "collage")
            write(self.root, "story.json", original)

    def test_unreferenced_private_visual_map_is_not_packaged(self):
        self.private_order(image=True)
        story = self.load("story.json")
        story["visuals"] = {"images/private-product.png": {"kind": "object", "title": "私密样本"}}
        write(self.root, "story.json", story)
        build(self.root, self.out, "collage")
        self.assertNotIn("private-product", self.all_output_text())

    def test_raw_metadata_and_unknown_fields_never_copied(self):
        orders = self.load("orders.json")
        orders[0].update(address="private-address-marker", raw_html="private-html-marker", receiver="private-name-marker")
        orders[0]["items"][0]["debug_payload"] = "private-debug-marker"
        write(self.root, "orders.json", orders)
        meta = self.load("project_meta.json")
        meta["target"] = {"uid": "private-account-marker"}
        meta["coverage_note"] = "private-coverage-marker"
        write(self.root, "project_meta.json", meta)
        story = self.load("story.json")
        story["private_notes"] = "private-story-marker"
        write(self.root, "story.json", story)
        build(self.root, self.out, "collage")
        for marker in ("private-address-marker", "private-html-marker", "private-name-marker", "private-debug-marker", "private-account-marker", "private-coverage-marker", "private-story-marker"):
            self.assertNotIn(marker, self.all_output_text())

    def test_private_story_text_rejected_even_if_id_not_linked(self):
        story = self.load("story.json")
        story["overview"]["text"] = "经常购买私密护理用品。"
        write(self.root, "story.json", story)
        with self.assertRaisesRegex(ValueError, "隐私边界"):
            prepare(self.root, "collage")

    def test_all_filtered_does_not_build_empty_journal(self):
        orders = self.load("orders.json")
        orders[0]["items"][0]["name"] = "测试内裤"
        write(self.root, "orders.json", orders)
        with self.assertRaises(ValueError):
            build(self.root, self.out, "collage")
        self.assertFalse(self.out.exists())

    def test_report_is_aggregate_only_and_not_publish_authorization(self):
        self.private_order()
        build(self.root, self.out, "collage")
        report = json.loads((self.out / "privacy-report.json").read_text())
        self.assertEqual(report["excluded_parent_orders"], 1)
        self.assertFalse(report["deployment_authorized"])
        self.assertFalse(report["automatic_detection_is_complete"])
        self.assertTrue(report["semantic_review_required"])
        self.assertNotIn("withheld", json.dumps(report))

    def test_private_image_alias_cannot_be_reintroduced(self):
        self.private_order(image=True)
        (self.root / "images/alias.png").write_bytes((self.root / "images/private-product.png").read_bytes())
        orders = self.load("orders.json")
        orders[0]["items"][0]["image_path"] = "images/alias.png"
        write(self.root, "orders.json", orders)
        with self.assertRaisesRegex(ValueError, "隐私边界"):
            build(self.root, self.out, "collage")
        self.assertFalse(self.out.exists())

    def test_user_provided_provenance_kept_without_local_personal_path(self):
        orders = self.load("orders.json")
        orders[0]["items"][0].update(origin="user_provided", provided_reference="C:/Users/secret-person/secret-folder/picture.png")
        write(self.root, "orders.json", orders)
        build(self.root, self.out, "collage")
        self.assertNotIn("secret-person", self.all_output_text())
        safe = json.loads((self.out / "orders.json").read_text(encoding="utf-8"))
        self.assertTrue(safe[0]["items"][0]["provided_reference"])

    def test_nested_metadata_and_coverage_free_text_are_not_exported(self):
        meta = self.load("project_meta.json")
        meta["requested_range"]["private_note"] = "private-nested-marker"
        write(self.root, "project_meta.json", meta)
        coverage = self.load("coverage.json")
        coverage[0].update(note="private-coverage-note", account="private-coverage-account")
        write(self.root, "coverage.json", coverage)
        build(self.root, self.out, "collage")
        for marker in ("private-nested-marker", "private-coverage-note", "private-coverage-account"):
            self.assertNotIn(marker, self.all_output_text())

    def test_coverage_status_is_not_a_free_text_backdoor(self):
        coverage = self.load("coverage.json")
        coverage[0]["status"] = "private-invalid-status"
        write(self.root, "coverage.json", coverage)
        with self.assertRaises(ValueError) as caught:
            build(self.root, self.out, "collage")
        self.assertNotIn("private-invalid-status", str(caught.exception))
        self.assertFalse(self.out.exists())

    def test_storage_key_changes_after_exclusion_and_is_stable_without_change(self):
        self.private_order(name="普通物品")
        before = prepare(self.root, "collage")["project_key"]
        self.assertEqual(before, prepare(self.root, "collage")["project_key"])
        write(self.root, "privacy.json", {"exclude_order_ids": ["withheld-secret-id"]})
        after = prepare(self.root, "collage")["project_key"]
        self.assertNotEqual(before, after)
        self.assertEqual(after, prepare(self.root, "collage")["project_key"])

    def test_storage_key_stays_stable_when_initial_plan_is_rewritten(self):
        before = prepare(self.root, "collage")["project_key"]
        story = self.load("story.json")
        story["plans"][0]["reason"] = "修改后的安全依据。"
        write(self.root, "story.json", story)
        self.assertEqual(before, prepare(self.root, "collage")["project_key"])

    def test_storage_key_stays_stable_for_normal_safe_increment(self):
        before = prepare(self.root, "collage")["project_key"]
        self.private_order(name="普通袜子")
        self.assertEqual(before, prepare(self.root, "collage")["project_key"])

    def test_cleaned_bundle_rebuild_retains_privacy_scope_and_storage_key(self):
        self.private_order()
        before = prepare(self.root, "collage")["project_key"]
        build(self.root, self.out, "collage")
        self.assertEqual(before, prepare(self.out, "collage")["project_key"])

    def test_explicit_synthetic_demo_flag_and_disclosure_are_preserved(self):
        meta = self.load("project_meta.json")
        meta["synthetic_demo"] = True
        write(self.root, "project_meta.json", meta)
        build(self.root, self.out, "collage")
        exported = json.loads((self.out / "project_meta.json").read_text(encoding="utf-8"))
        self.assertIs(exported["synthetic_demo"], True)
        self.assertIn("合成日期和订单", exported["coverage_note"])
        self.assertIn("AI 商品图", exported["coverage_note"])
        self.assertIn("非真实账号采集", exported["coverage_note"])
        coverage = json.loads((self.out / "coverage.json").read_text(encoding="utf-8"))
        self.assertIn("虚构演示", coverage[0]["note"])

    def test_synthetic_demo_flag_is_not_truthy_coerced(self):
        for value in ("true", "false", 1, False):
            meta = self.load("project_meta.json")
            meta["synthetic_demo"] = value
            write(self.root, "project_meta.json", meta)
            self.assertIsNot(prepare(self.root, "collage")["meta"].get("synthetic_demo"), True)

    def test_projects_without_explicit_identity_do_not_share_storage(self):
        meta = self.load("project_meta.json")
        meta.pop("target", None)
        write(self.root, "project_meta.json", meta)
        other = Path(self.temp.name) / "other-source"
        other.mkdir()
        fixture(other, "taobao")
        write(other, "project_meta.json", meta)
        self.assertNotEqual(prepare(self.root, "collage")["project_key"], prepare(other, "collage")["project_key"])

    def test_source_less_song_does_not_survive_private_source_removal(self):
        self.private_order()
        story = self.load("story.json")
        story["song"] = {"name": "合成测试歌曲", "artist": "合成作者", "reason": "旧的无来源依据", "is_recommendation": True}
        write(self.root, "story.json", story)
        with self.assertRaisesRegex(ValueError, "隐私边界"):
            prepare(self.root, "collage")
        story["song"]["source_ids"] = ["demo-1"]
        write(self.root, "story.json", story)
        self.assertEqual(prepare(self.root, "collage")["story"]["song"]["source_ids"], ["demo-1"])
        story["song"]["source_ids"] = ["not-real"]
        write(self.root, "story.json", story)
        with self.assertRaisesRegex(ValueError, "隐私边界"):
            prepare(self.root, "collage")


if __name__ == "__main__":
    unittest.main()
