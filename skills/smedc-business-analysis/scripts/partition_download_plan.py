#!/usr/bin/env python3
"""Plan bounded MCP downloads and track shared report consumers; never call HTTP."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import shutil
import sys
import os
import uuid
from contextlib import contextmanager
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

RELEASE_GATE = {
    'minimumPublishedLauncher': '0.8.0',
    'requiresMatchingServerEndpoints': True,
    'enabledByDefault': False,
}


def normalize_store_names(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or not 1 <= len(values) <= 20:
        raise ValueError('storeNameContains must contain 1–20 values')
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError('storeNameContains values must be text')
        value = unicodedata.normalize('NFC', value.strip())
        if not value:
            raise ValueError('store-name-contains values must be non-blank')
        if len(value) > 255:
            raise ValueError('storeNameContains values must be at most 255 characters')
        if value not in result:
            result.append(value)
    return result


def split_download_windows(dataset: str, windows: list[Any]) -> list[dict[str, str]]:
    if dataset not in {'business', 'dishes'}:
        raise ValueError(f'unsupported partition dataset: {dataset}')
    ranges = []
    for window in windows:
        start, end = (window['start'], window['end']) if isinstance(window, dict) else (window.start, window.end)
        start = date.fromisoformat(start) if isinstance(start, str) else start
        end = date.fromisoformat(end) if isinstance(end, str) else end
        if start > end:
            raise ValueError('download window start is after end')
        ranges.append((start, end))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    slices = []
    for start, end in merged:
        while start <= end:
            if dataset == 'business':
                next_month = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
                stop = min(end, next_month - timedelta(days=1))
            else:
                stop = min(end, start + timedelta(days=6))
            slices.append({'start': start.isoformat(), 'end': stop.isoformat()})
            start = stop + timedelta(days=1)
    return slices


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def make_extract(selector: dict[str, Any], scope: str = '') -> dict[str, Any]:
    selector = copy.deepcopy(selector)
    names = selector.get('storeNameContains')
    if names is not None:
        selector['storeNameContains'] = sorted(normalize_store_names(names))
    if 'storeIds' in selector:
        selector['storeIds'] = sorted(set(selector['storeIds']))
    key = digest({'scope': scope, 'selector': selector})
    extract_id = f"{selector['dataset']}_{key[:24]}"
    generation = uuid.uuid4().hex
    request_key = digest({'extract': key, 'generation': generation})
    request = '${prepare.requestId}'
    return {
        'id': extract_id, 'preparationGeneration': generation, 'reuseScope': scope, 'tool': 'download_structured_partitions', 'input': selector,
        'outputFile': f'partition-extracts/{extract_id}.json',
        'releaseGate': copy.deepcopy(RELEASE_GATE),
        'steps': [
            {'tool': 'prepare_structured_partition_download', 'input': {**selector, 'idempotencyKey': request_key}},
            {'tool': 'get_structured_partition_download_status', 'input': {'requestId': request},
             'wait': 'Follow retryAfterSeconds while queued/running; reject isError/failed/expired.'},
            {'tool': 'download_structured_partitions', 'input': {'requestId': request},
             'when': 'Only after status succeeded; save the full local download envelope at outputFile.'},
        ],
        'downloadState': {'status': 'planned'},
    }


def sync_reports(index: dict[str, Any]) -> None:
    extracts = {item['id']: item for item in index['extracts']}
    for report in index.get('reports', {}).values():
        report['extracts'] = [copy.deepcopy(extracts[key]) for key in report['extractRefs']]


def merge_download_plans(plans: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {'schemaVersion': 1, 'extracts': [], 'reports': {}}
    groups = {}
    for ordinal, original in enumerate(plans, start=1):
        report = copy.deepcopy(original)
        report_id = report.get('reportId') or f'report-{digest(report)[:16]}-{ordinal}'
        if not isinstance(report_id, str) or not report_id or report_id in index['reports']:
            raise ValueError('reportId must be unique non-empty text')
        report['reportId'] = report_id
        report['extractRefs'] = []
        result_prefix = f'report-results/{digest(report_id)[:16]}/'
        for job in report.get('jobs', []):
            if not job['outputFile'].startswith(result_prefix):
                job['outputFile'] = result_prefix + job['outputFile']
        scope = report.get('metadata', {}).get('organization_name', '')
        report_names = normalize_store_names(report.get('report', {}).get('storeNameContains') or None)
        for old in report.get('extracts', []):
            selector = copy.deepcopy(old['input'])
            if 'storeNameContains' in selector and set(normalize_store_names(selector['storeNameContains'])) != set(report_names):
                raise ValueError('extract storeNameContains differs from report scope')
            if report_names:
                selector['storeNameContains'] = sorted(report_names)
            if 'storeIds' in selector:
                selector['storeIds'] = sorted(set(selector['storeIds']))
            base = {k: v for k, v in selector.items() if k not in {'startDate', 'endDate'}}
            group = groups.setdefault(digest([scope, base]), {'scope': scope, 'base': base, 'days': {}, 'existing': {}})
            start, end = (date.fromisoformat(selector[k]) for k in ('startDate', 'endDate'))
            while start <= end:
                group['days'].setdefault(start, set()).add(report_id)
                start += timedelta(days=1)
            candidate = make_extract(selector, scope)
            if old.get('id') == candidate['id']:
                candidate = copy.deepcopy(old)
            elif old.get('downloadState', {}).get('status') == 'succeeded':
                candidate['downloadState'] = copy.deepcopy(old['downloadState'])
            prior = group['existing'].get(candidate['id'])
            if prior is None or candidate.get('downloadState', {}).get('status') == 'succeeded':
                group['existing'][candidate['id']] = candidate
        index['reports'][report_id] = report

    def add(extract, consumers):
        extract['consumers'] = sorted(consumers)
        extract['releasedBy'] = []
        index['extracts'].append(extract)
        for consumer in consumers:
            index['reports'][consumer]['extractRefs'].append(extract['id'])

    for group in groups.values():
        days = group['days']
        # Keep verified local successes intact; new requests cover only the remaining days.
        for existing in group['existing'].values():
            state = existing.get('downloadState', {})
            if state.get('status') != 'succeeded' or state.get('response') is None:
                continue
            verify_local_download(existing, state['response'])
            first, last = (date.fromisoformat(existing['input'][k]) for k in ('startDate', 'endDate'))
            covered = [day for day in days if first <= day <= last]
            if covered:
                add(existing, set().union(*(days[day] for day in covered)))
                for day in covered:
                    del days[day]
        while days:
            first = last = min(days)
            consumers = days[first]
            while days.get(last + timedelta(days=1)) == consumers:
                last += timedelta(days=1)
            for window in split_download_windows(group['base']['dataset'], [{'start': first, 'end': last}]):
                selector = {**group['base'], 'startDate': date.fromisoformat(window['start']).strftime('%Y%m%d'),
                            'endDate': date.fromisoformat(window['end']).strftime('%Y%m%d')}
                candidate = make_extract(selector, group['scope'])
                add(group['existing'].get(candidate['id'], candidate), consumers)
            for day in list(days):
                if first <= day <= last:
                    del days[day]
    index['extracts'].sort(key=lambda item: item['id'])
    sync_reports(index)
    return index


def renew_failed_extract(plan: dict[str, Any], extract_id: str) -> dict[str, Any]:
    result = copy.deepcopy(plan)
    parent = next(item for item in result['extracts'] if item['id'] == extract_id)
    state = parent.get('downloadState', {})
    if state.get('status') != 'expired' and state.get('errorCode') != 'PARTITION_DOWNLOAD_STALE':
        raise ValueError('only stale or expired requests may be renewed')
    fresh = make_extract(parent['input'], parent.get('reuseScope', ''))
    for key in ('preparationGeneration', 'steps', 'downloadState'):
        parent[key] = fresh[key]
    sync_reports(result)
    return result


def replace_failed_extract(plan: dict[str, Any], extract_id: str) -> dict[str, Any]:
    result = copy.deepcopy(plan)
    matches = [item for item in result['extracts'] if item['id'] == extract_id]
    if len(matches) != 1:
        raise ValueError('failed extract must exist exactly once')
    parent = matches[0]
    if parent.get('downloadState', {}).get('status') not in {'failed', 'expired'}:
        raise ValueError('only a failed or expired extract may be split')
    if parent['downloadState'].get('status') == 'expired' or parent['downloadState'].get('errorCode') == 'PARTITION_DOWNLOAD_STALE':
        return renew_failed_extract(result, extract_id)
    selector = parent['input']
    start, end = (date.fromisoformat(selector[name]) for name in ('startDate', 'endDate'))
    if start >= end:
        raise ValueError('one-day download failed; request a narrower store name scope')
    middle = start + timedelta(days=(end - start).days // 2)
    children = []
    for first, last in ((start, middle), (middle + timedelta(days=1), end)):
        child = make_extract({**selector, 'startDate': first.strftime('%Y%m%d'), 'endDate': last.strftime('%Y%m%d')}, parent.get('reuseScope', ''))
        child['replaces'] = extract_id
        for name in ('consumers', 'releasedBy'):
            if name in parent:
                child[name] = copy.deepcopy(parent[name])
        children.append(child)
    by_id = {item['id']: item for item in result['extracts'] if item['id'] != extract_id}
    for child in children:
        if child['id'] in by_id:
            existing = by_id[child['id']]
            for name in ('consumers', 'releasedBy'):
                if name in child:
                    existing[name] = sorted(set(existing.get(name, []) + child[name]))
        else:
            by_id[child['id']] = child
    result['extracts'] = [by_id[key] for key in sorted(by_id)]
    for report in result.get('reports', {}).values():
        replaced_refs = [child['id'] for key in report['extractRefs']
                         for child in (children if key == extract_id else [{'id': key}])]
        report['extractRefs'] = list(dict.fromkeys(replaced_refs))
    sync_reports(result)
    return result


def verify_local_download(extract: dict[str, Any], response: dict[str, Any]) -> None:
    from load_partition_extract import metadata_count, validate_download, validate_file_integrity
    directory, files = validate_download(extract, response)
    for file_spec in files:
        path = validate_file_integrity(directory, file_spec)
        with path.open(encoding='utf-8-sig', newline='') as handle:
            count = sum(1 for _ in csv.DictReader(handle))
        if count != metadata_count(file_spec.get('rowCount'), 'rowCount'):
            raise ValueError('reused partition row count mismatch')


def record_download_result(index: dict[str, Any], extract_id: str, response: dict[str, Any]) -> None:
    from assemble_query_bundle import is_error_envelope, unwrap_success_envelope
    extract = next(item for item in index['extracts'] if item['id'] == extract_id)
    try:
        payload = unwrap_success_envelope(response)
        if is_error_envelope(response) or is_error_envelope(payload):
            code = payload.get('error', {}).get('code') if isinstance(payload, dict) and isinstance(payload.get('error'), dict) else None
            payload = {'status': 'expired' if code == 'PARTITION_DOWNLOAD_EXPIRED' else 'failed',
                       'errorCode': code if isinstance(code, str) else 'MCP_ERROR'}
        if not isinstance(payload, dict):
            raise ValueError('download result must be an object')
    except ValueError:
        payload = {'status': 'failed', 'errorCode': 'MCP_ERROR'}
    status = payload.get('status')
    if status is None and 'localDirectory' in payload:
        verify_local_download(extract, payload)
        state = {'status': 'succeeded', 'localDirectory': payload['localDirectory'], 'response': payload}
    elif status in {'queued', 'running', 'succeeded', 'failed', 'expired'}:
        # Packaging succeeded does not mean a verified local directory exists yet.
        state = {key: payload[key] for key in ('requestId', 'retryAfterSeconds', 'errorCode', 'expiresAt') if key in payload}
        state['status'] = 'ready' if status == 'succeeded' else status
    else:
        raise ValueError('download result has no valid status or local envelope')
    extract['downloadState'] = state
    sync_reports(index)


def release_report_extracts(index: dict[str, Any], report_id: str) -> list[str]:
    from load_partition_extract import validate_extract_directory
    if not isinstance(index, dict):
        raise ValueError('shared download ledger must be an object')
    reports = index.get('reports')
    if index.get('schemaVersion') != 1 or not isinstance(reports, dict) or report_id not in reports:
        raise ValueError('shared download ledger has no matching report')
    if not all(isinstance(report, dict) and isinstance(report.get('extractRefs'), list) for report in reports.values()):
        raise ValueError('shared download ledger has malformed reports')
    refs = reports[report_id].get('extractRefs')
    extracts = index.get('extracts')
    if not isinstance(extracts, list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in extracts):
        raise ValueError('shared download ledger has malformed extracts')
    by_id = {item['id']: item for item in extracts}
    if len(by_id) != len(extracts):
        raise ValueError('shared download ledger repeats extracts')
    if any(not isinstance(key, str) or key not in by_id for report in reports.values() for key in report['extractRefs']):
        raise ValueError('shared download ledger has invalid extract references')
    if any(not isinstance(item.get('downloadState', {}), dict) for item in extracts):
        raise ValueError('shared download ledger has malformed download state')
    directories = [item.get('downloadState', {}).get('localDirectory') for item in extracts]
    directories = [str(Path(raw).resolve()) for raw in directories if isinstance(raw, str) and raw]
    if len(directories) != len(set(directories)):
        raise ValueError('shared download ledger repeats local directories')
    if not isinstance(refs, list) or any(key not in by_id for key in refs):
        raise ValueError('shared download ledger has invalid extract references')
    # Validate the entire release before any deletion; malformed ledgers fail closed.
    for key in refs:
        item = by_id[key]
        consumers, released = item.get('consumers'), item.get('releasedBy')
        if (not isinstance(consumers, list) or not consumers or report_id not in consumers
                or set(consumers) != {name for name, report in reports.items() if key in report['extractRefs']}
                or not isinstance(released, list) or any(consumer not in consumers for consumer in released)):
            raise ValueError('shared download ledger has invalid consumers')
        raw_directory = item.get('downloadState', {}).get('localDirectory')
        if raw_directory and not item.get('cleaned') and set(consumers) <= set([*released, report_id]):
            validate_extract_directory(raw_directory)
    deleted = []
    for key in refs:
        item = by_id[key]
        if report_id not in item['releasedBy']:
            item['releasedBy'].append(report_id)
        if set(item['consumers']) <= set(item['releasedBy']):
            raw_directory = item.get('downloadState', {}).get('localDirectory')
            if raw_directory and not item.get('cleaned'):
                directory = validate_extract_directory(raw_directory)
                shutil.rmtree(directory)
                deleted.append(str(directory))
            item['cleaned'] = True
    reports[report_id]['released'] = True
    sync_reports(index)
    return deleted


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    temporary.replace(path)


@contextmanager
def shared_lock(path: Path):
    # Lock one persistent byte on Windows; closing the handle also releases the lock.
    with path.with_suffix(path.suffix + '.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def release_saved_report(path: Path, report_id: str) -> list[str]:
    # Serialize concurrent runner finalizers so no consumer release is lost.
    with shared_lock(path):
        index = json.loads(path.read_text(encoding='utf-8'))
        deleted = release_report_extracts(index, report_id)
        save_json(path, index)
        return deleted


def resolve_shared_report(manifest: dict[str, Any]) -> dict[str, Any]:
    if 'sharedDownload' not in manifest:
        return manifest
    shared = manifest['sharedDownload']
    if not isinstance(shared, dict) or not isinstance(shared.get('indexPath'), str) or not isinstance(shared.get('reportId'), str):
        raise ValueError('invalid shared download reference')
    index = json.loads(Path(shared['indexPath']).read_text(encoding='utf-8'))
    report = index['reports'][shared['reportId']]
    if report.get('released'):
        raise ValueError('shared report has already released its extracts')
    by_id = {item['id']: item for item in index['extracts']}
    return {**manifest, 'jobs': copy.deepcopy(report.get('jobs', manifest.get('jobs', []))),
            'extracts': [copy.deepcopy(by_id[key]) for key in report['extractRefs']]}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    merge = commands.add_parser('merge')
    merge.add_argument('--plans', nargs='+', required=True, type=Path)
    merge.add_argument('--reports-dir', type=Path)
    merge.add_argument('--output', required=True, type=Path)
    split = commands.add_parser('split-failed')
    split.add_argument('--plan', required=True, type=Path)
    split.add_argument('--extract-id', required=True)
    split.add_argument('--output', required=True, type=Path)
    release = commands.add_parser('release-report')
    release.add_argument('--index', required=True, type=Path)
    release.add_argument('--report-id', required=True)
    record = commands.add_parser('record-result')
    record.add_argument('--index', required=True, type=Path)
    record.add_argument('--extract-id', required=True)
    record.add_argument('--response', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'merge':
            result = merge_download_plans([json.loads(path.read_text(encoding='utf-8')) for path in args.plans])
            for report_id, report in result['reports'].items():
                report['sharedDownload'] = {'indexPath': str(args.output.resolve()), 'reportId': report_id}
            save_json(args.output, result)
            if args.reports_dir:
                for report_id, report in result['reports'].items():
                    save_json(args.reports_dir / f'report-{digest(report_id)[:16]}.json', report)
        elif args.command == 'split-failed':
            result = replace_failed_extract(json.loads(args.plan.read_text(encoding='utf-8')), args.extract_id)
            for report in result.get('reports', {}).values():
                if 'sharedDownload' in report:
                    report['sharedDownload']['indexPath'] = str(args.output.resolve())
            save_json(args.output, result)
        elif args.command == 'release-report':
            release_saved_report(args.index, args.report_id)
        else:
            with shared_lock(args.index):
                result = json.loads(args.index.read_text(encoding='utf-8'))
                record_download_result(result, args.extract_id, json.loads(args.response.read_text(encoding='utf-8')))
                save_json(args.index, result)
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
