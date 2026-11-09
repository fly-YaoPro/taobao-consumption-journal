"""Conservative, local-only ecommerce display/export boundary. Not a classifier guarantee."""
import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import PurePosixPath
from ecommerce_platforms import ecommerce_platform, validate_order_platforms, validate_product_url


# Match product fields, never the entire export blob. Do not match broad fragments
# such as 成人/胸/袜/健康: books, ordinary socks and unrelated products remain usable.
PRIVATE_TERMS = (
    "内衣", "内裤", "文胸", "胸罩", "乳罩", "丁字裤", "三角裤", "平角裤",
    "情趣用品", "成人用品", "成人玩具", "性爱用品", "自慰", "跳蛋", "飞机杯",
    "避孕套", "安全套", "验孕", "早孕试纸", "排卵试纸", "私处", "私密护理",
    "阴道", "阴茎", "阴部", "龟头", "阴道炎", "妇科用药", "痔疮", "肛肠用药",
    "性病", "艾滋自测", "hiv自测", "hiv检测试纸", "梅毒", "精液检测",
    "卫生巾", "卫生棉条", "月经杯", "护垫", "失禁护理", "成人纸尿裤",
)
ENGLISH_PRIVATE = re.compile(
    r"(?<![a-z])(?:underwear|lingerie|bras?|panties|underpants|boxer\s+briefs|"
    r"condoms?|vibrators?|sex\s+toys?|adult\s+toys?|pregnancy\s+tests?|"
    r"ovulation\s+tests?|vaginal|menstrual\s+cups?|tampons?)(?![a-z])", re.I)
ORDER_KEYS = {"platform", "order_id", "placed_at", "raw_status", "is_success", "currency", "paid_amount",
              "refund_amount", "amount_basis", "url", "category", "display_title", "date_precision",
              "observed_amount", "observed_amount_label", "parent_order_id", "split_relation_uncertain", "amount_note"}
ITEM_KEYS = {"item_id", "item_id_basis", "name", "spec", "quantity", "image_path", "image_status",
             "origin", "source_url", "product_url"}
STORY_KEYS = {"overview", "themes", "findings", "stages", "threads", "milestones", "plans",
              "song", "visuals", "image_fallback_reason"}
SECTION_KEYS = {"id", "headline", "title", "title_lines", "text", "note", "tags", "source_ids",
                "item_ids", "image_paths", "image_captions", "layout", "excerpt", "range", "label",
                "notes", "context_ids", "detail_theme_id", "arrangement", "claim_key", "home", "teaser",
                "source_labels", "month", "reason", "done", "name", "artist", "url", "is_recommendation"}
VISUAL_KEYS = {"kind", "title", "display_path", "treatment", "promotional"}


def sensitive_text(value):
    """High-confidence cues only; semantic/image review is still required."""
    if not isinstance(value, str):
        return False
    text = unicodedata.normalize("NFKC", value).lower()
    return any(term in text for term in PRIVATE_TERMS) or bool(ENGLISH_PRIVATE.search(text))


def flagged(value):
    privacy = value.get("privacy")
    return (value.get("exclude_from_export") is True or value.get("is_private") is True
            or value.get("sensitive") is True or value.get("visibility") in {"private", "exclude", "hidden"}
            or privacy in ("private", "exclude", "hidden")
            or isinstance(privacy, dict) and (privacy.get("exclude") is True
                or privacy.get("sensitive") is True or privacy.get("visibility") in {"private", "exclude", "hidden"}))


def product_sensitive(value):
    return flagged(value) or any(sensitive_text(value.get(key)) for key in ("name", "spec", "category", "display_title"))


def path_key(value):
    return str(PurePosixPath(value.replace("\\", "/"))) if isinstance(value, str) and value else ""


def local_digest(root, value):
    if not isinstance(value, str) or not value:
        return None
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).digest()


def reject_story():
    raise ValueError("隐私边界：现有回顾或图片仍引用已排除资料。请由 Agent 仅依据可展示数据重写相关回顾、发现和计划后再构建；不要让用户编辑 JSON。")


def check_story(value, excluded_ids, excluded_images):
    if isinstance(value, dict):
        if set(value.get("source_ids", [])) & excluded_ids:
            reject_story()
        if any(path_key(p) in excluded_images for p in value.get("image_paths", [])):
            reject_story()
        for key, child in value.items():
            if key not in {"visuals", "image_captions", "source_labels"}:
                check_story(child, excluded_ids, excluded_images)
    elif isinstance(value, list):
        for child in value:
            check_story(child, excluded_ids, excluded_images)
    elif sensitive_text(value):
        reject_story()


