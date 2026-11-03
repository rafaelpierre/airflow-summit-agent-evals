import os
import time
import httpx
from pydantic import ValidationError
from .models import Response
from .config import digest


def call_agent(experiment_id, example, revision, client=None):
    request_id = digest([experiment_id, example['example_id'], 1])
    headers = {'Authorization': 'Bearer ' + os.environ['AGENT_API_KEY']} if os.getenv('AGENT_API_KEY') else {}
    start = time.monotonic()
    try:
        with (httpx.Client(timeout=60, follow_redirects=False) if client is None else client) as http:
            response = http.post(os.environ['AGENT_URL'], headers=headers,
                                 json={'question': example['question'], 'request_id': request_id})
            response.raise_for_status()
            result = Response.model_validate(response.json()).model_dump()
        if result['app_revision'] is not None and result['app_revision'] != revision:
            return {'status': 'api_error', 'error': 'revision_mismatch'}
        origin = 'application' if result['latency_ms'] is not None else 'client'
        result['latency_ms'] = result['latency_ms'] if result['latency_ms'] is not None else (time.monotonic() - start) * 1000
        return dict(status='ok', **result, latency_origin=origin, request_id=request_id)
    except (ValidationError, ValueError):
        return {'status': 'api_error', 'error': 'malformed_response'}
    except httpx.HTTPError:
        # Never persist exception messages: URLs/response bodies can contain credentials.
        return {'status': 'api_error', 'error': 'http_failure'}
