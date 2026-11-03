#!/usr/bin/env python3
"""Explicit synthetic judge-only Phoenix integration check, with no application/model calls."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from include.text2sql_eval.phoenix_adapter import PhoenixStore
from include.text2sql_eval.workflow import prepare_evaluation, judge_refs, persist
from include.text2sql_eval.reporting import build_report
from include.text2sql_eval.config import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', required=True)
    parser.parse_args()
    store = PhoenixStore()
    ds = store.client.datasets.create_dataset(name='SYNTHETIC-judge-only-' + uuid.uuid4().hex[:8],
        inputs=[{'question': 'Return one'}], outputs=[{'sql': 'select 1'}],
        metadata=[{'schema_context': 'No tables', 'sql_dialect': 'sqlite'}])
    exp = store.client.experiments.create(dataset_id=ds.id, dataset_version_id=ds.version_id,
        experiment_name='SYNTHETIC-saved-outputs', repetitions=1)
    now = datetime.now(timezone.utc)
    store.client.experiments.log_run(experiment_id=exp['id'], dataset_example_id=ds.examples[0]['id'],
        output={'sql': 'select 1'}, start_time=now, end_time=now, repetition_number=1)
    rubric = {'rubric_version': 'synthetic', 'rubric': 'Synthetic check, not a real judgment', 'temperature': 0}
    identity = 'synthetic-judge-' + uuid.uuid4().hex
    params = {'experiment_id': exp['id']}
    ref = prepare_evaluation(store, params, identity, lambda: rubric, lambda: 'synthetic-no-model')
    def forbidden():
        raise AssertionError('Configuration reread on retry')
    assert prepare_evaluation(store, params, identity, forbidden, forbidden) == ref
    row = judge_refs(store, ref)[0]
    persist(store, {'ref': row, 'error': 'evaluator_failure'})
    failed = build_report(store, exp['id'])
    assert failed['summary']['counts']['evaluator_error'] == 1
    assert not failed['summary']['complete']
    result = {'ref': row, 'actual_model': 'synthetic-no-model', 'judgment': {
        'verdict': 'correct', 'failure_category': 'none',
        'explanation': 'Explicit synthetic persistence check, not an LLM judgment.', 'suggested_check': ''}}
    persist(store, result)
    persist(store, result)
    assert build_report(store, exp['id'])['summary']['complete']
    assert judge_refs(store, ref) == []
    record = {'synthetic': True, **ref, 'dataset_id': ds.id, 'dataset_version_id': ds.version_id,
              'evaluation_config_id': digest(store.manifest(ref['manifest_id'])['config'])}
    path = Path('outputs/saved-outputs-smoke.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + '\n')
    print('Verified native saved outputs, pinned dataset, snapshot recovery, error annotation round-trip, upsert, and complete report. All judgments synthetic.')


if __name__ == '__main__':
    main()
