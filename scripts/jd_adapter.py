#!/usr/bin/env python3
"""Read-only normal-browser adapter for the observed JD desktop order list.

The host handles login, verification, navigation and visible pagination. This
module only reads the current order-list DOM and normalizes its whitelisted
fields. It neither calls platform interfaces nor collects delivery/contact
blocks. The selector contract must be rechecked when JD changes its UI.
"""
from datetime import datetime
import re
from urllib.parse import urlsplit


ORDER_LIST_HOSTS = frozenset({'order.jd.com', 'order.jd.hk'})
ORDER_LIST_PATH = '/center/list.action'
SUCCESS_STATUS = '已完成'


LIST_PAGE_SCRIPT = r"""
(() => {
  const t = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  const sel = prefix => '[class^="' + prefix + '-"],[class*=" ' + prefix + '-"]';
  const q = (root, prefix) => root ? root.querySelector(sel(prefix)) : null;
  const qa = (root, prefix) => root ? Array.from(root.querySelectorAll(sel(prefix))) : [];
  const has = (e, prefix) => !!e && e.matches(sel(prefix));
  const visible = e => !!e && e.getClientRects().length > 0;
  const https = value => value && value.startsWith('//') ? 'https:' + value : value || null;
  const productLink = value => {
    if (!value) return null;
    try {
      const u = new URL(value);
      return u.protocol === 'https:' && ['item.jd.com','item.jd.hk'].includes(u.hostname) &&
        !u.username && !u.password && (!u.port || u.port === '443') && /^\/[0-9]{6,30}\.html$/.test(u.pathname)
        ? u.origin + u.pathname : null;
    } catch (_) { return null; }
  };
  const list = q(document, 'listContent');
  const parentBanner = card => {
    for (let e = card.parentElement; e && e !== list; e = e.parentElement) {
      if (has(e.firstElementChild, 'splitBanner')) return e.firstElementChild;
    }
    return null;
  };
  const labelledValue = (root, label) => {
    const group = qa(root, 'infoGroup').find(e => t(e).includes(label));
    return group ? t(q(group, 'metaValue')) || t(group) : null;
  };
  // A split group's second card can be in a separate list child with no banner.
  // Carry only the most recent banner in this page's DOM order, clear it at a
  // normal header, and never infer a page-start parent from a previous page.
  let carriedParentText = null;
  const orders = qa(list, 'orderCard').map(card => {
    const header = q(card, 'header');
    const left = q(header, 'headerLeft');
    const right = q(header, 'headerRight');
    const banner = parentBanner(card);
    const isSplit = !!banner || has(header, 'splitOrderHeader');
    if (banner) carriedParentText = labelledValue(banner, '订单号');
    else if (!isSplit) carriedParentText = null;
    const time = q(left, 'orderTime');
    const metas = qa(left, 'orderMetas').find(e => /订单号|订单编号/.test(t(e)));
    const payment = q(card, 'priceActionSection');
    const price = q(q(q(payment, 'paymentTypestyle'), 'priceColumn'), 'priceRow');
    const detail = q(card, 'detailLink');
    const detailAnchor = detail && (detail.matches('a[href]') ? detail : detail.querySelector('a[href]'));
    const rows = qa(card, 'productItem').map(row => {
      const good = q(row, 'goodImg');
      const img = good && good.querySelector('img');
      return {
        name: t(q(row, 'productTitle')),
        quantity_text: t(q(row, 'productCount')),
        image_url: img ? https(img.currentSrc || img.getAttribute('src')) : null,
        image_pending: !img && !!(good && good.querySelector('.lazyload-placeholder')),
        item_url: productLink(good && good.matches('a[href]') ? good.href : null)
      };
    });
    return {
      order_date: t(q(time, 'metaValue')) || t(time),
      order_id_text: t(metas),
      shop: t(q(q(left, 'shopInfo'), 'shopNames')),
      status: t(q(q(right, 'rightStateStyle'), 'statusText')),
      detail_url: detailAnchor ? detailAnchor.href : null,
      payment_text: t(price),
      is_split_order: isSplit,
      parent_order_id_text: isSplit ? carriedParentText : null,
      rows
    };
  });
  const pages = q(document, 'pageNumbers');
  const active = qa(pages, 'pageItem').find(e => has(e, 'activePage') || !!q(e, 'activePage')) || q(pages, 'activePage');
  const next = q(pages, 'nextBtn');
  const prev = q(pages, 'prevBtn');
  const selected = Array.from(document.querySelectorAll('select')).find(visible);
  const customPeriod = qa(document, 'select').filter(visible)
    .flatMap(e => Array.from(e.querySelectorAll('span')).filter(visible).map(t))
    .find(s => /^(?:近[0-9一二三四五六七八九十]+个月订单|今年内订单|[0-9]{4}年订单)$/.test(s));
  const selectedPeriod = selected ? t(selected.selectedOptions && selected.selectedOptions[0]) :
    customPeriod || Array.from(document.querySelectorAll('[role="combobox"]')).filter(visible).map(t).find(s => /订单/.test(s)) || null;
  const login = Array.from(document.querySelectorAll('input[type="password"]')).some(visible);
  const blocked = Array.from(document.querySelectorAll('[role="alert"],[class*="verify"],[class*="captcha"]'))
    .some(e => visible(e) && /验证|验证码|访问受限|请求过于频繁/.test(t(e)));
  const loading = Array.from(document.querySelectorAll('[aria-busy="true"],[class^="loading-"]')).some(visible);
  const emptyMessage = Array.from(document.querySelectorAll('[class*="empty"]')).filter(visible)
    .map(t).find(s => /^没有相关订单哦[~～!！。]?/.test(s)) || null;
  return JSON.stringify({
    source_url: location.href,
    route_status: login ? 'login_required' : blocked ? 'blocked' : loading ? 'loading' : orders.length ? 'ready' : emptyMessage ? 'empty' : 'empty_or_unrecognized',
    empty_message: emptyMessage,
    selected_period: selectedPeriod,
    pagination: {
      active: t(active) || null,
      page_items: qa(pages, 'pageItem').map(t).filter(s => /^\d+$/.test(s)),
      next_disabled: next ? !!next.disabled || next.getAttribute('aria-disabled') === 'true' : null,
      prev_disabled: prev ? !!prev.disabled || prev.getAttribute('aria-disabled') === 'true' : null
    },
    orders
  });
})()
"""


