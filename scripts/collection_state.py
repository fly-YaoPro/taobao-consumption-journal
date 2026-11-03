#!/usr/bin/env python3
"""Persist batches observed through the normal browser; no platform API or login access."""
import argparse
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from journal_io import load, save

PARENT = {'order_id', 'placed_at', 'raw_status', 'is_success', 'currency', 'paid_amount',
          'refund_amount', 'amount_basis', 'url', 'category', 'display_title', 'items',
          'raw_placed_at', 'paid_amount_label', 'refund_amount_label', 'amount_note',
          'refund_status', 'source_observed_at', 'date_precision', 'amount_review_required'}
ITEM = {'item_id', 'item_id_basis', 'name', 'spec', 'quantity', 'source_url', 'origin',
        'provided_reference', 'image_path', 'image_status', 'image_error', 'image_sha256', 'image_dimensions'}


def initialize(root, account_key, start, end, cursor='1'):
    root = Path(root)
    if not isinstance(account_key, str) or not account_key.strip() or not isinstance(cursor, str) or not cursor:
        raise ValueError('use a nonempty account alias and string cursor')
    if date.fromisoformat(start) > date.fromisoformat(end): raise ValueError('reversed date window')
    config = {'account_key': account_key, 'requested_range': {'start': start, 'end': end}}
    meta = load(root / 'project_meta.json', {})
    if meta.get('requested_range') and meta['requested_range'] != config['requested_range']:
        raise ValueError('collection window differs from project; use the established range')
    prior = load(root / 'collection-state.json')
    if prior:
        if any(prior.get(k) != v for k, v in config.items()):
            raise ValueError('checkpoint belongs to another account/window; keep it and use a new project')
        return prior
    state = {**config, 'next_cursor': cursor, 'status': 'ready', 'pages': [], 'next_allowed_at': 0}
    save(root / 'collection-state.json', state)
    return state


def merge_orders(existing, incoming):
    merged = {o['order_id']: o for o in existing}
    for new in incoming:
        old = merged.get(new['order_id'], {})
        prior_items = {i['item_id']: i for i in old.get('items', [])}
        for item in new['items']:
            prior = prior_items.get(item['item_id'], {})
            value = {**prior, **item}
            if item.get('source_url') is None and prior.get('source_url'):
                value['source_url'] = prior['source_url']
            same_source = item.get('source_url') in (None, prior.get('source_url'))
            if prior.get('image_status') == 'saved' and same_source:
                for key in ('image_path', 'image_status', 'image_sha256', 'image_dimensions'):
                    if key in prior: value[key] = prior[key]
            elif not same_source:
                # A new source must not inherit a previously bound image silently.
                value['image_path'] = item.get('image_path')
                value['image_status'] = item.get('image_status', 'unavailable')
                for key in ('image_sha256', 'image_dimensions'): value.pop(key, None)
            prior_items[item['item_id']] = value
        value = {**old, **new, 'items': list(prior_items.values())}
        for key in ('paid_amount', 'refund_amount'):
            if new.get(key) is None and old.get(key) is not None:
                value[key] = old[key]
        if new.get('amount_basis') == 'unknown' and old.get('amount_basis') in {'original_paid', 'net_after_refund'} and not new.get('amount_review_required'):
            value['amount_basis'] = old['amount_basis']
        if old.get('date_precision') == 'second' and new.get('date_precision') == 'day' and old['placed_at'][:10] == new['placed_at'][:10]:
            value['placed_at'], value['date_precision'] = old['placed_at'], 'second'
        merged[new['order_id']] = value
    return sorted(merged.values(), key=lambda o: (o['placed_at'], o['order_id']))


