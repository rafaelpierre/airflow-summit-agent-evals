#!/usr/bin/env python3
"""Explicit host-side application run. Airflow only judges the resulting experiment."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from include.text2sql_eval.agent_cli import ENV_KEYS, call_cli, invoke
from include.text2sql_eval.application import execute_application
from include.text2sql_eval.config import digest, normalize
from include.text2sql_eval.phoenix_adapter import PhoenixStore


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset-id', required=True)
    p.add_argument('--dataset-version-id', required=True)
    p.add_argument('--run-id', required=True, help='Reuse to resume; use a new identity for a candidate')
    p.add_argument('--max-examples', type=int, default=12)
    a = p.parse_args()
    if not 1 <= a.max_examples <= 100:
        raise ValueError('max-examples must be between 1 and 100')
    # Load only application secrets into this host process, never into Airflow.
    for key, value in dotenv_values(ROOT / '.env.agent').items():
        if key in ENV_KEYS and value:
            os.environ.setdefault(key, value)
    os.environ.setdefault('AGENT_CLI_PYTHON', str(ROOT / 'workshop_agent/.venv/bin/python'))
    os.environ.setdefault('AGENT_CLI_SCRIPT', str(ROOT / 'workshop_agent/cli.py'))
    os.environ.setdefault('PHOENIX_BASE_URL', 'http://localhost:6006')
    ready = invoke('check', timeout=20)
    if ready['missing_credentials']:
        raise ValueError('Missing application configuration: ' + ', '.join(ready['missing_credentials']))
    store = PhoenixStore()
    examples = normalize(store.dataset(a.dataset_id, a.dataset_version_id))[:a.max_examples]
    key = digest(['host-application', a.run_id])
    eid = store.find(a.dataset_id, key)
    manifest = {'dataset_id': a.dataset_id, 'dataset_version_id': a.dataset_version_id,
                'app_revision': ready['app_revision'], 'examples': examples,
                'selected_example_ids': [e['example_id'] for e in examples],
                'run_key': key, 'mode': 'new_experiment', 'repetition': 1}
    if eid:
        if store.manifest(eid) != manifest:
            raise ValueError('Run identity already exists with different inputs or application revision')
    else:
        eid = store.create(manifest)
    ref = {'manifest_id': eid, 'experiment_id': eid}
    execute_application(store, ref, caller=call_cli)
    runs, _ = store.records(eid)
    complete = sum(not r.get('error') and r['output']['status'] == 'ok' for r in runs) == len(examples)
    record = {**ref, 'app_revision': ready['app_revision'], 'complete': complete}
    target = ROOT / 'outputs/application-run.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    if not complete:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Application run failed:', type(exc).__name__, '(details suppressed)')
        raise SystemExit(1)