def validate_list_url(value):
    """Allow only the desktop list locations actually observed in this release."""
    if not isinstance(value, str):
        raise ValueError('JD order-list URL is required')
    parts = urlsplit(value)
    if (parts.scheme != 'https' or parts.hostname not in ORDER_LIST_HOSTS
            or parts.path != ORDER_LIST_PATH or parts.username or parts.password
            or parts.port not in (None, 443)):
        raise ValueError('expected the verified HTTPS JD order-list page')
    return value


def extract_order_id(value):
    """Keep long platform ids as strings; only use the labelled order field."""
    if not isinstance(value, str):
        raise ValueError('order id text is missing')
    labelled = re.findall(r'(?:订单号|订单编号)\s*[:：]?\s*([0-9]{6,30})(?!\d)', value)
    # Split banners may expose the metaValue alone, after its label was checked
    # by the DOM reader. Do not accept arbitrary text containing a bare number.
    matches = labelled or ([value.strip()] if re.fullmatch(r'[0-9]{6,30}', value.strip()) else [])
    if len(matches) != 1:
        raise ValueError('order id missing or ambiguous; verify the labelled field')
    return matches[0]


def parse_quantity(value):
    if not isinstance(value, str):
        raise ValueError('quantity missing; verify the product row')
    match = re.fullmatch(r'\s*共\s*([0-9]+)\s*件\s*', value)
    if not match or int(match[1]) < 1:
        raise ValueError('quantity missing or ambiguous; do not assume one')
    return int(match[1])


def parse_observed_amount(value):
    """Retain a single displayed price, never promote it to paid/net amount."""
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ValueError('observed price label must be text')
    compact = re.sub(r'\s+', '', value)
    match = re.fullmatch(r'[￥¥]([0-9]+(?:\.[0-9]{1,2})?)', compact)
    return match[1] if match else None


def parse_item_url_id(value):
    """Optional exact SKU from an actual visible JD product link, not guessed."""
    if not value or not isinstance(value, str):
        return None
    parts = urlsplit(value)
    if (parts.scheme != 'https' or parts.hostname not in {'item.jd.com', 'item.jd.hk'}
            or parts.username or parts.password or parts.port not in (None, 443)):
        return None
    match = re.fullmatch(r'/([0-9]{6,30})\.html', parts.path)
    return match[1] if match else None