def section_projection(value):
    if isinstance(value, list):
        return [section_projection(v) for v in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    projected = {k: copy.deepcopy(v) for k, v in value.items() if k in SECTION_KEYS}
    if "notes" in projected:
        projected["notes"] = section_projection(projected["notes"])
    return projected


def safe_metadata(meta):
    """Known nested fields are schemas too, not containers for arbitrary notes."""
    try:
        bounds = meta["requested_range"]
        begin, end = date.fromisoformat(bounds["start"]), date.fromisoformat(bounds["end"])
        if begin > end or meta.get("mode") not in {"full", "selected"} or meta.get("timezone") != "Asia/Shanghai":
            raise ValueError()
        title = meta["title"]
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise ValueError()
        safe = {"schema_version": 1, "platform": ecommerce_platform(meta.get("platform")), "title": title, "mode": meta["mode"],
                "timezone": "Asia/Shanghai", "requested_range": {"start": begin.isoformat(), "end": end.isoformat()}}
        if meta.get("plan_year") is not None:
            safe["plan_year"] = int(meta["plan_year"])
        # Demo status is factual provenance, not optional decoration. Never
        # coerce strings/numbers to True, and never strip an explicit true flag.
        if isinstance(meta.get("synthetic_demo"), bool):
            safe["synthetic_demo"] = meta["synthetic_demo"]
        return safe
    except (KeyError, TypeError, ValueError):
        raise ValueError("项目展示元数据格式无效，请由 Agent 核对日期、标题和范围；未复制原始字段") from None


def prepare_private_projection(root, meta, story, coverage, orders):
    """Return a separate safe bundle; never mutate/delete raw local files.

    A mixed parent order is withheld whole: retaining its amount/date/title could
    reveal the excluded item, and a narrative citing it cannot be auto-repaired.
    """
    validate_order_platforms(orders, meta.get("platform"))
    for order in orders:
        if meta.get('platform') == 'jd' and order.get('is_success') is True and order.get('raw_status') != '已完成':
            raise ValueError('JD included status must be exactly 已完成; verify imported records before export')
        for item in order.get('items', []):
            validate_product_url(item.get('product_url'), meta.get('platform'))
    policy_path = root / "privacy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig")) if policy_path.exists() else {}
    if not isinstance(policy, dict):
        raise ValueError("privacy.json 需为隐私筛选对象，请由 Agent 修复配置")
    explicit_orders = policy.get("exclude_order_ids", [])
    explicit_items = policy.get("exclude_items", [])
    if not isinstance(explicit_orders, list) or any(not isinstance(x, str) for x in explicit_orders):
        raise ValueError("隐私排除订单需为字符串 ID 列表")
    if not isinstance(explicit_items, list) or any(not isinstance(x, dict) or not isinstance(x.get("order_id"), str) or not isinstance(x.get("item_id"), str) for x in explicit_items):
        raise ValueError("隐私排除商品需同时提供订单和商品字符串 ID")
    item_pairs = {(x["order_id"], x["item_id"]) for x in explicit_items}
    existing_ids = {str(o["order_id"]) for o in orders}
    existing_items = {(str(o["order_id"]), str(i["item_id"])) for o in orders for i in o.get("items", [])}
    if not set(explicit_orders).issubset(existing_ids) or not item_pairs.issubset(existing_items):
        raise ValueError("隐私排除清单与本地数据不一致，请由 Agent 核对后重试；未忽略排除请求")
    excluded = set(explicit_orders)
    for order in orders:
        oid = str(order["order_id"])
        if product_sensitive(order) or any(product_sensitive(it) or (oid, str(it["item_id"])) in item_pairs for it in order.get("items", [])):
            excluded.add(oid)
    # Do not let a shared source-image path reintroduce a withheld image via an
    # otherwise innocent row. This also covers derivative pointers in visuals.
    excluded_images = set()
    excluded_hashes = set()
    changed = True
    while changed:
        changed = False
        for order in orders:
            if str(order["order_id"]) in excluded:
                excluded_images.update(path_key(i.get("image_path")) for i in order.get("items", []) if i.get("image_path"))
        excluded_hashes.update(d for p in excluded_images if (d := local_digest(root, p)))
        for order in orders:
            if str(order["order_id"]) not in excluded and any(path_key(i.get("image_path")) in excluded_images or local_digest(root, i.get("image_path")) in excluded_hashes for i in order.get("items", []) if i.get("image_path")):
                excluded.add(str(order["order_id"])); changed = True
    check_story(story, excluded, excluded_images)
    # An optional song explanation can still carry an old conclusion. Once
    # privacy exclusions changed its underlying material, require safe evidence
    # instead of silently retaining a source-less recommendation from before.
    if excluded and story.get("song") and not story["song"].get("source_ids"):
        reject_story()
    if story.get("song") and any(i not in existing_ids - excluded for i in story["song"].get("source_ids", [])):
        reject_story()
    safe_orders = []
    for order in orders:
        if str(order["order_id"]) in excluded or not order.get("is_success"):
            continue
        safe = {k: copy.deepcopy(v) for k, v in order.items() if k in ORDER_KEYS}
        safe["items"] = [{k: copy.deepcopy(v) for k, v in it.items() if k in ITEM_KEYS} for it in order.get("items", [])]
        for original, item in zip(order.get("items", []), safe["items"]):
            if item.get("origin") == "user_provided" and original.get("provided_reference"):
                item["provided_reference"] = "用户提供的对应商品图片；原始授权说明仅保留在本地资料。"
        safe_orders.append(safe)
    safe_images = {path_key(i.get("image_path")) for o in safe_orders for i in o.get("items", []) if i.get("image_path")}
    safe_story = {k: (copy.deepcopy(v) if k in {"visuals", "image_fallback_reason"} else section_projection(v)) for k, v in story.items() if k in STORY_KEYS}
    safe_story["visuals"] = {k: {a: copy.deepcopy(b) for a, b in v.items() if a in VISUAL_KEYS}
                             for k, v in story.get("visuals", {}).items() if path_key(k) not in excluded_images}
    for visual in safe_story["visuals"].values():
        if path_key(visual.get("display_path")) in excluded_images or local_digest(root, visual.get("display_path")) in excluded_hashes or sensitive_text(visual.get("title")):
            reject_story()
    for section in [safe_story.get("overview", {})] + [x for field in ("themes", "stages", "threads") for x in safe_story.get(field, [])]:
        section["image_captions"] = {k: v for k, v in section.get("image_captions", {}).items() if path_key(k) in safe_images}
        section["source_labels"] = {k: v for k, v in section.get("source_labels", {}).items() if k not in excluded}
        if any(sensitive_text(v) for v in list(section["image_captions"].values()) + list(section["source_labels"].values())):
            reject_story()
    safe_meta = safe_metadata(meta)
    used_contexts = {c for s in safe_story.get("stages", []) for c in s.get("context_ids", [])}
    safe_meta["confirmed_context"] = [{k: c[k] for k in ("id", "text", "source") if k in c}
                                      for c in meta.get("confirmed_context", []) if c.get("id") in used_contexts]
    if any(sensitive_text(c.get("text")) for c in safe_meta["confirmed_context"]):
        reject_story()
    if sensitive_text(safe_meta.get("title")):
        reject_story()
    # Stable opaque project identity avoids exporting a raw target/account field.
    prior_key = str(meta.get("project_id", ""))
    identity = prior_key or meta.get("target", {}).get("uid") or "local-source:" + str(root.resolve())
    safe_meta["project_id"] = prior_key if meta.get("privacy_filtered") and re.fullmatch(r"[0-9a-f]{20}", prior_key) else hashlib.sha256(str(identity).encode()).hexdigest()[:20]
    safe_meta["privacy_filtered"] = True
    # Preserve manual plans across normal incremental collection and editorial
    # changes. Isolate storage only when the privacy boundary itself changes.
    # A previously cleaned bundle no longer contains withheld rows; retain its
    # opaque boundary fingerprint rather than treating it as a fresh empty set.
    prior_scope = str(meta.get("privacy_storage_scope", ""))
    cleaned_scope = prior_scope if meta.get("privacy_filtered") is True and re.fullmatch(r"[0-9a-f]{20}", prior_scope) else ""
    if cleaned_scope and not excluded:
        safe_meta["privacy_storage_scope"] = cleaned_scope
    else:
        storage_scope = {"policy_version": 1, "excluded_order_ids": sorted(excluded)}
        if cleaned_scope:
            storage_scope["prior_cleaned_scope"] = cleaned_scope
        safe_meta["privacy_storage_scope"] = hashlib.sha256(json.dumps(storage_scope, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    safe_meta["coverage_note"] = ("虚构演示：合成日期和订单、AI 商品图，非真实账号采集，不代表真实消费经历。"
                                  if safe_meta.get("synthetic_demo") is True else
                                  "本页仅展示通过隐私筛选的记录；原始资料留在本地，不包含于此产物。自动筛查不能替代逐条及逐图复核。")
    counts = Counter(str(o["placed_at"])[:4] for o in safe_orders)
    if not isinstance(coverage, list) or any(not isinstance(c, dict) or not isinstance(c.get("year"), int)
            or isinstance(c.get("year"), bool) or not 1900 <= c["year"] <= 2200
            or c.get("status") not in {"complete", "partial", "selected", "unread", "failed", "empty"} for c in coverage):
        raise ValueError("覆盖记录年份或状态格式无效，请由 Agent 核对；未复制自由说明字段")
    safe_coverage = [{"year": c["year"], "status": c["status"], "scanned_count": None,
                      "saved_count": counts[str(c["year"])], "note": "虚构演示：合成日期和订单、AI 商品图，非真实账号采集。" if safe_meta.get("synthetic_demo") is True else "数量为隐私筛选后的可展示记录，不代表全部订单。"} for c in coverage]
    report = {"policy_version": 1, "excluded_parent_orders": len(excluded),
              "display_orders": len(safe_orders), "raw_source_copied": False,
              "automatic_detection_is_complete": False, "semantic_review_required": True,
              "deployment_authorized": False}
    return safe_meta, safe_story, safe_coverage, safe_orders, report
