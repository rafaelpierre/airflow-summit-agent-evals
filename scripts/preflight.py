#!/usr/bin/env python3
"""Read-only judge readiness checks, run inside Airflow. Never executes the application."""
import argparse
import importlib.metadata
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from airflow.models import Variable
from airflow.models.connection import Connection
from include.text2sql_eval.config import snapshot
from include.text2sql_eval.phoenix_adapter import PhoenixStore


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--experiment-id', required=True)
    a = p.parse_args()
    store = PhoenixStore()
    source = store.manifest(a.experiment_id)
    store.dataset(source['dataset_id'], source['dataset_version_id'])
    store.records(a.experiment_id)
    snapshot(Variable.get('text2sql_judge_config', deserialize_json=True),
             Variable.get('text2sql_judge_model'), source['examples'])
    conn = Connection.get_connection_from_secrets('judge')
    if conn.conn_type != 'pydanticai' or not conn.password:
        raise ValueError('Configure the judge pydanticai Connection in Airflow or its secrets backend')
    headers = {'Authorization': 'Bearer ' + os.environ['PHOENIX_API_KEY']} if os.getenv('PHOENIX_API_KEY') else {}
    with httpx.Client(timeout=15) as client:
        base = os.environ['PHOENIX_BASE_URL'].rstrip('/')
        client.get(base + '/healthz', headers=headers).raise_for_status()
        version = client.get(base + '/arize_phoenix_version', headers=headers)
        version.raise_for_status()
        if version.text.strip().strip('"') != '21.0.0':
            raise ValueError('Phoenix server differs from pinned version')
    print('Pinned dataset, saved outputs, Phoenix version, and Airflow judge configuration verified; client',
          importlib.metadata.version('arize-phoenix-client'))
    print('Model authentication/inference untested. No application or model calls were made.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Preflight failed:', type(exc).__name__, '(details suppressed)')
        raise SystemExit(1)
