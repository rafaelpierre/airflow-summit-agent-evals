"""Create persistent local Airflow secrets without displaying or rotating them."""
import base64
import os
from pathlib import Path
import secrets


def initialize(path=Path('.env.airflow')):
    if path.exists():
        print('Keeping existing local Airflow credentials.')
        return
    password = secrets.token_hex(24)
    values = {
        'POSTGRES_PASSWORD': password,
        'AIRFLOW__DATABASE__SQL_ALCHEMY_CONN': f'postgresql+psycopg2://airflow:{password}@postgres/airflow',
        'AIRFLOW__CORE__FERNET_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        'AIRFLOW__API_AUTH__JWT_SECRET': secrets.token_hex(32),
        'AIRFLOW__API__SECRET_KEY': secrets.token_hex(32),
        'AIRFLOW_ADMIN_PASSWORD': secrets.token_urlsafe(24),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    print('Created local Airflow credentials in .env.airflow (not displayed).')


if __name__ == '__main__':
    initialize()
