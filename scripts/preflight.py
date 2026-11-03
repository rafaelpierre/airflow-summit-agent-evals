#!/usr/bin/env python3
"""Read-only readiness checks. Does not call the agent's inference endpoint or a model."""
import argparse
import importlib.metadata
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from include.text2sql_eval.config import normalize
from include.text2sql_eval.phoenix_adapter import PhoenixStore


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset-version-id', required=True)
    p.add_argument('--cloud', action='store_true')
    a = p.parse_args()
    required = ['PHOENIX_BASE_URL', 'PHOENIX_DATASET_ID', 'AGENT_URL', 'JUDGE_MODEL', 'AIRFLOW_CONN_JUDGE']
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise ValueError('Missing configuration names: ' + ', '.join(missing))
    url = urlparse(os.environ['PHOENIX_BASE_URL'])
    if a.cloud and (url.hostname in {'localhost', '127.0.0.1', 'phoenix', 'host.docker.internal'} or url.scheme != 'https' or not os.getenv('PHOENIX_API_KEY')):
        raise ValueError('Cloud requires a reachable authenticated HTTPS Phoenix endpoint')
    headers = {'Authorization': 'Bearer ' + os.environ['PHOENIX_API_KEY']} if os.getenv('PHOENIX_API_KEY') else {}
    with httpx.Client(timeout=15) as client:
        health = client.get(os.environ['PHOENIX_BASE_URL'].rstrip('/') + '/healthz', headers=headers)
        health.raise_for_status()
        version = client.get(os.environ['PHOENIX_BASE_URL'].rstrip('/') + '/arize_phoenix_version', headers=headers)
        version.raise_for_status()
        if version.text.strip().strip('"') != '21.0.0':
            raise ValueError('Phoenix server version differs from pinned 21.0.0')
        if os.getenv('AGENT_HEALTH_URL'):
            agent_headers = {'Authorization': 'Bearer ' + os.environ['AGENT_API_KEY']} if os.getenv('AGENT_API_KEY') else {}
            client.get(os.environ['AGENT_HEALTH_URL'], headers=agent_headers).raise_for_status()
        else:
            print('Agent connectivity: pending; set AGENT_HEALTH_URL to a read-only health endpoint')
    normalize(PhoenixStore().dataset(os.environ['PHOENIX_DATASET_ID'], a.dataset_version_id))
    import json
    conn = json.loads(os.environ['AIRFLOW_CONN_JUDGE'])
    if conn.get('conn_type') != 'pydanticai' or not conn.get('password'):
        raise ValueError('AIRFLOW_CONN_JUDGE must be a pydanticai OpenAI connection with a password')
    print('Phoenix readiness/version/dataset access verified from this process; client', importlib.metadata.version('arize-phoenix-client'))
    print('Judge connection shape verified; model authentication and inference remain untested')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Preflight failed:', type(exc).__name__, '(inspect configuration; credentials and responses suppressed)')
        raise SystemExit(1)