def resolve_item_identities(rows):
    values = [parse_item_url_id(row.get('item_url')) for row in rows]
    return values if values and all(values) and len(values) == len(set(values)) else None


def is_success_status(value):
    return value == SUCCESS_STATUS


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        raise ValueError('verified JD order timestamp is required')
    parsed = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    return parsed.isoformat() + '+08:00'


def normalize_list_page(raw, account_key, cursor, evidence_note, next_cursor=None):
    """Normalize only card orders, never split-banner aggregate payments.

    Raw non-success records remain in this observation batch. The collection
    layer decides inclusion; status changes must not be silently discarded.
    """
    if not isinstance(raw, dict):
        raise ValueError('raw JD list payload must be an object')
    source = validate_list_url(raw.get('source_url'))
    if not isinstance(account_key, str) or not account_key.strip():
        raise ValueError('verified local account alias is required')
    if not isinstance(evidence_note, str) or not evidence_note.strip():
        raise ValueError('actual observation note is required')
    if not isinstance(raw.get('orders'), list):
        raise ValueError('orders must be an array')
    orders, ids = [], set()
    for entry in raw['orders']:
        if not isinstance(entry, dict):
            raise ValueError('order card must be an object')
        oid = extract_order_id(entry.get('order_id_text'))
        if oid in ids:
            raise ValueError('repeated card order id; verify split groups and pagination')
        ids.add(oid)
        status = entry.get('status')
        if not isinstance(status, str) or not status.strip():
            raise ValueError('order status missing; recheck this card')
        rows = entry.get('rows')
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError('each card order requires its actual product rows')
        real_ids = resolve_item_identities(rows)
        items = []
        for number, row in enumerate(rows):
            name = row.get('name')
            if not isinstance(name, str) or not name.strip():
                raise ValueError('product title missing; verify the row')
            image_url = row.get('image_url')
            if image_url is not None:
                parts = urlsplit(image_url)
                if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
                    raise ValueError('observed product image URL is invalid')
            items.append({
                'item_id': real_ids[number] if real_ids else f'{oid}-{number:02d}',
                'item_id_basis': 'item_url_id' if real_ids else 'order_row_index',
                'name': name.strip(), 'spec': None,
                'quantity': parse_quantity(row.get('quantity_text')),
                'product_url': (f"https://{urlsplit(row['item_url']).hostname}{urlsplit(row['item_url']).path}"
                                if parse_item_url_id(row.get('item_url')) else None),
                'source_url': image_url, 'origin': 'platform' if image_url else None,
                'image_path': None, 'image_status': 'unavailable',
            })
            if row.get('image_pending') and not image_url:
                items[-1]['image_error'] = 'lazy image not loaded; normally scroll this page and reobserve before concluding missing'
        parent_text = entry.get('parent_order_id_text')
        parent_id = extract_order_id(parent_text) if parent_text else None
        if parent_id == oid:
            raise ValueError('split parent id equals child id; verify the split group')
        detail_url = entry.get('detail_url')
        if detail_url is not None:
            parts = urlsplit(detail_url)
            if (parts.scheme != 'https' or parts.hostname not in ORDER_LIST_HOSTS
                    or parts.username or parts.password or parts.port not in (None, 443)):
                raise ValueError('detail URL must be an actual verified JD order link')
        label = entry.get('payment_text')
        observed = parse_observed_amount(label)
        orders.append({
            'platform': 'jd', 'order_id': oid,
            'parent_order_id': parent_id,
            'split_relation_uncertain': bool(entry.get('is_split_order') and not parent_id),
            'placed_at': _timestamp(entry.get('order_date')),
            'raw_placed_at': entry.get('order_date'), 'date_precision': 'second',
            'raw_status': status, 'is_success': is_success_status(status),
            'currency': 'CNY', 'paid_amount': None, 'refund_amount': None,
            'amount_basis': 'unknown',
            'observed_amount': observed, 'observed_amount_label': label,
            'amount_note': '列表金额未明确标记实付或净额，仅保留观察值；不将拆单父总额另计。',
            'url': detail_url or source, 'items': items,
        })
    return {
        'platform': 'jd', 'account_key': account_key,
        'cursor': str(cursor), 'next_cursor': None if next_cursor is None else str(next_cursor),
        'orders': orders,
        'evidence': {'source_url': source, 'note': evidence_note.strip()},
    }
