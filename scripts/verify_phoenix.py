#!/usr/bin/env python3
"""Explicit synthetic API smoke test. No real agent/model calls. Use a disposable instance."""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from include.text2sql_eval.phoenix_adapter import PhoenixStore
from include.text2sql_eval.workflow import prepare, execute_application, judge_refs, persist
from include.text2sql_eval.reporting import build_report, export
from include.text2sql_eval.config import digest


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seed', action='store_true')
    p.add_argument('--record', default='outputs/phoenix-smoke.json')
    a = p.parse_args()
    store = PhoenixStore()
    record_path = Path(a.record)
    if a.seed:
        dataset = store.client.datasets.create_dataset(name='SYNTHETIC-api-smoke-' + uuid.uuid4().hex[:8],
            inputs=[{'question': 'Return one'}], outputs=[{'sql': 'select 1'}],
            metadata=[{'schema_context': 'No tables', 'sql_dialect': 'sqlite'}])
        params = {'dataset_version_id': dataset.version_id, 'app_revision': 'SYNTHETIC'}
        rubric = {'rubric_version': 'test', 'rubric': 'Explicit synthetic test judgment', 'temperature': 0}
        identity = ['synthetic-smoke', uuid.uuid4().hex]
        ref = prepare(store, params, identity, lambda: rubric, 'synthetic-no-model', dataset.id)
        assert prepare(store, params, identity, lambda: (_ for _ in ()).throw(AssertionError('reread')), None, dataset.id) == ref
        execute_application(store, ref, lambda *a: {'status': 'ok', 'sql': 'select 1', 'trace_id': None})
        execute_application(store, ref, lambda *a: (_ for _ in ()).throw(AssertionError('repeated app')))
        refs = judge_refs(store, ref)
        assert len(refs) == 1
        envelope = {'ref': refs[0], 'actual_model': 'synthetic-no-model', 'judgment': {
            'verdict': 'correct', 'failure_category': 'none', 'explanation': 'Synthetic API test, not an LLM assessment.', 'suggested_check': ''}}
        persist(store, envelope); persist(store, envelope)
        ree = prepare(store, {'mode': 'evaluate_existing', 'experiment_id': ref['experiment_id'], 'new_evaluation_config': True},
            ['synthetic-reeval', uuid.uuid4().hex], lambda: {**rubric, 'rubric_version': 'test-2'}, 'synthetic-no-model')
        execute_application(store, ree, lambda *a: (_ for _ in ()).throw(AssertionError('reeval app')))
        persist(store, {**envelope, 'ref': judge_refs(store, ree)[0]})
        record = {**ref, 'dataset_id': dataset.id, 'dataset_version_id': dataset.version_id,
                  'config_id': digest(store.manifest(ref['manifest_id'])['config'])}
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=2))
    record = json.loads(record_path.read_text())
    assert len(store.dataset(record['dataset_id'], record['dataset_version_id'])) == 1
    report = build_report(store, record['experiment_id'], record['config_id'])
    assert report['summary']['complete'] and report['summary']['counts']['correct'] == 1
    assert len(store.records(record['experiment_id'])[1]) == 2
    export(report, record_path.parent / 'synthetic-smoke-report')
    print('Real Phoenix API: dataset, recovery, run IDs, evaluation upsert, re-evaluation, and export verified. Agent and judgments are explicit synthetic doubles.')


if __name__ == '__main__':
    main()
