"""Read-only checks for local login, service heartbeats, and DAG registration."""
import httpx
from dotenv import dotenv_values


def main():
    password = dotenv_values('.env.airflow')['AIRFLOW_ADMIN_PASSWORD']
    with httpx.Client(base_url='http://localhost:8080', timeout=15) as client:
        response = client.post('/auth/token', json={'username': 'admin', 'password': password})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
        response = client.get('/api/v2/monitor/health')
        response.raise_for_status()
        for component in ('metadatabase', 'scheduler', 'dag_processor'):
            if response.json()[component]['status'] != 'healthy':
                raise ValueError('Unhealthy local Airflow component')
        response = client.get('/api/v2/dags/text2sql_evaluation')
        response.raise_for_status()
        if not response.json()['is_paused']:
            raise ValueError('Expected evaluation DAG to remain paused during setup')
        response = client.get('/api/v2/importErrors')
        response.raise_for_status()
        if response.json()['total_entries']:
            raise ValueError('Airflow has DAG import errors')
    print('Local Airflow login, database/scheduler/parser health, and paused evaluation DAG verified. No tasks triggered.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Local verification failed: {type(exc).__name__} (credentials and responses suppressed)') from None
