#!/usr/bin/env python3
"""Create an allowlisted environment file for local Airflow."""
import argparse
import os
from pathlib import Path
from dotenv import dotenv_values

ALLOWED = {'PHOENIX_BASE_URL', 'PHOENIX_API_KEY', 'PHOENIX_DATASET_ID', 'AGENT_URL',
           'AGENT_API_KEY', 'AGENT_HEALTH_URL', 'JUDGE_MODEL', 'AIRFLOW_CONN_JUDGE'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', default='.env')
    p.add_argument('--output', default='.env.runtime')
    a = p.parse_args()
    values = {**dotenv_values(a.source), **os.environ}
    lines = []
    for key in sorted(ALLOWED):
        value = values.get(key, '') or ''
        if '\n' in value or '\r' in value:
            raise ValueError('Multiline environment values are not supported')
        # Compose env files support single quotes and escaped single quotes.
        value = value.replace('\\', '\\\\').replace("'", "\\'")
        lines.append(f"{key}='{value}'")
    path = Path(a.output)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(path, 0o600)
    print('Wrote runtime credential allowlist.')


if __name__ == '__main__':
    main()
