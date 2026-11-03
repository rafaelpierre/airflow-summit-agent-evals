"""Explicit synthetic OpenInference-to-Phoenix check; no real model or SQL generation."""
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from cli import ask


def synthetic_pipeline(question, narrate):
    Agent(TestModel(custom_output_text='select 1')).run_sync(question)
    return SimpleNamespace(error='', generated_sql='select 1')


def main():
    result = ask('SYNTHETIC tracing verification, not an application evaluation',
                 'synthetic-tracing-check', pipeline=synthetic_pipeline)
    base = os.getenv('PHOENIX_BASE_URL', 'http://localhost:6006').rstrip('/')
    headers = {'Authorization': 'Bearer ' + os.environ['PHOENIX_API_KEY']} if os.getenv('PHOENIX_API_KEY') else {}
    spans = []
    with httpx.Client(timeout=10, headers=headers) as client:
        for _ in range(10):
            response = client.get(base + '/v1/projects/agentic-text2sql/spans', params={'trace_id': result['trace_id']})
            if response.status_code == 200:
                spans = response.json()['data']
                if len(spans) >= 3:
                    break
            time.sleep(0.5)
    if len(spans) < 3:
        raise RuntimeError('Expected automatic agent/model spans were not retrieved')
    record = {'synthetic': True, 'trace_id': result['trace_id'], 'span_count': len(spans),
              'span_kinds': sorted({s['span_kind'] for s in spans})}
    if not {'CHAIN', 'AGENT', 'LLM'} <= set(record['span_kinds']):
        raise RuntimeError('Missing OpenInference span kinds')
    path = Path(__file__).resolve().parents[1] / 'outputs/agent-tracing-smoke.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
