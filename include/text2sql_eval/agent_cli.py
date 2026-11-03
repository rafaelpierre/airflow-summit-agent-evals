"""Host-side CLI transport (never used by Airflow); no reference SQL, shell expansion, or inherited judge secrets."""
import json
import os
import signal
import subprocess
import time

from .config import digest
from .models import Response

# Deliberately exclude Airflow credentials and judge connections from the child process.
ENV_KEYS = {'PATH', 'LANG', 'LC_ALL', 'HOME', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
            'MODAL_API_TOKEN', 'FAST_MODEL_BASE_URL', 'SQL_MODEL_BASE_URL',
            'FAST_MODEL', 'SQL_MODEL', 'ANSWER_MODEL', 'REASONING_EFFORT',
            'MAX_TOKENS_SQL', 'MAX_TOKENS_ANSWER', 'DB_URL', 'NLTK_DATA',
            'AGENT_SOURCE_DIR', 'PHOENIX_API_KEY', 'PHOENIX_PROJECT_NAME', 'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT'}


def invoke(command, payload=None, timeout=60):
    python = os.environ['AGENT_CLI_PYTHON']
    script = os.environ['AGENT_CLI_SCRIPT']
    env = {k: v for k, v in os.environ.items() if k in ENV_KEYS}
    with subprocess.Popen([python, script, command], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, env=env, start_new_session=True) as process:
        try:
            output, _ = process.communicate(json.dumps(payload) if payload is not None else None, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        if process.returncode:
            raise ValueError('CLI failed')
        return json.loads(output)


def call_cli(experiment_id, example, revision):
    request_id = digest([experiment_id, example['example_id'], 1])
    start = time.monotonic()
    try:
        result = Response.model_validate(invoke('ask', {'question': example['question'], 'request_id': request_id})).model_dump()
        if result['app_revision'] != revision:
            return {'status': 'api_error', 'error': 'revision_mismatch'}
        origin = 'application' if result['latency_ms'] is not None else 'client'
        if result['latency_ms'] is None:
            result['latency_ms'] = (time.monotonic() - start) * 1000
        return dict(status='ok', **result, latency_origin=origin, request_id=request_id)
    except subprocess.TimeoutExpired:
        return {'status': 'api_error', 'error': 'cli_timeout'}
    except (ValueError, OSError, KeyError):
        return {'status': 'api_error', 'error': 'cli_failure'}
