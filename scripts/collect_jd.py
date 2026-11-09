"""Bounded JD annual-list collection using the host's normal UI callbacks.

No login, cookies, guessed page URLs or platform interfaces. Period selection,
pagination and lazy-image scrolling are injected normal-browser operations.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from collection_state import initialize, commit_page, collect, resume, bound_platform
from jd_adapter import LIST_PAGE_SCRIPT, extract_order_id, normalize_list_page, validate_list_url
from journal_io import load, save


class ObservationError(ValueError):
    pass


def _fail_reason(exc):
    return str(exc) if isinstance(exc, ObservationError) else 'jd_browser_read_failed:' + type(exc).__name__


def _periods(meta, values):
    bounds = meta['requested_range']
    start, end = date.fromisoformat(bounds['start']), date.fromisoformat(bounds['end'])
    if start > end or not isinstance(values, list) or not values:
        raise ValueError('provide annual periods covering the requested range')
    result, labels = [], set()
    current_year = datetime.now(timezone(timedelta(hours=8))).year
    for value in values:
        label = value.get('label') if isinstance(value, dict) else None
        match = re.fullmatch(r'([0-9]{4})年订单', label or '')
        year = int(match[1]) if match else current_year if label == '今年内订单' else None
        if year is None or label in labels:
            raise ValueError('use unique, verified annual labels; a recent-three-month filter is not annual coverage')
        begin, finish = date.fromisoformat(value['start']), date.fromisoformat(value['end'])
        if not start <= begin <= finish <= end or begin.year != year or finish.year != year:
            raise ValueError('period dates must belong to its labelled year and the requested range')
        labels.add(label)
        result.append({'label': label, 'start': begin.isoformat(), 'end': finish.isoformat(), 'year': year})
    spans = sorted(result, key=lambda p: p['start'])
    pointer = start
    for span in spans:
        if date.fromisoformat(span['start']) != pointer:
            raise ValueError('annual period plan has a gap or overlap')
        pointer = date.fromisoformat(span['end']) + timedelta(days=1)
    if pointer != end + timedelta(days=1):
        raise ValueError('annual period plan does not cover the entire requested range')
    return result


def _cursor(config, index, page):
    return f"jd:{config['period_plan_sha256'][:16]}:{index}:{page}"


def _position(config, cursor):
    match = re.fullmatch(r'jd:([0-9a-f]{16}):([0-9]+):([1-9][0-9]*)', str(cursor))
    if (not match or match[1] != config['period_plan_sha256'][:16]
            or int(match[2]) >= len(config['periods'])):
        raise ValueError('cursor does not belong to this JD annual period plan')
    return int(match[2]), int(match[3])


def _decode(bu):
    raw = bu.js(LIST_PAGE_SCRIPT)
    raw = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(raw, dict):
        raise ObservationError('invalid_jd_dom_payload')
    validate_list_url(raw.get('source_url'))
    status = raw.get('route_status')
    if status in {'login_required', 'blocked'}:
        raise ObservationError(status)
    if status not in {'ready', 'loading', 'empty', 'empty_or_unrecognized'} or not isinstance(raw.get('orders'), list):
        raise ObservationError('jd_adapter_reverification_required')
    return raw


def _identity(raw):
    ids = sorted(extract_order_id(o.get('order_id_text')) for o in raw['orders'])
    return hashlib.sha256(json.dumps(ids).encode()).hexdigest()


def _fingerprint(raw):
    safe = {'selected_period': raw.get('selected_period'), 'orders': raw['orders'], 'empty_message': raw.get('empty_message')}
    return hashlib.sha256(json.dumps(safe, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _normal_empty(raw):
    return (not raw['orders'] and raw['route_status'] == 'empty'
            and isinstance(raw.get('empty_message'), str)
            and re.match(r'^没有相关订单哦[~～!！。]?', raw['empty_message']) is not None)


def _capture(bu, period, page, previous, deadline, clock, sleep, counters):
    stable = None
    for _ in range(12):
        if clock() >= deadline:
            return None
        counters['dom_reads'] += 1
        raw = _decode(bu)
        pg = raw.get('pagination') or {}
        active = str(pg.get('active') or '')
        normal_empty = _normal_empty(raw)
        if normal_empty:
            active = '1'  # Verified normal empty-year UI has no pagination.
        # Loading can temporarily remove the cards and pagination. Keep polling,
        # do not treat a transitional empty DOM as the end of a selected year.
        known_page = normal_empty or active.isdigit() and type(pg.get('next_disabled')) is bool
        dates_match = all(isinstance(o.get('order_date'), str)
                          and o['order_date'][:4] == str(period['year']) for o in raw['orders'])
        signature = _fingerprint(raw)
        valid = (known_page and raw['route_status'] != 'loading'
                 and raw.get('selected_period') == period['label'] and active == str(page)
                 and dates_match and (not raw['orders'] or previous is None or _identity(raw) != previous))
        token = (period['label'], active, signature, True if normal_empty else pg.get('next_disabled'))
        if valid and stable == token:
            return raw, signature
        stable = token if valid else None
        sleep(min(.2, max(0, deadline - clock())))
    raise ObservationError('jd_period_or_page_not_stable_or_not_advanced')


def _context(root):
    root = Path(root)
    config = load(root / 'jd-browser-collection.json')
    state = load(root / 'collection-state.json')
    meta = load(root / 'project_meta.json', {})
    if not config or not state:
        raise ValueError('configure the JD annual collection first')
    if (meta.get('platform') != 'jd' or state.get('platform') != 'jd'
            or config.get('platform') != 'jd' or config['account_key'] != state.get('account_key')
            or config['requested_range'] != state.get('requested_range')
            or config['requested_range'] != meta.get('requested_range')
            or state.get('jd_period_plan_sha256') != config['period_plan_sha256']
            or _periods(meta, config['periods']) != config['periods']):
        raise ValueError('JD account/platform/range/annual plan differs from checkpoint')
    expected = hashlib.sha256(json.dumps(config['periods'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if expected != config['period_plan_sha256']:
        raise ValueError('JD annual plan fingerprint changed')
    _position(config, state['next_cursor'])
    return root, config, state


def _summary(root, config, state, **extra):
    index, page = _position(config, state['next_cursor'])
    verified = set()
    for item in state.get('pages', []):
        period_index, _ = _position(config, item['cursor'])
        if (item.get('observation') or {}).get('next_disabled') is True:
            verified.add(config['periods'][period_index]['label'])
    return {'status': 'handoff' if state['status'] == 'blocked' else state['status'],
            'next_cursor': state['next_cursor'], 'selected_period': config['periods'][index]['label'],
            'next_page': page, 'periods_verified': len(verified), 'periods_requested': len(config['periods']),
            'saved_orders': len(load(root / 'orders.json', [])), 'reason': state.get('reason'), **extra}


def _batch(raw, signature, config, cursor, verify_empty_period, bu):
    index, page = _position(config, cursor)
    period = config['periods'][index]
    pg = raw['pagination']
    terminal = _normal_empty(raw) or pg.get('next_disabled') is True
    evidence_note = 'Stable normal JD annual order-list DOM; displayed year and all card years checked.'
    if not raw['orders']:
        # Even the known empty message can remain from the previous year while
        # the selector already shows the new year. A pair of 0.2s snapshots is
        # not proof of an empty annual response; the host must verify normally.
        result = verify_empty_period(bu, dict(period)) if callable(verify_empty_period) else None
        if (not terminal or not isinstance(result, dict) or result.get('verified') is not True
                or result.get('label') != period['label']
                or not isinstance(result.get('note'), str) or not result['note'].strip()):
            raise ObservationError('empty_jd_year_requires_normal_ui_verification')
        current = _decode(bu)
        if (current.get('selected_period') != period['label'] or current['orders']
                or current['route_status'] in {'loading', 'login_required', 'blocked'}):
            raise ObservationError('empty_jd_year_verification_changed_reobserve')
        evidence_note += ' Empty annual period independently verified in the normal UI: ' + result['note'].strip()
    next_cursor = (_cursor(config, index, page + 1) if not terminal else
                   _cursor(config, index + 1, 1) if index + 1 < len(config['periods']) else None)
    batch = normalize_list_page(raw, config['account_key'], cursor, evidence_note,
                               next_cursor=next_cursor)
    batch['end_verified'] = bool(terminal)
    dates = sorted(o['order_date'] for o in raw['orders'])
    batch['observation'] = {'active': str(page), 'content_sha256': signature,
                            'order_ids_sha256': _identity(raw), 'all_order_count': len(raw['orders']),
                            'earliest_date': dates[0] if dates else None, 'latest_date': dates[-1] if dates else None,
                            'next_disabled': terminal}
    return batch


def _prepare(bu, prepare_page, counters):
    if callable(prepare_page):
        counters['prepare_actions'] += 1
        prepare_page(bu)  # Normal scrolling only; no JS clicks or scroll injection.


def _ensure_images(raw):
    if any(row.get('image_pending') for order in raw['orders'] for row in order.get('rows', [])):
        raise ObservationError('jd_lazy_images_pending_normal_scroll_and_reobserve')


def configure_browser(bu, root, account_key, periods, select_period, *, prepare_page=None,
                      verify_empty_period=None, clock=time.time, sleep=time.sleep):
    """Bind the annual plan and save its first page; empty years require verification.

    verify_empty_period(bu, period) is optional only if no empty year is met.
    At every empty year it must perform actual normal-UI verification and return
    {'verified': True, 'label': period['label'], 'note': 'actual observation'}.
    """
    if not callable(select_period):
        raise ValueError('supply a verified normal-UI annual period selector')
    root = Path(root)
    meta = load(root / 'project_meta.json', {})
    if meta.get('platform') != 'jd':
        raise ValueError('JD project_meta is required')
    plan = _periods(meta, periods)
    digest = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    config = {'platform': 'jd', 'account_key': account_key, 'requested_range': meta['requested_range'],
              'route': 'normal_annual_list_dom', 'periods': plan, 'period_plan_sha256': digest}
    prior = load(root / 'jd-browser-collection.json')
    existing = load(root / 'collection-state.json')
    # Complete all identity checks before either config or checkpoint is written.
    bound_platform(root, existing, 'jd')
    if not isinstance(account_key, str) or not account_key.strip():
        raise ValueError('a verified local account alias is required')
    if existing and (existing.get('account_key') != account_key
                     or existing.get('requested_range') != meta['requested_range']):
        raise ValueError('checkpoint account/window does not match this JD setup')
    if prior and prior != config:
        raise ValueError('JD annual plan/account is already bound; preserve it and use a new directory')
    if existing and (existing.get('jd_period_plan_sha256') not in (None, digest)
                     or not str(existing.get('next_cursor', '')).startswith(f'jd:{digest[:16]}:')):
        raise ValueError('existing checkpoint is not this JD annual plan')
    state = initialize(root, account_key, meta['requested_range']['start'],
                       meta['requested_range']['end'], _cursor(config, 0, 1), platform='jd')
    state['jd_period_plan_sha256'] = digest
    save(root / 'collection-state.json', state)
    save(root / 'jd-browser-collection.json', config)
    if state['pages'] or state['status'] != 'ready':
        return _summary(root, config, state, resumed=True)
    counters = {'dom_reads': 0, 'period_actions': 0, 'page_actions': 0, 'prepare_actions': 0}
    try:
        counters['period_actions'] += 1
        select_period(bu, plan[0]['label'])
        _prepare(bu, prepare_page, counters)
        found = _capture(bu, plan[0], 1, None, clock() + 8, clock, sleep, counters)
        if found is None:
            return _summary(root, config, state, reason='initial_jd_snapshot_budget', **counters)
        raw, signature = found
        _ensure_images(raw)
        state = commit_page(root, _batch(raw, signature, config, state['next_cursor'], verify_empty_period, bu), clock)
        return _summary(root, config, state, first_page_saved=True, **counters)
    except Exception as exc:
        state.update(status='blocked', reason=_fail_reason(exc))
        save(root / 'collection-state.json', state)
        return _summary(root, config, state, **counters)


def collect_browser(bu, root, select_period, advance_page, *, prepare_page=None,
                    verify_empty_period=None, max_pages=5, deadline_seconds=45,
                    clock=time.time, sleep=time.sleep):
    """One bounded batch; moving between years always uses normal UI selection."""
    if type(max_pages) is not int or not 1 <= max_pages <= 10 or not 0 < deadline_seconds <= 120:
        raise ValueError('one batch: 1..10 pages, up to 120 seconds')
    if not callable(select_period) or not callable(advance_page):
        raise ValueError('supply verified normal UI period and page callbacks')
    root, config, state = _context(root)
    started, counters = clock(), {'dom_reads': 0, 'period_actions': 0, 'page_actions': 0, 'prepare_actions': 0}
    deadline = started + deadline_seconds

    def read_page(cursor):
        try:
            index, target = _position(config, cursor)
            period = config['periods'][index]
            counters['dom_reads'] += 1
            raw = _decode(bu)
            active = str((raw.get('pagination') or {}).get('active') or '')
            if _normal_empty(raw):
                active = '1'  # Same effective page as capture/resume for empty years.
            if raw.get('selected_period') != period['label']:
                if target != 1:
                    raise ObservationError('jd_resume_period_position_required')
                counters['period_actions'] += 1
                select_period(bu, period['label'])
            elif active != str(target):
                if active != str(target - 1) or (raw.get('pagination') or {}).get('next_disabled') is not False:
                    raise ObservationError('jd_resume_page_position_required')
                if raw['route_status'] == 'loading' or clock() >= deadline:
                    return {'status': 'yield'}
                counters['page_actions'] += 1
                advance_page(bu, target)
            _prepare(bu, prepare_page, counters)
            current = load(root / 'collection-state.json')
            previous = current['pages'][-1].get('observation', {}).get('order_ids_sha256') if current['pages'] else None
            found = _capture(bu, period, target, previous, min(deadline, clock() + 8), clock, sleep, counters)
            if found is None:
                return {'status': 'yield'}
            raw, signature = found
            _ensure_images(raw)
            return _batch(raw, signature, config, cursor, verify_empty_period, bu)
        except Exception as exc:
            return {'status': 'blocked', 'reason': _fail_reason(exc)}

    try:
        result = collect(root, read_page, max_pages, deadline_seconds, clock, sleep)
    except (ValueError, KeyError, TypeError) as exc:
        current = load(root / 'collection-state.json')
        current.update(status='blocked', reason='jd_page_commit_failed:' + type(exc).__name__)
        save(root / 'collection-state.json', current)
        result = {'processed_pages': 0, 'cache_hits': 0}
    current = load(root / 'collection-state.json')
    summary = _summary(root, config, current, processed_pages=result['processed_pages'], cache_hits=result['cache_hits'],
                       wait_seconds=max(0, round(current.get('next_allowed_at', 0) - clock(), 2)),
                       elapsed_seconds=round(clock() - started, 3), **counters)
    if summary['status'] == 'ready' and not summary['processed_pages']:
        summary['status'] = 'cooldown'
    metrics = load(root / 'jd-collection-metrics.json', [])
    metrics.append(summary)
    save(root / 'jd-collection-metrics.json', metrics)
    return summary


def resume_browser(bu, root, note, *, clock=time.time, sleep=time.sleep):
    """Resume only after a real, stable read at the pending year's page or previous page."""
    root, config, state = _context(root)
    if not isinstance(note, str) or not note.strip():
        raise ValueError('record the successful normal-browser re-verification')
    index, target = _position(config, state['next_cursor'])
    raw = _decode(bu)
    active = str((raw.get('pagination') or {}).get('active') or '')
    if _normal_empty(raw):
        active = '1'
    if raw.get('selected_period') != config['periods'][index]['label'] or active not in {str(target), str(target - 1)}:
        return _summary(root, config, state, reason='jd_resume_position_required')
    found = _capture(bu, config['periods'][index], int(active), None, clock() + 8, clock, sleep, {'dom_reads': 0})
    if not found:
        return _summary(root, config, state, reason='jd_reverification_budget')
    return _summary(root, config, resume(root, note))
