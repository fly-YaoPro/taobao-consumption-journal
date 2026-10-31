"""Synthetic tests only; no platform/account access."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from build_journal import build, prepare, local_file, day


def write(root, name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture(root, kind="weibo"):
    write(root, "project_meta.json", {"schema_version": 1, "platform": kind, "title": "虚构测试示例", "mode": "selected", "timezone": "Asia/Shanghai", "requested_range": {"start": "2016-01-01", "end": "2026-10-30"}, "plan_year": 2027, "target": {"uid": "synthetic"}})
    write(root, "coverage.json", [{"year": 2025, "status": "selected", "note": "虚构测试，不是真实账号"}])
    if kind == "weibo":
        records = [{"id": "demo-1", "created_at": "2025-05-19T12:00:00+08:00", "text": "窗台的薄荷又长了一片叶子。", "images": [], "url": ""}]
        write(root, "records.json", records)
    else:
        write(root, "orders.json", [{"order_id": "demo-1", "placed_at": "2025-05-19T12:00:00+08:00", "is_success": True, "items": [{"item_id": "item-1", "name": "虚构测试花盆", "image_path": None}]}])
    write(root, "story.json", {"overview": {"headline": "虚构测试：窗台的一片新叶", "text": "这只是用于检查页面的合成记录，不是用户经历。", "source_ids": ["demo-1"]}, "themes": [{"id": "t1", "title": "测试主题", "text": "这一页只用于功能检查。", "source_ids": ["demo-1"], "layout": "C", "excerpt": "窗台的薄荷又长了一片叶子。" if kind == "weibo" else "虚构测试花盆"}], "findings": [{"title": "测试发现", "text": "合成数据。", "source_ids": ["demo-1"]}], "plans": [{"id": "p1", "title": "整理一次已有记录", "reason": "虚构测试建议。", "month": "2027-03", "source_ids": ["demo-1"]}]})


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def mutate(self, fn):
        value = json.loads((self.root / "story.json").read_text(encoding="utf-8"))
        fn(value)
        write(self.root, "story.json", value)

    def test_both_weibo_skins_and_taobao(self):
        for skin in ("paper", "frosted"):
            result = build(self.root, Path(self.temp.name) / skin, skin)
            self.assertEqual(result["plans"], 1)
        fixture(self.root, "taobao")
        self.assertEqual(build(self.root, Path(self.temp.name) / "collage", "collage")["records"], 1)

    def test_original_is_unchanged(self):
        before = (self.root / "story.json").read_bytes()
        build(self.root, Path(self.temp.name) / "new", "paper")
        self.assertEqual((self.root / "story.json").read_bytes(), before)

    def test_scrapbook_runtime_and_offline_fonts_are_bundled(self):
        fixture(self.root, "taobao")
        out = Path(self.temp.name) / "scrapbook"
        build(self.root, out, "collage")
        for name in ("scrapbook.css", "scrapbook.js", "fonts/display-bobo.woff2", "fonts/body.woff2", "fonts/note.woff2", "fonts/Bobohei-OFL.txt", "fonts/Noto-OFL.txt", "fonts/WenKai-OFL.txt"):
            self.assertTrue((out / name).is_file(), name)
        self.assertIn("scrapbook.js", (out / "index.html").read_text(encoding="utf-8"))

    def test_empty_plan_blocked(self):
        self.mutate(lambda s: s.update(plans=[]))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

    def test_unknown_source_blocked(self):
        self.mutate(lambda s: s["plans"][0].update(source_ids=["not-real"]))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

    def test_false_quote_blocked(self):
        self.mutate(lambda s: s["themes"][0].update(excerpt="这是凭空编写的原话"))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

    def test_nonempty_target_and_nested_blocked(self):
        out = Path(self.temp.name) / "new"
        out.mkdir()
        (out / "keep.txt").write_text("do not overwrite", encoding="utf-8")
        with self.assertRaises(ValueError):
            build(self.root, out, "paper")
        with self.assertRaises(ValueError):
            build(self.root, self.root / "nested", "paper")

    def test_path_escape_and_svg_blocked(self):
        for path in ("../outside.png", "https://example.com/a.jpg", "C:/secret.png", "images\\a.jpg"):
            with self.assertRaises(ValueError):
                local_file(self.root, path)
        (self.root / "a.svg").write_text("<svg/>", encoding="utf-8")
        with self.assertRaises(ValueError):
            local_file(self.root, "a.svg")

    def test_date_and_requested_range_are_not_faked(self):
        self.assertEqual(day("2025-01-01T20:00:00Z"), "2025-01-02")
        data = prepare(self.root, "paper")
        self.assertEqual(data["meta"]["actual_range"]["start"], "2025-05-19")
        self.assertIn("更早范围未完整收录", data["scope"])

    def test_js_string_is_escaped(self):
        self.mutate(lambda s: s["overview"].update(text="</script><script>alert(1)</script>"))
        out = Path(self.temp.name) / "escaped"
        build(self.root, out, "paper")
        self.assertNotIn("</script>", (out / "journal-data.js").read_text(encoding="utf-8"))

    def stage(self, **changes):
        return dict(id="s1", label="一个阶段", title="具体的变化", text="来自合成订单的阶段说明。", source_ids=["demo-1"], **changes)

    def test_stage_dates_are_derived_and_not_handwritten(self):
        self.mutate(lambda s: s.update(stages=[self.stage(range="1900-01-01")]))
        data = prepare(self.root, "paper")
        self.assertEqual(data["story"]["stages"][0]["range"], "2025-05-19 — 2025-05-19")
        self.assertEqual(data["story"]["stages"][0]["period_label"], "2025")

    def test_unconfirmed_life_context_is_blocked(self):
        self.mutate(lambda s: s.update(stages=[self.stage(context_ids=["imagined-graduation"])]))
        with self.assertRaisesRegex(ValueError, "生活背景"):
            prepare(self.root, "paper")

    def test_confirmed_context_and_natural_title_lines(self):
        meta = json.loads((self.root / "project_meta.json").read_text(encoding="utf-8"))
        meta["confirmed_context"] = [{"id":"test-background", "text":"虚构测试确认的背景。", "source":"user_confirmed"}]
        write(self.root, "project_meta.json", meta)
        self.mutate(lambda s: s.update(stages=[self.stage(context_ids=["test-background"], title_lines=["具体的", "变化"])]))
        self.assertEqual(len(prepare(self.root, "paper")["story"]["stages"]), 1)

    def test_stage_cannot_point_at_unknown_theme(self):
        self.mutate(lambda s: s.update(stages=[self.stage(detail_theme_id="missing")]))
        with self.assertRaisesRegex(ValueError, "不存在的主题"):
            prepare(self.root, "paper")

    def test_fake_title_line_or_overlong_note_is_blocked(self):
        self.mutate(lambda s: s.update(stages=[self.stage(title_lines=["另一个", "标题"])]))
        with self.assertRaisesRegex(ValueError, "title_lines"):
            prepare(self.root, "paper")
        self.mutate(lambda s: s.update(stages=[self.stage(notes=[{"title":"便签", "text":"字"*101, "source_ids":["demo-1"]}])]))
        with self.assertRaisesRegex(ValueError, "阶段便笺"):
            prepare(self.root, "paper")

    def test_stage_and_thread_images_are_checked_against_sources(self):
        for field in ("stages", "threads"):
            self.mutate(lambda s: s.update({"stages":[], "threads":[], field:[self.stage(image_paths=["images/unrelated.jpg"])]}))
            with self.assertRaisesRegex(ValueError, "页面图片与来源ID不对应"):
                prepare(self.root, "paper")

    def media_fixture(self):
        fixture(self.root, "taobao")
        (self.root / "images").mkdir(exist_ok=True)
        (self.root / "images/a.jpg").write_bytes(b"synthetic image test payload")
        orders = json.loads((self.root / "orders.json").read_text())
        orders[0]["items"][0]["image_path"] = "images/a.jpg"
        write(self.root, "orders.json", orders)

    def test_unclassified_images_are_source_only(self):
        self.media_fixture()
        self.assertEqual(prepare(self.root, "collage")["story"]["overview"]["images"][0]["kind"], "source")

    def test_sales_banner_is_not_promoted_to_cover(self):
        self.media_fixture()
        self.mutate(lambda s: s.update(visuals={"images/a.jpg": {"kind":"cover", "title":"合成促销样本", "promotional":True}}))
        self.assertEqual(prepare(self.root, "collage")["story"]["overview"]["images"][0]["kind"], "source")

    def test_verified_derivative_keeps_original_and_is_copied(self):
        self.media_fixture()
        (self.root / "derived").mkdir()
        (self.root / "derived/a.png").write_bytes(b"synthetic derived test payload")
        self.mutate(lambda s: s.update(visuals={"images/a.jpg":{"kind":"object", "title":"测试物件", "display_path":"derived/a.png", "treatment":"cutout"}}))
        out = Path(self.temp.name) / "media-output"
        build(self.root, out, "collage")
        image = prepare(self.root, "collage")["story"]["overview"]["images"][0]
        self.assertEqual(image["path"], "derived/a.png")
        self.assertEqual(image["large"], "images/a.jpg")
        self.assertTrue((out / "images/a.jpg").is_file())
        self.assertTrue((out / "derived/a.png").is_file())

    def test_generated_or_unknown_visual_is_rejected(self):
        self.media_fixture()
        for visual in ({"images/missing.jpg":{"kind":"object", "title":"错误来源"}},
                       {"images/a.jpg":{"kind":"cartoon", "title":"错误类型"}}):
            self.mutate(lambda s: s.update(visuals=visual))
            with self.assertRaises(ValueError):
                prepare(self.root, "collage")

    def test_derivative_cannot_escape_or_use_generation(self):
        self.media_fixture()
        self.mutate(lambda s: s.update(visuals={"images/a.jpg":{"kind":"object", "title":"样本", "display_path":"../outside.png", "treatment":"cutout"}}))
        with self.assertRaises(ValueError):
            prepare(self.root, "collage")
        self.mutate(lambda s: s.update(visuals={"images/a.jpg":{"kind":"object", "title":"样本", "display_path":"images/a.jpg", "treatment":"generate"}}))
        with self.assertRaises(ValueError):
            prepare(self.root, "collage")

    def test_explicit_empty_images_is_not_filled_from_orders(self):
        self.media_fixture()
        self.mutate(lambda s: s["overview"].update(image_paths=[]))
        self.assertEqual(prepare(self.root, "collage")["story"]["overview"]["images"], [])

    def test_duplicate_narrative_is_rejected(self):
        self.media_fixture()
        text = json.loads((self.root / "story.json").read_text())["themes"][0]["text"]
        self.mutate(lambda s: s.update(stages=[{**self.stage(), "text":text}]))
        with self.assertRaisesRegex(ValueError, "正文重复"):
            prepare(self.root, "collage")

    def test_duplicate_home_claim_is_rejected(self):
        self.media_fixture()
        self.mutate(lambda s: s.update(stages=[self.stage(claim_key="same")], threads=[dict(id="thread", title="另一个标题", text="措辞不同也不应重复同一发现。", source_ids=["demo-1"], claim_key="same")]))
        with self.assertRaisesRegex(ValueError, "claim_key"):
            prepare(self.root, "collage")

    def test_plan_can_be_unscheduled_without_changing_source(self):
        self.media_fixture()
        self.mutate(lambda s: s["plans"][0].pop("month"))
        before = (self.root / "story.json").read_bytes()
        self.assertEqual(prepare(self.root, "collage")["story"]["plans"][0]["month"], "")
        self.assertEqual((self.root / "story.json").read_bytes(), before)

    def test_share_embeds_same_local_image_for_offline_canvas(self):
        self.media_fixture()
        self.mutate(lambda s: s.update(visuals={"images/a.jpg":{"kind":"object","title":"测试物件"}}))
        out = Path(self.temp.name) / "share-output"
        build(self.root, out, "collage")
        js = (out / "journal-data.js").read_text(encoding="utf-8")
        data = json.loads(js[len("window.JOURNAL_DATA = "):].strip().rstrip(';'))
        import base64
        encoded = data["share_images"][0]["data_url"]
        self.assertEqual(base64.b64decode(encoded.split(',')[1]), (self.root / "images/a.jpg").read_bytes())
        self.assertNotIn("order_id", data["share_images"][0])

    def test_share_does_not_enlarge_promotional_source(self):
        self.media_fixture()
        self.mutate(lambda s: s.update(visuals={"images/a.jpg":{"kind":"source","title":"测试广告","promotional":True}}))
        out = Path(self.temp.name) / "share-source-only"
        build(self.root, out, "collage")
        js = (out / "journal-data.js").read_text(encoding="utf-8")
        data = json.loads(js[len("window.JOURNAL_DATA = "):].strip().rstrip(';'))
        self.assertEqual(data["share_images"], [])


if __name__ == "__main__":
    unittest.main()
