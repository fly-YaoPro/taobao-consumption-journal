#!/usr/bin/env python3
"""Build a new offline journal from existing normalized data. Python 3.9+, no network."""
import argparse
import base64
import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from image_files import image_info
from privacy_filter import prepare_private_projection
from ecommerce_platforms import ECOMMERCE_PLATFORMS


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def local_file(root, name):
    if not isinstance(name, str) or not name or re.match(r"^[a-zA-Z]+:", name) or "\\" in name:
        raise ValueError("图片必须是项目内相对路径")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("图片路径越界或文件缺失: " + name)
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        raise ValueError("证据图片只接受本地栅格图，不执行 SVG/HTML: " + name)
    try:
        image_info(path)
    except ValueError as exc:
        raise ValueError("图片文件无效，不能把下载响应当成功：" + name + ": " + str(exc)) from exc
    return path


def day(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("原始时间缺时区")
    return dt.astimezone(timezone(timedelta(hours=8))).date().isoformat()


def normalize(root, meta, kind, source=None):
    if source is None:
        source = load(root / ("records.json" if kind == "weibo" else "orders.json"))
    rows = []
    for r in source:
        if kind == "weibo":
            images = []
            for im in r.get("images", []):
                path = im.get("thumb_path") or im.get("large_path")
                if not path:
                    continue
                local_file(root, path)
                large = im.get("large_path") or path
                local_file(root, large)
                images.append({"path": path, "large": large, "caption": im.get("caption", "")})
            text = r.get("text", "")
            rows.append({"id": str(r["id"]), "date": day(r["created_at"]), "text": text,
                         "title": r.get("title") or re.sub(r"\s+", " ", text)[:26] or "一条记录",
                         "images": images, "url": r.get("url"), "links": r.get("links", [])})
        else:
            if not r.get("is_success"):
                continue
            images = []
            items = r.get("items", [])
            for it in items:
                path = it.get("image_path")
                if it.get("image_status") == "saved" and not path:
                    raise ValueError("商品标记已下载但没有 image_path，请先修复订单到图片的绑定")
                if path:
                    local_file(root, path)
                    images.append({"path": path, "large": path, "caption": it.get("name", "商品"), "item_id": str(it["item_id"])})
            names = [it.get("name", "商品") for it in items]
            rows.append({"id": str(r["order_id"]), "date": day(r["placed_at"]), "text": "\n".join(names),
                         "title": r.get("display_title") or " / ".join(names)[:30] or "一笔订单",
                         "images": images, "url": r.get("url"), "category": r.get("category", "未分类")})
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("来源ID重复，请先运行数据检查器")
    if not rows:
        raise ValueError("没有可用记录，不制作空手账")
    return sorted(rows, key=lambda r: (r["date"], r["id"]))


def prepare(root, skin):
    meta, story, coverage = (load(root / p) for p in ("project_meta.json", "story.json", "coverage.json"))
    kind = meta["platform"]
    if kind not in {"weibo", *ECOMMERCE_PLATFORMS} or (kind in ECOMMERCE_PLATFORMS and skin != "collage") or (kind == "weibo" and skin == "collage"):
        raise ValueError("微博使用 paper/frosted；电商（淘宝/京东）使用 collage")
    export_orders, privacy_report = None, None
    if kind in ECOMMERCE_PLATFORMS:
        meta, story, coverage, export_orders, privacy_report = prepare_private_projection(
            root, meta, story, coverage, load(root / "orders.json"))
    rows = normalize(root, meta, kind, export_orders)
    by_id = {r["id"]: r for r in rows}
    visual_map = story.get("visuals", {})
    if not isinstance(visual_map, dict):
        raise ValueError("visuals 必须是以原图路径为键的对象")
    raw_images = {im["path"] for r in rows for im in r["images"]}
    for original, visual in visual_map.items():
        if original not in raw_images or not isinstance(visual, dict):
            raise ValueError("视觉素材必须对应实际记录中的原图: " + str(original))
        if visual.get("kind") not in {"object", "photo", "cover", "design", "service", "source"}:
            raise ValueError("视觉类型需为 object/photo/cover/design/service/source")
        if not isinstance(visual.get("title"), str) or not 1 <= len(visual["title"].strip()) <= 24:
            raise ValueError("视觉素材需24字以内的准确短名，原商品标题留在订单档案")
        if visual.get("display_path"):
            local_file(root, visual["display_path"])
            if visual.get("treatment") not in {"crop", "cutout"}:
                raise ValueError("派生图片须注明 crop/cutout；不接受生成替换")
        if visual.get("promotional") and not visual.get("display_path") and visual["kind"] not in {"source", "service"}:
            visual["kind"] = "source"  # Do not enlarge a sales banner just to fill a page.
    def refs(value):
        ids = value.get("source_ids", [])
        if not ids or any(not isinstance(i, str) or i not in by_id for i in ids):
            raise ValueError("回顾、发现与计划必须关联真实字符串来源ID")
        return ids
    overview = story.get("overview", {})
    if not overview.get("text", "").strip() or len(overview["text"]) > 220:
        raise ValueError("先完成200字以内的真实回顾，不把数据范围说明当总结")
    if not overview.get("headline", "").strip() or len(overview["headline"]) > 36:
        raise ValueError("overview.headline 需由本批数据撰写，最多36字，不硬编码通用金句")
    refs(overview)
    themes = story.get("themes", [])
    if not themes:
        raise ValueError("先根据已有数据整理主题，不制作空页")
    theme_ids = set()
    for t in themes:
        refs(t)
        if not t.get("id") or t["id"] in theme_ids:
            raise ValueError("主题ID缺失或重复")
        theme_ids.add(t["id"])
        if not t.get("title") or not t.get("text") or t.get("layout", "A") not in {"A", "B", "C"}:
            raise ValueError("主题需标题、短记和 A/B/C 布局")
        excerpt = t.get("excerpt")
        if excerpt and not any(excerpt in by_id[i]["text"] for i in t["source_ids"]):
            raise ValueError("摘句不在关联原文中，不可伪造原话")
    for f in story.get("findings", []):
        refs(f)
    if kind in ECOMMERCE_PLATFORMS and not story.get("findings"):
        raise ValueError("电商总览需要有来源的发现，不能只放空便签")
    for m in story.get("milestones", []):
        refs(m)
    # Life chapters and cross-year threads are authored by the agent, never inferred
    # from a product category by this renderer. Every visual stays tied to sources.
    stages, threads = story.get("stages", []), story.get("threads", [])
    contexts = meta.get("confirmed_context", [])
    context_ids = {c.get("id") for c in contexts if c.get("id") and c.get("text") and c.get("source") == "user_confirmed"}
    for field, sections, maximum in (("stages", stages, 6), ("threads", threads, 4)):
        if not isinstance(sections, list) or len(sections) > maximum:
            raise ValueError(field + " 需为列表，且不超过 " + str(maximum) + " 项")
        seen = set()
        for section in sections:
            ids = refs(section)
            if not section.get("id") or section["id"] in seen:
                raise ValueError(field + " ID缺失或重复")
            seen.add(section["id"])
            if not section.get("title") or len(section["title"]) > 28 or not section.get("text") or len(section["text"]) > 240:
                raise ValueError(field + " 需短标题与240字以内的具体叙事")
            if len(section.get("label", "")) > 16 or len(section.get("notes", [])) > 2:
                raise ValueError("阶段标签最多16字，侧笺最多2张")
            lines = section.get("title_lines", [])
            if lines and (not isinstance(lines, list) or not 2 <= len(lines) <= 3 or any(not isinstance(x, str) or not x.strip() for x in lines) or "".join(lines) != section["title"]):
                raise ValueError("title_lines 须为原题目的2—3段自然断句，不改写标题")
            if section.get("detail_theme_id") and section["detail_theme_id"] not in theme_ids:
                raise ValueError("阶段关联了不存在的主题")
            if section.get("arrangement", "spread") not in {"spread", "ledger", "contrast"}:
                raise ValueError("arrangement 需为 spread/ledger/contrast")
            if any(c not in context_ids for c in section.get("context_ids", [])):
                raise ValueError("生活背景须在 confirmed_context 中由用户确认")
            dates = sorted(by_id[i]["date"] for i in ids)
            section["range"] = dates[0] + " — " + dates[-1]
            section["period_label"] = dates[0][:4] if dates[0][:4] == dates[-1][:4] else dates[0][:4] + "—" + dates[-1][:4]
            for note in section.get("notes", []):
                if not note.get("title") or not note.get("text") or len(note["text"]) > 100 or not set(refs(note)).issubset(ids):
                    raise ValueError("阶段便笺需短文字及该阶段内的来源")
    if kind in ECOMMERCE_PLATFORMS:
        bodies = {}
        for section in themes + stages + threads:
            body = re.sub(r"\s+", "", section["text"])
            if body in bodies:
                raise ValueError("叙事正文重复：合并同一发现，详情只补新信息")
            bodies[body] = section["id"]
        home_claims = set()
        for section in stages + threads:
            claim = section.get("claim_key")
            if claim and claim in home_claims:
                raise ValueError("阶段与跨年线索重复使用 claim_key，请合并或只保留一处")
            if claim:
                home_claims.add(claim)
    stages.sort(key=lambda s: s["range"])
    plans = story.get("plans", [])
    if not plans:
        raise ValueError("story.plans 为空：先由 Agent 从真实记录生成3—6条建议，再构建；不交付空计划页")
    plan_ids = set()
    for p in plans:
        refs(p)
        p.setdefault("month", "")
        if not p.get("id") or p["id"] in plan_ids or not p.get("title") or not p.get("reason") or (p["month"] != "" and not re.fullmatch(r"(?:19|20|21)\d{2}-(?:0[1-9]|1[0-2])", p["month"])):
            raise ValueError("计划需唯一ID、标题、依据 reason 和来源ID；无排期依据时 month 留空")
        plan_ids.add(p["id"])
    # Display image choices must actually belong to cited records, not a global unrelated gallery.
    for section in [overview] + themes + stages + threads:
        allowed = {im["path"]: (r, im) for i in section["source_ids"] for r in [by_id[i]] for im in r["images"]}
        choices = section.get("image_paths")
        if choices is None:
            priority = {"object": 0, "photo": 0, "cover": 1, "design": 2, "service": 3, "source": 4}
            choices = sorted(allowed, key=lambda path: priority.get(visual_map.get(path, {}).get("kind", "source"), 4))[:5 if section is overview else 3]
        if len(choices) != len(set(choices)):
            raise ValueError("同页图片重复")
        section["images"] = []
        for path in choices:
            if path not in allowed:
                raise ValueError("页面图片与来源ID不对应: " + str(path))
            r, im = allowed[path]
            visual = visual_map.get(path, {})
            if kind in ECOMMERCE_PLATFORMS and not visual:
                raise ValueError("图片已下载但未完成页面展示映射：" + path + "；先读图填写 story.visuals，不能默认隐藏为来源卡")
            caption = section.get("image_captions", {}).get(path) or visual.get("title") or im["caption"] or r["title"]
            section["images"].append({**im, "path": visual.get("display_path") or path,
                                      "large": im["large"], "kind": visual.get("kind", "source" if kind in ECOMMERCE_PLATFORMS else "photo"),
                                      "date": r["date"], "record_id": r["id"], "caption": caption})
    if kind in ECOMMERCE_PLATFORMS:
        sections = [overview] + themes + stages + threads
        visible_kinds = {"object", "photo", "cover", "design"}
        eligible = {path for path, visual in visual_map.items() if visual["kind"] in visible_kinds}
        visible = [im for section in sections for im in section["images"] if im["kind"] in visible_kinds]
        if eligible and not any(im["kind"] in visible_kinds for im in overview["images"]):
            raise ValueError("有已核对可展示的商品图片，但首页没有实际图片；补齐 overview.source_ids 与 image_paths，不能只在日历出现")
        if raw_images and not eligible and not str(story.get("image_fallback_reason") or "").strip():
            raise ValueError("全部商品图都被降成服务/来源卡；先复核分类，确实全无适合图片时写 image_fallback_reason，不能静默做成纯文字")
        if not raw_images and not (privacy_report and privacy_report["excluded_parent_orders"]) and any((root / folder).is_dir() and any(p.is_file() for p in (root / folder).rglob("*")) for folder in ("images", "downloads")):
            raise ValueError("目录里有图片文件但订单未绑定任何 image_path；先核对下载清单与商品行，不能交付无图页面")
        media_summary = {"downloaded_originals": len(raw_images), "classified_originals": len(visual_map),
                         "displayable_originals": len(eligible), "rendered_image_slots": len(visible),
                         "overview_image_slots": sum(im["kind"] in visible_kinds for im in overview["images"]),
                         "fallback_reason": story.get("image_fallback_reason", "")}
    else:
        media_summary = None
    actual = {"start": rows[0]["date"], "end": rows[-1]["date"]}
    meta["actual_range"] = actual
    meta["plan_year"] = int(meta.get("plan_year") or datetime.now().year + 1)
    mode = "精选记录" if meta.get("mode") == "selected" else "已收录记录（完整性见覆盖说明）"
    scope = f'{actual["start"]} — {actual["end"]} · {len(rows)}条{mode}'
    requested = meta.get("requested_range", {})
    if requested.get("start", actual["start"]) < actual["start"]:
        scope += " · 更早范围未完整收录"
    identity = str(meta.get("project_id") or meta.get("target", {}).get("uid") or rows[0]["id"])
    if kind in ECOMMERCE_PLATFORMS:
        identity += ":privacy-v1:" + meta["privacy_storage_scope"]
    project_key = hashlib.sha256((kind + ":" + identity).encode()).hexdigest()[:16]
    return {"version": 2, "project_key": project_key, "skin": skin, "meta": meta, "story": story,
            "coverage": coverage, "records": rows, "scope": scope, "media_summary": media_summary,
            "_export_orders": export_orders, "privacy_report": privacy_report}


def build(source, output, skin, template=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("输出与原项目必须分开，禁止嵌套或覆盖")
    if output.exists() and any(output.iterdir()):
        raise ValueError("输出目录不为空；选新目录，保留旧网页与手动计划")
    data = prepare(source, skin)  # validate before writing anything
    export_orders = data.pop("_export_orders")
    template = Path(template) if template else Path(__file__).resolve().parents[1] / "assets" / "starter"
    output.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "styles.css", "app.js", "core.js", "scrapbook.css", "scrapbook.js", "share-editorial.js"):
        shutil.copyfile(template / filename, output / filename)
    # Only template-owned fonts and their notices. Never copy source caches or profiles.
    font_dir = template / "fonts"
    if font_dir.exists():
        for font in font_dir.iterdir():
            if font.is_symlink() or not font.is_file() or font.suffix.lower() not in {".woff2", ".txt", ".md"}:
                raise ValueError("模板 fonts/ 仅允许本地字体与许可说明")
        shutil.copytree(font_dir, output / "fonts")
    # Data URLs keep genuine local images canvas-safe even when opened with file://.
    # Raw order files stay unchanged; these are display resources, never invented pictures.
    share_candidates = data["story"]["overview"]["images"]
    if not any(im.get("kind") in {"object", "photo", "cover", "design"} for im in share_candidates):
        share_candidates = [im for t in data["story"]["themes"] for im in t.get("images", [])]
    data["share_images"] = []
    seen_share = set()
    mime_types = {"jpeg":"image/jpeg", "png":"image/png", "webp":"image/webp", "gif":"image/gif"}
    for im in share_candidates:
        if im.get("kind") not in {"object", "photo", "cover", "design"} or im["path"] in seen_share:
            continue
        file = local_file(source, im["path"])
        data["share_images"].append({"caption":im["caption"], "kind":im["kind"], "date":im["date"],
                                     "data_url":"data:" + mime_types[image_info(file)["format"]] + ";base64," + base64.b64encode(file.read_bytes()).decode("ascii")})
        seen_share.add(im["path"])
        if len(data["share_images"]) == 4:
            break
    js = "window.JOURNAL_DATA = " + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    (output / "journal-data.js").write_text(js, encoding="utf-8")
    if data["media_summary"] is not None:
        (output / "media-report.json").write_text(json.dumps(data["media_summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    if data["privacy_report"] is not None:
        (output / "privacy-report.json").write_text(json.dumps(data["privacy_report"], ensure_ascii=False, indent=2), encoding="utf-8")
    paths = {im[k] for r in data["records"] for im in r["images"] for k in ("path", "large")}
    paths.update(v["display_path"] for v in data["story"].get("visuals", {}).values() if v.get("display_path"))
    for name in paths:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_file(source, name), target)
    # Ecommerce has a separate display/export boundary. Raw data remains ONLY in
    # the source directory: hidden rows in an HTML UI are not anonymisation.
    if data["meta"]["platform"] in ECOMMERCE_PLATFORMS:
        for filename, value in (("project_meta.json", data["meta"]), ("coverage.json", data["coverage"]),
                                ("story.json", data["story"]), ("orders.json", export_orders)):
            (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        for filename in ("project_meta.json", "coverage.json", "story.json", "records.json"):
            shutil.copyfile(source / filename, output / filename)
    bundle = "data.js" if data["meta"]["platform"] == "weibo" else "orders.js"
    global_name = "LIFE_ARCHIVE_DATA" if data["meta"]["platform"] == "weibo" else "CONSUMPTION_JOURNAL_DATA"
    raw_key = "records" if data["meta"]["platform"] == "weibo" else "orders"
    canonical = {"meta": data["meta"], "coverage": data["coverage"], "story": data["story"], raw_key: export_orders if export_orders is not None else load(source / (raw_key + ".json"))}
    canonical_js = f"window.{global_name} = " + json.dumps(canonical, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    (output / bundle).write_text(canonical_js, encoding="utf-8")
    (output / "exports").mkdir(exist_ok=True)
    return {"output": str(output), "records": len(data["records"]), "themes": len(data["story"]["themes"]), "stages": len(data["story"].get("stages", [])), "plans": len(data["story"]["plans"]), "images": len(paths), "skin": skin}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skin", required=True, choices=["paper", "frosted", "collage"])
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.source, args.output, args.skin), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, "未构建: " + str(error) + "\n")
