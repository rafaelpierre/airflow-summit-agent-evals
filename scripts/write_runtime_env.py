#!/usr/bin/env python3
"""Create an allowlisted environment file for local Airflow."""
import argparse
import os
from pathlib import Path
from dotenv import dotenv_values

ALLOWED = {'PHOENIX_BASE_URL', 'PHOENIX_API_KEY', 'AIRFLOW_CONN_JUDGE',
           'AIRFLOW_VAR_TEXT2SQL_JUDGE_MODEL', 'AIRFLOW_CONN_TEXT2SQL_API'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', default='.env')
    p.add_argument('--output', default='.env.runtime')
    a = p.parse_args()
    values = {**dotenv_values(a.source), **os.environ}
    lines = []
    for key in sorted(ALLOWED):
        value = values.get(key, '') or ''
        if not value and key.startswith(('AIRFLOW_CONN_', 'AIRFLOW_VAR_')):
            # Empty environment secrets would mask Variables/Connections in the UI.
            continue
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
