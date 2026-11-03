#!/usr/bin/env python3
"""Bounded concurrent downloads of observed product URLs; preserves original bytes."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from image_files import image_info
from journal_io import load, save, local


def validate_url(url, hosts):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.hostname not in hosts:
        raise ValueError('image URL must use HTTPS and an explicitly observed allowed host')


def items(orders):
    seen = set()
    for order in orders:
        oid = order.get('order_id')
        if not isinstance(oid, str) or not oid:
            raise ValueError('order_id must be a nonempty string')
        for item in order.get('items', []):
            iid = item.get('item_id')
            key = (oid, iid)
            if not isinstance(iid, str) or not iid or key in seen:
                raise ValueError('order_id/item_id must identify a unique product row')
            seen.add(key)
            yield key, item


def plan(root, allowed_hosts):
    root = Path(root)
    hosts = sorted(set(allowed_hosts))
    if not hosts or any(not h or '/' in h or ':' in h for h in hosts):
        raise ValueError('provide exact image hosts observed in the sample, without scheme or wildcard')
    jobs, missing = [], []
    for (oid, iid), item in items(load(root / 'orders.json', [])):
        url = item.get('source_url')
        if item.get('origin') == 'user_provided':
            continue
        if not url:
            if item.get('image_status') != 'saved': missing.append({'order_id': oid, 'item_id': iid, 'reason': 'missing observed image URL'})
            continue
        validate_url(url, hosts)
        jobs.append({'order_id': oid, 'item_id': iid, 'url': url})
    save(root / 'media-manifest.json', {'allowed_hosts': hosts, 'jobs': jobs, 'missing_sources': missing})
    return {'jobs': len(jobs), 'unique_urls': len({j['url'] for j in jobs}), 'missing_sources': missing}


def download(root, workers=3, max_mb=512, max_file_mb=25, timeout=20, attempts=2, opener=None):
    root = Path(root)
    if type(workers) is not int or not 1 <= workers <= 6 or min(max_mb, max_file_mb, timeout) <= 0 or type(attempts) is not int or not 1 <= attempts <= 2:
        raise ValueError('workers:1..6, attempts:1..2; budgets and timeout must be positive')
    orders = load(root / 'orders.json', [])
    lookup = dict(items(orders))
    manifest = load(root / 'media-manifest.json')
    if not manifest:
        raise ValueError('run plan with the observed image hosts first')
    hosts, groups = manifest['allowed_hosts'], {}
    for job in manifest['jobs']:
        item = lookup.get((job['order_id'], job['item_id']))
        if item is None or item.get('source_url') != job['url'] or item.get('origin') == 'user_provided':
            raise ValueError('stale manifest; regenerate plan without changing product associations')
        validate_url(job['url'], hosts)
        groups.setdefault(job['url'], []).append(item)
    state = load(root / 'media-state.json', {})
    total = sum(p.stat().st_size for p in (root / 'images').rglob('*') if p.is_file())
    stop = threading.Event()
    completed = failed = fetched = reused = 0
    reason = None

    def persist():
        save(root / 'orders.json', orders)
        save(root / 'media-state.json', state)

    def attach(url, entry):
        nonlocal completed
        for item in groups[url]:
            item.update(image_path=entry['path'], image_status='saved', origin='platform',
                        image_sha256=entry['sha256'], image_dimensions={k: entry[k] for k in ('width', 'height')})
            item.pop('image_error', None)
            completed += 1

    def failure(url, message, blocking=False):
        nonlocal failed, reason
        for item in groups[url]:
            # Existing original files are retained, including when refreshing a failed URL.
            item['image_status'] = 'failed'
            item['image_error'] = message
            failed += 1
        state[hashlib.sha256(url.encode()).hexdigest()] = {'status': 'failed', 'error': message}
        if blocking:
            stop.set()
            reason = reason or message
        persist()

    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate_url(newurl, hosts)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    def fetch(url):
        client = opener if opener is not None else urllib.request.build_opener(Redirect())
        last = 'download failed'
        for _ in range(attempts):
            if stop.is_set(): return {'cancelled': True}
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with client.open(req, timeout=timeout) as response:
                    validate_url(response.geturl(), hosts)
                    raw = response.read(int(max_file_mb * 1024**2) + 1)
                if len(raw) > max_file_mb * 1024**2:
                    stop.set()
                    return {'error': 'single image budget exceeded', 'blocking': True}
                return {'data': raw, 'info': image_info(raw)}
            except urllib.error.HTTPError as exc:
                last = 'HTTP ' + str(exc.code)
                if exc.code in (401, 403, 429, 432):
                    stop.set()
                    return {'error': last, 'blocking': True}
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last = type(exc).__name__
            except ValueError as exc:
                return {'error': str(exc)}
        return {'error': last}

    pending = []
    for url, group in groups.items():
        digest = hashlib.sha256(url.encode()).hexdigest()
        entry = state.get(digest, {})
        try:
            path = local(root, entry.get('path'))
            info = image_info(path)
            if info['sha256'] != entry.get('sha256'): raise ValueError('corrupt cache')
        except (ValueError, OSError, TypeError):
            # Reuse valid, bound originals from an imported/older project as well.
            entry = None
            for item in group:
                if item.get('image_status') == 'saved' and item.get('image_path'):
                    try:
                        info = image_info(local(root, item['image_path']))
                        entry = {**info, 'path': item['image_path'], 'status': 'saved'}
                        break
                    except (ValueError, OSError): pass
        if entry:
            state[digest] = entry
            attach(url, entry)
            reused += 1
        else:
            pending.append(url)
    persist()
    queue = iter(pending)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        running = {}
        def fill():
            while len(running) < workers and not stop.is_set():
                url = next(queue, None)
                if url is None: break
                running[pool.submit(fetch, url)] = url
        fill()
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                url = running.pop(future)
                value = future.result()
                if value.get('cancelled'): continue
                if value.get('error'):
                    failure(url, value['error'], value.get('blocking', False))
                    continue
                raw, info = value['data'], value['info']
                ext = 'jpg' if info['format'] == 'jpeg' else info['format']
                relative = 'images/' + info['sha256'] + '.' + ext
                target = local(root, relative, exists=False)
                try:
                    valid = target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == info['sha256']
                    if not valid:
                        old_size = target.stat().st_size if target.is_file() else 0
                        if total + len(raw) - old_size > max_mb * 1024**2:
                            raise ValueError('total image budget exceeded; keep checkpoint and adjust budget')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        part = target.with_suffix(target.suffix + '.part')
                        part.write_bytes(raw)
                        os.replace(part, target)
                        total += len(raw) - old_size
                    entry = {**info, 'path': relative, 'status': 'saved'}
                    state[hashlib.sha256(url.encode()).hexdigest()] = entry
                    attach(url, entry)
                    fetched += 1
                    persist()
                except (ValueError, OSError) as exc:
                    failure(url, str(exc), blocking=True)
            fill()
    pending_count = sum(i.get('image_status') != 'saved' for group in groups.values() for i in group)
    report = {'ok': not failed and not pending_count and not stop.is_set() and not manifest.get('missing_sources'),
        'workers': workers, 'completed_jobs': completed, 'failed_jobs': failed, 'pending_jobs': pending_count,
        'fetched_urls': fetched, 'reused_urls': reused, 'total_bytes': total, 'stopped_reason': reason,
        'missing_sources': manifest.get('missing_sources', []), 'original_bytes_preserved': True}
    save(root / 'media-download-report.json', report)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', type=Path)
    sub = p.add_subparsers(dest='command', required=True)
    make = sub.add_parser('plan'); make.add_argument('--allow-host', action='append', required=True)
    down = sub.add_parser('download'); down.add_argument('--workers', type=int, default=3)
    down.add_argument('--max-mb', type=float, default=512); down.add_argument('--max-file-mb', type=float, default=25)
    a = p.parse_args()
    try:
        result = plan(a.project, a.allow_host) if a.command == 'plan' else download(a.project, a.workers, a.max_mb, a.max_file_mb)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get('ok', True) else 1)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        p.exit(1, str(exc) + '\n')
