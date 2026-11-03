"""Offline instrumentation tests use an explicit Pydantic AI test model."""
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from cli import ask, tracing


def test_auto_instrumentation_links_real_trace_id_and_disables_narration():
    exporter = InMemorySpanExporter()
    provider = tracing(exporter)
    calls = []
    def pipeline(question, narrate):
        calls.append((question, narrate))
        Agent(TestModel(custom_output_text='select 1')).run_sync(question)
        return SimpleNamespace(error='', generated_sql='select 1')
    try:
        result = ask('test question', 'request-1', provider, pipeline)
        spans = exporter.get_finished_spans()
        assert calls == [('test question', False)]
        assert len(spans) >= 3
        assert {format(s.context.trace_id, '032x') for s in spans} == {result['trace_id']}
        kinds = {s.attributes.get('openinference.span.kind') for s in spans}
        assert {'CHAIN', 'AGENT', 'LLM'} <= kinds
        assert result['sql'] == 'select 1' and result['app_revision'].startswith('sha256:')
    finally:
        Agent.instrument_all(False)
        provider.shutdown()


def test_pipeline_error_does_not_enter_root_trace():
    exporter = InMemorySpanExporter()
    provider = tracing(exporter)
    def pipeline(*a, **k):
        raise ValueError('private-provider-response')
    try:
        with pytest.raises(RuntimeError, match='application_failure'):
            ask('question', 'request-1', provider, pipeline)
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.description == 'application_failure'
        assert not spans[0].events
    finally:
        Agent.instrument_all(False)
        provider.shutdown()
