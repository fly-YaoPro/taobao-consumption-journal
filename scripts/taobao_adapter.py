#!/usr/bin/env python3
"""Normal-browser adapter for the Taobao buyer order list.

The browser is driven by the host's already-verified normal browser capability.
The bundled batch runner accepts a browser object and a normal pagination callback. This module never logs in, stores
credentials or calls a private API: it only (1) provides read-only JavaScript
that parses the visible order list/detail pages, and (2) normalizes the parsed
payload into the data contract consumed by ``collection_state``.

Selectors deliberately use ``[class*="..."]`` contains matches because the site appends
hashed suffixes (e.g. ``shopInfoStatus--InnfaPAJ``) that change over time.
"""
import copy
import re
from urllib.parse import urlsplit, parse_qs

# ---------------------------------------------------------------------------
# Status vocabulary observed on the real buyer pages.
# ---------------------------------------------------------------------------
SUCCESS_STATUS = "交易成功"
# Only the exact completed-trade label is included; other statuses stay outside the saved order set.


# ---------------------------------------------------------------------------
# Read-only JavaScript: parse the current "已买到的宝贝" list page.
# Returns a JSON string: {source_url, pagination, orders:[...]}.
# ---------------------------------------------------------------------------
LIST_PAGE_SCRIPT = r"""
(() => {
  const t = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  const bgUrl = e => {
    if (!e) return null;
    const m = (e.getAttribute('style') || '').match(/background-image:\s*url\(["']?(.*?)["']?\)/);
    return m ? m[1] : null;
  };
  const toHttp = u => u && u.startsWith('//') ? 'https:' + u : u;
  const visible = e => !!e && e.getClientRects().length>0;
  const login = Array.from(document.querySelectorAll('input[type=password]')).some(visible);
  const blocked = Array.from(document.querySelectorAll('[role=alert],.nc-container')).some(e=>visible(e)&&/验证|验证码|访问受限|请求过于频繁/.test(t(e)));
  const loading = Array.from(document.querySelectorAll('.ant-spin-spinning,[aria-busy=true]')).some(visible);
  const orders = Array.from(document.querySelectorAll('.trade-bought-list-order-container')).map(c => {
    const detailA = c.querySelector('a[class*="shopInfoOrderDetail"]');
    const rows = Array.from(c.querySelectorAll('[class*="itemInfoColItem"]')).map(r => ({
      image_url: toHttp(bgUrl(r.querySelector('a[class*="image"]'))),
      item_url: (r.querySelector('a[class*="title"]') || {}).href || null,
      name: t(r.querySelector('[class*="titleText"]')),
      info_lines: Array.from(r.querySelectorAll('[class*="infoContent"]')).map(t),
      price_text: t(r.parentElement.querySelector('[class*="itemInfoColPrice"]'))
    }));
    return {
      order_date: t(c.querySelector('[class*="shopInfoOrderTime"]')),
      order_id_text: t(c.querySelector('[class*="shopInfoOrderId"]')),
      shop: t(c.querySelector('[class*="shopInfoName"]')) ||
            ((c.querySelector('[class*="shopInfo"] a') || {}).textContent || ''),
      status: t(c.querySelector('[class*="shopInfoStatus"]')),
      detail_url: detailA ? detailA.href : null,
      payment_text: t(c.querySelector('[class*="orderPaymentCol"]')),
      operations_text: t(c.querySelector('[class*="orderOperationsCol"]')),
      rows
    };
  });
  const active = document.querySelector('.ant-pagination-item-active');
  const nextBtn = document.querySelector('.ant-pagination-next');
  return JSON.stringify({
    source_url: location.href,
    route_status: login?'login_required':blocked?'blocked':loading?'loading':orders.length?'ready':'empty_or_unrecognized',
    pagination: {
      active: active ? active.title : null,
      page_items: Array.from(document.querySelectorAll('.ant-pagination-item')).map(li => li.title),
      next_disabled: nextBtn ? (nextBtn.classList.contains('ant-pagination-disabled') || nextBtn.getAttribute('aria-disabled')==='true' || !!nextBtn.querySelector('button:disabled')) : null
    },
    orders
  });
})()
"""

# ---------------------------------------------------------------------------
# Read-only JavaScript: parse a single order detail page.
# The genuine order image lives in the same .imageContainer/a.image structure as
# the list. Every img.product-img belongs to the "猜你喜欢" recommendation feed
# and is ignored. Sensitive address/contact blocks are never returned.
# ---------------------------------------------------------------------------
DETAIL_PAGE_SCRIPT = r"""
(() => {
  const t = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  const imgA = document.querySelector('.imageContainer a[class*="image"]') ||
               document.querySelector('a[class*="image"]');
  let mainImage = null;
  if (imgA) {
    const m = (imgA.getAttribute('style') || '').match(/background-image:\s*url\(["']?(.*?)["']?\)/);
    if (m) mainImage = m[1].startsWith('//') ? 'https:' + m[1] : m[1];
  }
  const times = {};
  const amounts = {};
  Array.from(document.querySelectorAll('[class*="detailInfoContent"]')).forEach(b => {
    const text = t(b);
    let m = text.match(/(创建时间|付款时间|发货时间|成交时间)(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/);
    if (m) times[m[1]] = m[2];
    m = text.match(/(商品总价|实付款)￥([0-9]+(?:\.[0-9]+)?)/);
    if (m) amounts[m[1]] = m[2];
  });
  return JSON.stringify({
    source_url: location.href,
    main_image: mainImage,
    times: times,
    amounts: amounts
  });
})()
"""

