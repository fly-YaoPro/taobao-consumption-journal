"""Bounded normal-browser list collection. No login, private API or JS clicks.

Import in the host browser execution environment. bu.js reads the current DOM;
advance_page(bu, target_page) must use the host's verified normal pagination UI.
Only compact summaries leave this module; normalized pages are committed locally.
"""
import hashlib
import json
import re
from pathlib import Path
import time
from urllib.parse import urlsplit

from collection_state import initialize, commit_page, collect, resume
from journal_io import load, save
from taobao_adapter import LIST_PAGE_SCRIPT, normalize_list_page, extract_order_id


class ObservationError(ValueError):
    pass


def _failure_reason(exc, prefix):
    if isinstance(exc, ObservationError):
        return str(exc)
    code = getattr(exc, 'code', None)
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,79}', code):
        match = re.search(r'\bBU_[A-Z0-9_]+\b', str(exc))
        code = match[0] if match else None
    return prefix + type(exc).__name__ + (':' + code if code else '')


def _decode(bu):
    raw = bu.js(LIST_PAGE_SCRIPT)
    raw = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(raw, dict):
        raise ObservationError('invalid_dom_payload')
    url = urlsplit(raw.get('source_url', ''))
    if (url.scheme != 'https' or url.hostname != 'buyertrade.taobao.com'
            or url.path != '/trade/itemlist/list_bought_items.htm' or url.username or url.password):
        raise ObservationError('wrong_order_list_page')
    status = raw.get('route_status')
    if status in {'login_required', 'blocked'}:
        raise ObservationError(status)
    if status not in {'ready', 'loading', 'empty_or_unrecognized'}:
        raise ObservationError('adapter_reverification_required')
    return raw


def _fingerprint(raw):
    # All visible orders, including non-success, participate in page identity.
    values = [(extract_order_id(o.get('order_id_text'), o.get('detail_url')),
               o.get('order_date'), o.get('status'), o.get('rows')) for o in raw.get('orders', [])]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _identity(raw):
    ids = sorted(extract_order_id(o.get('order_id_text'), o.get('detail_url')) for o in raw.get('orders', []))
    return hashlib.sha256(json.dumps(ids).encode('utf-8')).hexdigest()


def _capture(bu, *, expected=None, previous=None, deadline, clock, sleep, counters):
    stable = None
    # Bounded polling replaces fixed full-page load sleeps. It cannot interrupt a
    # blocked host call; the outer Harness tool must also have a real timeout.
    for _ in range(8):
        if clock() >= deadline:
            return None
        counters['dom_reads'] += 1
        raw = _decode(bu)
        pg = raw.get('pagination') or {}
        active = str(pg.get('active') or '')
        if not active.isdigit():
            raise ObservationError('pagination_not_recognized')
        if type(pg.get('next_disabled')) is not bool:
            raise ObservationError('next_button_state_unknown')
        signature = _fingerprint(raw)
        valid = (raw['route_status'] != 'loading' and (expected is None or active == str(expected))
                 and (previous is None or _identity(raw) != previous))
        token = (active, signature, pg['next_disabled'])
        if valid and stable == token:
            return raw, signature
        stable = token if valid else None
        if clock() < deadline:
            sleep(min(.2, max(0, deadline-clock())))
    raise ObservationError('page_not_stable_or_not_advanced')


def _batch(raw, signature, config, cursor):
    pg = raw['pagination']
    terminal = pg['next_disabled'] or not raw['orders']
    batch = normalize_list_page(raw, config['account_key'], str(cursor),
                               'Stable normal order-list DOM; no date-picker prerequisite.',
                               next_cursor=None if terminal else str(int(cursor)+1),
                               item_id_basis=config.get('item_id_basis', 'row_index'))
    # A nonempty stable last page with an actual disabled next control is direct
    # terminal evidence. Empty DOM still needs one normal-page boundary review.
    batch['end_verified'] = bool(terminal and raw['orders'])
    dates = sorted(o['order_date'] for o in raw['orders'])
    batch['observation'] = {'active': str(cursor), 'content_sha256': signature,
                            'order_ids_sha256': _identity(raw),
                            'all_order_count': len(raw['orders']), 'next_disabled': terminal,
                            'earliest_date': dates[0] if dates else None,
                            'latest_date': dates[-1] if dates else None}
    return batch


def _context(root):
    root = Path(root)
    config = load(root / 'browser-collection.json')
    state = load(root / 'collection-state.json')
    meta = load(root / 'project_meta.json', {})
    if not config or not state:
        raise ValueError('configure_browser first on the verified first order-list page')
    if (config['account_key'] != state['account_key'] or config['requested_range'] != state['requested_range']
            or config['requested_range'] != meta.get('requested_range')):
        raise ValueError('browser configuration/account/window differs from checkpoint')
    return root, config, state


def _summary(root, state, **extra):
    return {'status': 'handoff' if state['status'] == 'blocked' else state['status'],
            'next_cursor': state['next_cursor'], 'saved_orders': len(load(root / 'orders.json', [])),
            'reason': state.get('reason'), **extra}


