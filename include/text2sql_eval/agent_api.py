"""Adapter for agentic-text2sql POST /ask. Never log bodies, URLs, or credentials."""
import os
import time
import httpx
from .models import Response
from .config import digest


def call_agent(experiment_id, example, revision=None, client=None, *, url=None, api_key=None):
    request_id = digest([experiment_id, example['example_id'], 1])
    url = url or os.environ['AGENT_URL']
    api_key = api_key if api_key is not None else os.getenv('AGENT_API_KEY')
    headers = {'Authorization': 'Bearer ' + api_key} if api_key else {}
    # The current API does not implement idempotency; this header is correlation only.
    headers['X-Request-ID'] = request_id
    start = time.monotonic()
    try:
        with (httpx.Client(timeout=60, follow_redirects=False) if client is None else client) as http:
            response = http.post(url, headers=headers,
                                 json={'question': example['question'], 'narrate': False, 'verbose': False})
            if response.status_code == 502:
                return {'status': 'api_error', 'error': 'application_failure'}
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('error', ''), str):
                raise ValueError('Invalid response')
            if data.get('error'):
                return {'status': 'api_error', 'error': 'application_failure'}
            result = Response.model_validate({'sql': data.get('generated_sql'),
                'trace_id': response.headers.get('X-Trace-ID'),
                'latency_ms': (time.monotonic() - start) * 1000}).model_dump()
        return dict(status='ok', **result, latency_origin='client', request_id=request_id)
    except ValueError:
        return {'status': 'api_error', 'error': 'malformed_response'}
    except httpx.HTTPError:
        return {'status': 'api_error', 'error': 'http_failure'}


def call_configured_agent(experiment_id, example):
    from airflow.sdk import Connection
    connection = Connection.get('text2sql_api')
    # Host contains the full /ask URL. Password optionally holds a proxy bearer token.
    return call_agent(experiment_id, example, url=connection.host, api_key=connection.password or '')