# ---------------------------------------------------------------------------
# Field-level parsing helpers.
# ---------------------------------------------------------------------------
def _query_id_from_url(detail_url):
    if not detail_url:
        return None
    parts = urlsplit(detail_url)
    query = parse_qs(parts.query)
    value = query.get('biz_order_id') or query.get('bizOrderId')
    return value[0] if value else None


def extract_order_id(order_id_text, detail_url=None):
    """Return the platform order id as a string; cross-check both sources."""
    text_id = None
    match = re.search(r'([0-9]{6,})', order_id_text or '')
    if match:
        text_id = match.group(1)
    url_id = _query_id_from_url(detail_url)
    chosen = text_id or url_id
    if not chosen:
        raise ValueError('could not locate a platform order id')
    if url_id and text_id and url_id != text_id:
        raise ValueError('order id mismatch between header and detail link')
    if not chosen.isdigit():
        raise ValueError('order id must be a digit string')
    return chosen


_AMOUNT_RE = re.compile(r'实付款\s*[￥¥]\s*([0-9]+(?:\.[0-9]+)?)')
_QTY_RE = re.compile(r'[x×X]\s*([0-9]+)(?![0-9])')


def parse_paid_amount(payment_text):
    """Extract the parent-order paid amount; None when the page shows none."""
    if not payment_text:
        return None
    match = _AMOUNT_RE.search(payment_text)
    return match.group(1) if match else None


def parse_quantity(price_text):
    """Extract quantity from the row price text (e.g. '￥72.01x30')."""
    matches = _QTY_RE.findall(price_text or '')
    if len(matches) != 1 or int(matches[0]) < 1:
        raise ValueError('quantity missing or ambiguous; verify the product row')
    return int(matches[0])


def parse_spec(info_lines):
    """First info line is the SKU/spec; service guarantees come after it."""
    if not info_lines:
        return None
    candidate = info_lines[0].strip()
    return candidate or None


def build_item_id(order_id, row_index):
    """Stable in-order row key when the list exposes no platform line id."""
    return f'{order_id}-{row_index:02d}'