def configure_browser(bu, root, account_key, *, item_id_basis='row_index',
                      clock=time.time, sleep=time.sleep):
    """Save the first full list page immediately, after normal identity verification.

    item_id_basis stays 'row_index' unless the Harness has verified unstable row
    order and explicitly opts into the real 'item_url' identity; the choice is
    bound in browser-collection.json and reused by every later process.
    """
    if item_id_basis not in ('row_index', 'item_url'):
        raise ValueError("item_id_basis must be 'row_index' or 'item_url'")
    root = Path(root)
    meta = load(root / 'project_meta.json', {})
    if meta.get('platform') != 'taobao':
        raise ValueError('Taobao project_meta is required')
    bounds = meta['requested_range']
    state = initialize(root, account_key, bounds['start'], bounds['end'])
    config = {'account_key': account_key, 'requested_range': bounds,
              'route': 'normal_list_dom', 'item_id_basis': item_id_basis}
    prior = load(root / 'browser-collection.json')
    if prior and prior != config:
        raise ValueError('keep the established browser configuration and checkpoint')
    save(root / 'browser-collection.json', config)
    if state['status'] in {'blocked', 'complete', 'verify_boundary'}:
        return _summary(root, state, resumed=True)
    counters = {'dom_reads': 0}
    try:
        found = _capture(bu, deadline=clock()+8, clock=clock, sleep=sleep, counters=counters)
        if found is None:
            return {'status':'setup_required', 'reason':'initial_snapshot_budget', **counters}
        raw, signature = found
        current = str(raw['pagination']['active'])
        if not state['pages']:
            if current != '1' or state['next_cursor'] != '1':
                return {'status':'setup_required', 'reason':'first_page_required', **counters}
            save(root / 'browser-collection.json', config)
            state = commit_page(root, _batch(raw, signature, config, '1'), clock)
            return _summary(root, state, first_page_saved=True, **counters)
        save(root / 'browser-collection.json', config)
        return _summary(root, state, resumed=True, **counters)
    except Exception as exc:
        reason = _failure_reason(exc, 'initial_read_failed:')
        # No automatic retry of tool timeouts or schema mismatches.
        state.update(status='blocked', reason=reason)
        save(root / 'collection-state.json', state)
        return _summary(root, state, **counters)


def collect_browser(bu, root, advance_page, *, max_pages=5, deadline_seconds=45,
                    clock=time.time, sleep=time.sleep):
    """Capture/commit up to N pages in one host call; normal pagination is serial."""
    if type(max_pages) is not int or not 1 <= max_pages <= 10 or not 0 < deadline_seconds <= 120:
        raise ValueError('one batch:1..10 pages, up to120 seconds')
    if not callable(advance_page):
        raise ValueError('supply a harness-verified normal pagination callback')
    root, config, state = _context(root)
    started = clock()
    deadline = started + deadline_seconds
    counters = {'dom_reads': 0, 'page_actions': 0}

    def read_page(cursor):
        try:
            counters['dom_reads'] += 1
            raw = _decode(bu)
            pg = raw.get('pagination') or {}
            active = str(pg.get('active') or '')
            if not active.isdigit():
                raise ObservationError('pagination_not_recognized')
            if active != cursor:
                if int(active) != int(cursor)-1 or pg.get('next_disabled') is not False:
                    raise ObservationError('resume_position_required')
                if raw['route_status'] == 'loading':
                    return {'status':'yield'}
                if clock() >= deadline:
                    return {'status':'yield'}
                counters['page_actions'] += 1
                advance_page(bu, int(cursor))
            current_state = load(root / 'collection-state.json')
            pages = current_state.get('pages', [])
            previous = (pages[-1].get('observation') or {}).get('order_ids_sha256') if pages else None
            found = _capture(bu, expected=cursor, previous=previous, deadline=min(deadline,clock()+8),
                             clock=clock, sleep=sleep, counters=counters)
            if found is None:
                return {'status':'yield'}
            raw, signature = found
            return _batch(raw, signature, config, cursor)
        except Exception as exc:
            reason = _failure_reason(exc, 'browser_route_failed:')
            return {'status':'blocked', 'reason':reason}

    try:
        result = collect(root, read_page, max_pages=max_pages, deadline_seconds=deadline_seconds, clock=clock, sleep=sleep)
    except (ValueError, KeyError, TypeError) as exc:
        current = load(root / 'collection-state.json')
        current.update(status='blocked', reason='page_commit_failed:' + type(exc).__name__)
        save(root / 'collection-state.json', current)
        result = _summary(root, current, processed_pages=len(current['pages'])-len(state['pages']), cache_hits=0)
    if result['status'] == 'blocked':
        result['status'] = 'handoff'
    elif result['status'] == 'ready' and not result['processed_pages']:
        result['status'] = 'cooldown'
    result.update(counters, elapsed_seconds=round(clock()-started, 3))
    # Deliberately no product titles, raw DOM, credentials or original IDs here.
    history = load(root / 'collection-metrics.json', [])
    history.append(result)
    save(root / 'collection-metrics.json', history)
    return result


def resume_browser(bu, root, note, *, clock=time.time, sleep=time.sleep):
    """Explicit normal-page re-verification, retaining existing orders and cursor."""
    root, config, state = _context(root)
    if not isinstance(note, str) or not note.strip():
        raise ValueError('normal-page verification note is required')
    found = _capture(bu, deadline=clock()+8, clock=clock, sleep=sleep, counters={'dom_reads':0})
    if not found:
        return {'status':'handoff', 'reason':'verification_budget'}
    current = int(found[0]['pagination']['active'])
    if current not in {int(state['next_cursor']), int(state['next_cursor'])-1}:
        return {'status':'handoff', 'reason':'resume_position_required', 'next_cursor':state['next_cursor']}
    return _summary(root, resume(root, note))