def commit_page(root, batch, clock=time.time, observed_online=True):
    root = Path(root)
    state = load(root / 'collection-state.json')
    if not state: raise ValueError('initialize collection state first')
    if state['status'] == 'blocked': raise ValueError('normal browser verification is required before resume')
    if state['status'] == 'complete': return state
    if batch.get('account_key') != state['account_key'] or batch.get('cursor') != state['next_cursor']:
        raise ValueError('batch account/cursor does not match checkpoint')
    observed = batch.get('evidence', {})
    source = urlsplit(observed.get('source_url', ''))
    if source.scheme != 'https' or not source.hostname or source.username or source.password or not str(observed.get('note', '')).strip():
        raise ValueError('save actual normal-browser source and observation note')
    incoming = batch.get('orders')
    if not isinstance(incoming, list): raise ValueError('orders must be an array')
    next_cursor = batch.get('next_cursor')
    if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor or next_cursor == state['next_cursor']):
        raise ValueError('cursor must advance; do not loop over the same page')
    terminal = next_cursor is None
    if terminal and batch.get('end_verified') is not True:
        status = 'verify_boundary'
    else:
        status = 'complete' if terminal else 'ready'
    clean, seen = [], set()
    for order in incoming:
        oid = order.get('order_id')
        if not isinstance(oid, str) or not oid or oid in seen:
            raise ValueError('order IDs must be nonempty unique strings')
        seen.add(oid)
        dt = datetime.fromisoformat(order['placed_at'].replace('Z', '+00:00'))
        if dt.tzinfo is None: raise ValueError('original order date needs timezone')
        day = dt.astimezone(timezone(timedelta(hours=8))).date().isoformat()
        if not state['requested_range']['start'] <= day <= state['requested_range']['end']: continue
        if order.get('is_success') is not True: continue
        if not isinstance(order.get('items'), list) or not order['items']: raise ValueError('each order needs product rows')
        item_ids = set()
        for item in order['items']:
            iid = item.get('item_id')
            if not isinstance(iid, str) or not iid or iid in item_ids: raise ValueError('invalid product-row ID')
            item_ids.add(iid)
        # Cache only the normalized fields used by this skill, never a raw page/body.
        value = {k: v for k, v in order.items() if k in PARENT}
        value['items'] = [{k: v for k, v in i.items() if k in ITEM} for i in order['items']]
        clean.append(value)
    cached = {'account_key': state['account_key'], 'cursor': batch['cursor'], 'next_cursor': next_cursor,
        'orders': clean, 'evidence': {'source_url': observed['source_url'], 'note': observed['note']},
        'end_verified': batch.get('end_verified') is True}
    observation = batch.get('observation', {})
    cached['observation'] = {k: observation[k] for k in
        ('active', 'content_sha256', 'order_ids_sha256', 'all_order_count', 'earliest_date', 'latest_date', 'next_disabled') if k in observation}
    key = hashlib.sha256(batch['cursor'].encode()).hexdigest()
    cache = root / 'collection-cache' / (key + '.json')
    save(cache, cached)  # Cache before merging, so a crash can replay without another browser read.
    save(root / 'orders.json', merge_orders(load(root / 'orders.json', []), clean))
    state['pages'] = [p for p in state['pages'] if p['cursor'] != batch['cursor']]
    state['pages'].append({'cursor': batch['cursor'], 'cache': cache.relative_to(root).as_posix(),
        'saved_orders': len(clean), 'boundary_verified': cached['end_verified'], 'observation': cached['observation']})
    state.update(status=status, next_cursor=next_cursor if not terminal else batch['cursor'],
                 next_allowed_at=clock() + 4 if observed_online else state.get('next_allowed_at', 0))
    save(root / 'collection-state.json', state)
    return state


def collect(root, read_page, max_pages=5, deadline_seconds=45, clock=time.time, sleep=time.sleep):
    """read_page(cursor) uses the host's already-verified normal browser capability."""
    if type(max_pages) is not int or not 1 <= max_pages <= 10 or not 0 < deadline_seconds <= 120:
        raise ValueError('one batch:1..10 pages, up to120 seconds')
    root = Path(root)
    deadline, processed, cache_hits = clock() + deadline_seconds, 0, 0
    state = load(root / 'collection-state.json')
    if not state: raise ValueError('initialize collection state first')
    while processed < max_pages and state['status'] == 'ready':
        if clock() >= deadline: break
        key = hashlib.sha256(state['next_cursor'].encode()).hexdigest()
        try:
            cached = load(root / 'collection-cache' / (key + '.json'))
        except (OSError, ValueError):
            state.update(status='blocked', reason='invalid_cached_page')
            save(root / 'collection-state.json', state)
            break
        if cached is None:
            wait_seconds = max(0, state.get('next_allowed_at', 0) - clock())
            if clock() + wait_seconds >= deadline: break
            if wait_seconds: sleep(wait_seconds)
        batch = cached if cached is not None else read_page(state['next_cursor'])
        if batch.get('status') == 'yield':
            break
        if batch.get('status') in ('blocked', 'login_required', 'rate_limited'):
            state.update(status='blocked', reason=batch.get('reason', batch['status']))
            save(root / 'collection-state.json', state)
            break
        state = commit_page(root, batch, clock, observed_online=cached is None)
        cache_hits += int(cached is not None)
        processed += 1
    return {'status': state['status'], 'processed_pages': processed, 'cache_hits': cache_hits,
            'next_cursor': state['next_cursor'], 'saved_orders': len(load(root / 'orders.json', [])),
            'wait_seconds': max(0, round(state.get('next_allowed_at', 0) - clock(), 2)),
            'reason': state.get('reason')}


def resume(root, note):
    if not isinstance(note, str) or not note.strip(): raise ValueError('record successful normal browser re-verification')
    root = Path(root)
    state = load(root / 'collection-state.json')
    if not state: raise ValueError('no checkpoint')
    if state['status'] == 'complete': return state
    if state['status'] == 'verify_boundary':
        if state.get('boundary_retry_used'):
            return state
        # Discard just the unverified terminal observation so one fresh read is possible.
        key = hashlib.sha256(state['next_cursor'].encode()).hexdigest()
        path = root / 'collection-cache' / (key + '.json')
        if path.exists():
            previous = load(path)
            save(root / 'boundary-observations' / (key + '.json'), previous)
            path.unlink()
        state['boundary_retry_used'] = True
    state.update(status='ready', verification_note=note)
    state.pop('reason', None)
    save(root / 'collection-state.json', state)
    return state


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('project', type=Path)
    sub = p.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    for key in ('account-key', 'start', 'end'): init.add_argument('--' + key, required=True)
    init.add_argument('--cursor', default='1')
    ingest = sub.add_parser('ingest'); ingest.add_argument('--input', required=True, type=Path)
    sub.add_parser('status')
    recover = sub.add_parser('resume'); recover.add_argument('--note', required=True)
    a = p.parse_args()
    try:
        if a.command == 'init': result = initialize(a.project, a.account_key, a.start, a.end, a.cursor)
        elif a.command == 'ingest': result = commit_page(a.project, load(a.input))
        elif a.command == 'resume': result = resume(a.project, a.note)
        else: result = load(a.project / 'collection-state.json')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        p.exit(1, str(exc) + '\n')
