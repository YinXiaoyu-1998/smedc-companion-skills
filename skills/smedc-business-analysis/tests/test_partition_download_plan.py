import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import partition_download_plan as planner


def plan(report_id='one', fragments=None):
    return {'reportId': report_id, 'report': {'storeNameContains': fragments or []}, 'jobs': [],
            'extracts': [planner.make_extract({'dataset': 'business', 'enterpriseName': '企业',
                'startDate': '20240201', 'endDate': '20240229', **({'storeNameContains': fragments} if fragments else {})})]}


class DownloadPlanTests(unittest.TestCase):
    def test_cli_merge_split_release_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plans = []
            for name in ('one', 'two'):
                path = root / f'{name}.json'
                path.write_text(json.dumps(plan(name)))
                plans.append(str(path))
            index_path = root / 'index.json'
            script = str(ROOT / 'scripts/partition_download_plan.py')
            merged = subprocess.run([sys.executable, script, 'merge', '--plans', *plans, '--output', str(index_path), '--reports-dir', str(root / 'reports')], capture_output=True, text=True)
            self.assertEqual(merged.returncode, 0, merged.stderr)
            self.assertEqual(len(list((root/'reports').glob('*.json'))), 2)
            index = json.loads(index_path.read_text())
            extract_id = index['extracts'][0]['id']
            failed = root / 'failed.json'
            failed.write_text(json.dumps({'status': 'failed', 'requestId': 'req', 'errorCode': 'PACKAGE_TOO_LARGE'}))
            recorded = subprocess.run([sys.executable, script, 'record-result', '--index', str(index_path), '--extract-id', extract_id, '--response', str(failed)], capture_output=True, text=True)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            split = subprocess.run([sys.executable, script, 'split-failed', '--plan', str(index_path), '--extract-id', extract_id, '--output', str(index_path)], capture_output=True, text=True)
            self.assertEqual(split.returncode, 0, split.stderr)
            self.assertEqual(len(json.loads(index_path.read_text())['extracts']), 2)
            release = subprocess.run([sys.executable, script, 'release-report', '--index', str(index_path), '--report-id', 'one'], capture_output=True, text=True)
            self.assertEqual(release.returncode, 0, release.stderr)

    def test_full_leap_february_is_one_business_batch(self):
        self.assertEqual(planner.split_download_windows('business', [{'start': '2024-02-01', 'end': '2024-02-29'}]), [{'start': '2024-02-01', 'end': '2024-02-29'}])

    def test_reuse_isolation_includes_enterprise_dataset_and_organization(self):
        plans = [plan('one')]
        for key, value in (('enterpriseName', '其他企业'), ('dataset', 'dishes')):
            different = plan(key)
            different['extracts'][0]['input'][key] = value
            plans.append(different)
        different = plan('organization')
        different['metadata'] = {'organization_name': '其他组织'}
        plans.append(different)
        self.assertEqual(len(planner.merge_download_plans(plans)['extracts']), 4)

    def test_month_and_week_splits_cover_union_without_overlap(self):
        for dataset in ('business', 'dishes'):
            windows = [{'start': '2024-02-25', 'end': '2024-03-05'},
                       {'start': '2024-02-28', 'end': '2024-03-10'},
                       {'start': '2023-02-26', 'end': '2023-03-04'}]
            slices = planner.split_download_windows(dataset, windows)
            observed = []
            for window in slices:
                start, end = date.fromisoformat(window['start']), date.fromisoformat(window['end'])
                self.assertTrue(start.month == end.month if dataset == 'business' else (end-start).days < 7)
                observed.extend(start + timedelta(days=i) for i in range((end-start).days + 1))
            expected = {date.fromisoformat(w['start']) + timedelta(days=i) for w in windows
                        for i in range((date.fromisoformat(w['end'])-date.fromisoformat(w['start'])).days+1)}
            self.assertEqual(set(observed), expected)
            self.assertEqual(len(observed), len(set(observed)))

    def test_same_scope_shares_and_different_filter_does_not(self):
        shared = planner.merge_download_plans([plan('one', ['一店']), plan('two', ['一店']), plan('three', ['二店'])])
        self.assertEqual(len(shared['extracts']), 2)
        self.assertEqual(shared['reports']['one']['extractRefs'], shared['reports']['two']['extractRefs'])
        self.assertNotEqual(shared['reports']['one']['extractRefs'], shared['reports']['three']['extractRefs'])
        self.assertEqual(json.loads(json.dumps(shared)), shared)

    def test_failed_parent_is_removed_from_every_report_and_one_day_fails(self):
        shared = planner.merge_download_plans([plan('one'), plan('two')])
        parent = shared['extracts'][0]
        parent['downloadState'] = {'status': 'failed', 'errorCode': 'PACKAGE_TOO_LARGE'}
        result = planner.replace_failed_extract(shared, parent['id'])
        self.assertEqual(len(result['extracts']), 2)
        for report in result['reports'].values():
            self.assertNotIn(parent['id'], report['extractRefs'])
            self.assertEqual(len(report['extracts']), 2)
        days = sum((date.fromisoformat(e['input']['endDate'][:4]+'-'+e['input']['endDate'][4:6]+'-'+e['input']['endDate'][6:]) -
                    date.fromisoformat(e['input']['startDate'][:4]+'-'+e['input']['startDate'][4:6]+'-'+e['input']['startDate'][6:])).days+1
                   for e in result['extracts'])
        self.assertEqual(days, 29)
        tiny = plan()
        tiny['extracts'][0]['input']['endDate'] = '20240201'
        tiny['extracts'][0]['downloadState'] = {'status': 'failed'}
        with self.assertRaisesRegex(ValueError, 'narrower store'):
            planner.replace_failed_extract(tiny, tiny['extracts'][0]['id'])

    def test_failed_split_reuses_existing_child_without_losing_consumers(self):
        first, second = plan('one'), plan('two')
        second['extracts'][0]['input']['endDate'] = '20240215'
        index = planner.merge_download_plans([first, second])
        parent = next(extract for extract in index['extracts'] if extract['input']['endDate'] == '20240229')
        parent['downloadState'] = {'status': 'failed'}
        result = planner.replace_failed_extract(index, parent['id'])
        self.assertEqual(len(result['extracts']), 2)
        child = next(extract for extract in result['extracts'] if extract['input']['endDate'] == '20240215')
        self.assertEqual(set(child['consumers']), {'one', 'two'})
        self.assertEqual(result['reports']['two']['extractRefs'], [child['id']])
        self.assertEqual(len(result['reports']['one']['extractRefs']), 2)

    def test_release_last_consumer_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)/'smedc-partition-extracts'/'extract-shared'
            directory.mkdir(parents=True)
            shared = planner.merge_download_plans([plan('one'), plan('two')])
            shared['extracts'][0]['downloadState'] = {'status': 'succeeded', 'localDirectory': str(directory)}
            planner.release_report_extracts(shared, 'one')
            self.assertTrue(directory.exists())
            planner.release_report_extracts(shared, 'one')
            self.assertTrue(directory.exists())
            planner.release_report_extracts(shared, 'two')
            self.assertFalse(directory.exists())

    def test_steps_are_release_gated_and_download_only_uses_request_id(self):
        extract = plan(fragments=['店'])['extracts'][0]
        self.assertEqual(extract['steps'][0]['tool'], 'prepare_structured_partition_download')
        self.assertEqual(extract['steps'][0]['input']['storeNameContains'], ['店'])
        self.assertEqual(len(extract['steps'][0]['input']['idempotencyKey']), 64)
        self.assertEqual(list(extract['steps'][2]['input']), ['requestId'])
        self.assertEqual(extract['releaseGate']['minimumPublishedLauncher'], '0.8.0')

    def test_failure_and_pending_cannot_be_reused_as_zero(self):
        shared = planner.merge_download_plans([plan()])
        extract_id = shared['extracts'][0]['id']
        for response in ({'isError': True}, {'status': 'failed', 'requestId': 'req'}, {'status': 'running', 'requestId': 'req', 'retryAfterSeconds': 2}):
            planner.record_download_result(shared, extract_id, response)
            self.assertNotEqual(shared['extracts'][0]['downloadState']['status'], 'succeeded')