def parse_item_url_id(item_url):
    """Real visible row id from the product link; None when it cannot be trusted.

    The title anchor on every product row points at the item page and carries its
    platform ``id``. Only an https URL with a bounded digit id is accepted, so a
    malformed or non-product link can never be promoted into a row identity.
    """
    if not item_url:
        return None
    parts = urlsplit(item_url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        return None
    value = parse_qs(parts.query).get('id')
    if not value:
        return None
    candidate = value[0]
    return candidate if re.fullmatch(r'[0-9]{6,19}', candidate) else None


def resolve_item_identities(rows):
    """Return real row ids for a whole order, or None to fall back to row index.

    The switch is safe only when every row exposes a unique real id; a missing
    id or a duplicate (e.g. the same product in two specs) makes the caller keep
    the deterministic order-row index instead of guessing.
    """
    ids = [parse_item_url_id(row.get('item_url')) for row in rows]
    if not ids or any(i is None for i in ids) or len(set(ids)) != len(ids):
        return None
    return ids


def is_success_status(status):
    return status == SUCCESS_STATUS


def _list_date_to_iso(order_date):
    # The list page only exposes a date. The normalized timestamp keeps that
    # date at 00:00 Beijing time until a detail read fills the exact created_at.
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', order_date or ''):
        raise ValueError('invalid order date from list page: ' + str(order_date))
    return order_date + 'T00:00:00+08:00'


# ---------------------------------------------------------------------------
# Payload normalization.
# ---------------------------------------------------------------------------
def _normalize_item(item_id, item_id_basis, row):
    name = (row.get('name') or '').strip()
    if not name:
        raise ValueError('product row missing title')
    return {
        'item_id': item_id,
        'item_id_basis': item_id_basis,
        'name': name,
        'spec': parse_spec(row.get('info_lines')),
        'quantity': parse_quantity(row.get('price_text')),
        'source_url': row.get('image_url'),
        'origin': 'platform' if row.get('image_url') else None,
        'image_status': 'unavailable',
        'image_path': None,
    }


def normalize_list_page(raw, account_key, cursor, evidence_note, next_cursor=None,
                        item_id_basis='row_index'):
    """Convert LIST_PAGE_SCRIPT output into a collection_state batch dict.

    Non-success orders are kept in the batch with their real status;
    ``collection_state.commit_page`` filters them out of the saved order set.

    ``item_id_basis`` defaults to ``'row_index'`` (deterministic in-order key and
    the only behavior existing projects know). With ``'item_url'`` each order is
    switched to its real visible product ids only when every row has a unique one;
    any order that fails that check is kept on the row-index fallback.
    """
    if item_id_basis not in ('row_index', 'item_url'):
        raise ValueError("item_id_basis must be 'row_index' or 'item_url'")
    if not isinstance(raw, dict):
        raise ValueError('raw list payload must be an object')
    source_url = raw.get('source_url', '')
    parts = urlsplit(source_url)
    if parts.scheme != 'https' or not parts.hostname:
        raise ValueError('save an https order-list source url')
    orders = []
    for entry in raw.get('orders', []):
        rows = entry.get('rows')
        if not isinstance(rows, list) or not rows:
            raise ValueError('each order needs product rows')
        order_id = extract_order_id(entry.get('order_id_text'), entry.get('detail_url'))
        real_ids = resolve_item_identities(rows) if item_id_basis == 'item_url' else None
        items = []
        for i, row in enumerate(rows):
            if real_ids is not None:
                items.append(_normalize_item(real_ids[i], 'item_url_id', row))
            else:
                items.append(_normalize_item(build_item_id(order_id, i),
                                             'order_row_index', row))
        success = is_success_status(entry.get('status'))
        paid = parse_paid_amount(entry.get('payment_text'))
        orders.append({
            'order_id': order_id,
            'placed_at': _list_date_to_iso(entry.get('order_date')),
            'raw_placed_at': entry.get('order_date'),
            'date_precision': 'day',
            'raw_status': entry.get('status'),
            'is_success': success,
            'currency': 'CNY',
            'paid_amount': paid,
            'refund_amount': None,
            'amount_basis': 'original_paid' if paid else 'unknown',
            'url': entry.get('detail_url'),
            'items': items,
        })
    return {
        'account_key': account_key,
        'cursor': str(cursor),
        'next_cursor': None if next_cursor is None else str(next_cursor),
        'orders': orders,
        'evidence': {'source_url': source_url, 'note': evidence_note},
    }


def _beijing_iso(value):
    """'2026-10-15 01:56:16' -> '2026-10-15T01:56:16+08:00'."""
    match = re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}:[0-9]{2}:[0-9]{2})', value or '')
    if not match:
        raise ValueError('invalid detail timestamp: ' + str(value))
    return match.group(1) + 'T' + match.group(2) + '+08:00'


def normalize_detail(raw):
    """Return exact created_at, paid amount and order image from a detail page."""
    if not isinstance(raw, dict):
        raise ValueError('raw detail payload must be an object')
    created = (raw.get('times') or {}).get('创建时间')
    amounts = raw.get('amounts') or {}
    return {
        'placed_at': _beijing_iso(created) if created else None,
        'paid_amount': amounts.get('实付款'),
        'main_image': raw.get('main_image'),
    }


def merge_detail_into_order(order, detail):
    """Apply an on-demand detail read to a normalized order.

    The exact created_at replaces the list-level midnight timestamp while the
    raw list date is kept. Amounts are cross-checked: a disagreement is flagged
    for review rather than silently overwritten. The detail's order image is the
    same 200x200 source as the list, so item sources are left untouched.
    """
    merged = copy.deepcopy(order)
    if detail.get('placed_at'):
        merged['placed_at'] = detail['placed_at']
        merged['date_precision'] = 'second'
    detail_paid = detail.get('paid_amount')
    if detail_paid is not None:
        list_paid = order.get('paid_amount')
        if list_paid is not None and list_paid != detail_paid:
            merged['amount_basis'] = 'unknown'
            merged['amount_review_required'] = True
            merged['amount_note'] = (
                f'列表实付{list_paid}与详情实付{detail_paid}不一致，待人工核对')
        else:
            merged['paid_amount'] = detail_paid
            if not merged.get('amount_review_required'):
                merged['amount_basis'] = 'original_paid'
    return merged


# ---------------------------------------------------------------------------
# Host-driven date filter (real browser clicks; the picker is React controlled).
# ---------------------------------------------------------------------------
def apply_date_filter(bu, start, end, set_range=None):
    """Optional verified host callback; default collection never operates the picker.

    The old one-prev-click sequence could not select an arbitrary ten-year range.
    A host may supply set_range(bu, start, end), after verifying the controlled
    picker and the effective submitted range. Do not treat input values alone as
    proof of server-side filtering.
    """
    from datetime import date
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('reversed date window')
    if set_range is None:
        raise ValueError('date filter is optional: collect the default list and filter locally; '
                         'provide a harness-verified set_range callback only when needed')
    result = set_range(bu, start, end)
    if not isinstance(result, dict) or result.get('verified') is not True or result.get('applied_range') != {'start':start, 'end':end}:
        raise ValueError('effective date range was not verified; keep the existing collection checkpoint')
    return result
