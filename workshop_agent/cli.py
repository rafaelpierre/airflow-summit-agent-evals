"""Workshop CLI around the unchanged agentic-text2sql pipeline; no HTTP server."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time

SOURCE = Path(os.getenv('AGENT_SOURCE_DIR', Path(__file__).resolve().parents[1] / 'apps/agentic-text2sql'))
sys.path.insert(0, str(SOURCE))


def revision():
    """Fingerprint executable source and the adapter's locked runtime, including local repairs."""
    digest = hashlib.sha256()
    files = [SOURCE / 'cli.py', *sorted((SOURCE / 'text2sql_mvp').rglob('*.py'))]
    files += [Path(__file__), Path(__file__).with_name('uv.lock')]
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return 'sha256:' + digest.hexdigest()


def engine():
    from text2sql_mvp.app.db import get_engine
    return get_engine()


def check():
    from sqlalchemy import text
    with engine().connect() as conn:
        for table in ('meta.table_registry', 'ecommerce.products', 'fts_tables', 'fts_columns'):
            conn.execute(text(f'SELECT 1 FROM {table} LIMIT 1'))
    import nltk
    nltk.corpus.wordnet.ensure_loaded()
    required = ('MODAL_API_TOKEN', 'FAST_MODEL_BASE_URL', 'SQL_MODEL_BASE_URL')
    return {'status': 'ok', 'app_revision': revision(),
            'missing_credentials': [key for key in required if not os.getenv(key)]}


def initialize():
    from sqlalchemy import text
    from text2sql_mvp.app.seed_meta import seed_meta
    from text2sql_mvp.app.seed_data import seed_data
    from text2sql_mvp.app.fts import build_fts_index
    with engine().begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS workshop_state (ready INTEGER NOT NULL)'))
        if conn.execute(text('SELECT ready FROM workshop_state')).scalar() == 1:
            return check()
        # Never overwrite an existing or partially initialized application database.
        existing = conn.execute(text("SELECT name FROM ecommerce.sqlite_master WHERE type='table'" )).fetchall()
        if existing:
            raise ValueError('Existing application tables without initialization marker')
        seed_meta(conn)
        seed_data(conn)
        build_fts_index(conn)
        conn.execute(text('INSERT INTO workshop_state VALUES (1)'))
    return check()


def golden_examples():
    from text2sql_mvp.app.dbml_gen import generate_full_dbml
    with engine().connect() as conn:
        schema = generate_full_dbml(conn, include_notes=True)
    records = [json.loads(line) for line in (SOURCE / 'eval/eval_examples.jsonl').read_text().splitlines() if line.strip()]
    return [{'example_id': str(row['id']), 'question': row['question'],
             'reference_sql': row['expected_sql'], 'schema_context': schema,
             'sql_dialect': 'sqlite', 'business_rules': ''} for row in records]


def tracing(exporter=None):
    # The application owns instrumentation; this adapter only opts into it.
    from text2sql_mvp.app.telemetry import create_tracer_provider
    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings
    provider = create_tracer_provider(exporter)
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider, version=5))
    return provider


def ask(question, request_id, provider=None, pipeline=None):
    from opentelemetry.trace import Status, StatusCode
    if pipeline is None:
        from text2sql_mvp.app.text2sql import run_pipeline
        pipeline = run_pipeline
    own_provider = provider is None
    provider = provider or tracing()
    start = time.monotonic()
    try:
        with provider.get_tracer('workshop').start_as_current_span(
            'text2sql.question', record_exception=False, set_status_on_exception=False,
            attributes={'openinference.span.kind': 'CHAIN', 'input.value': question,
                        'request_id': request_id, 'app_revision': revision()},
        ) as span:
            try:
                result = pipeline(question, narrate=False)
                if result.error or not result.generated_sql.strip():
                    raise ValueError('Pipeline failed')
            except Exception:
                span.set_status(Status(StatusCode.ERROR, 'application_failure'))
                raise RuntimeError('application_failure') from None
            span.set_attribute('output.value', result.generated_sql)
            return {'sql': result.generated_sql,
                    'trace_id': format(span.get_span_context().trace_id, '032x'),
                    'latency_ms': (time.monotonic() - start) * 1000,
                    'app_revision': revision()}
    finally:
        provider.force_flush(timeout_millis=5000)
        if own_provider:
            provider.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'check', 'export-dataset', 'ask'])
    args = parser.parse_args()
    for key in ('FAST_MODEL', 'SQL_MODEL', 'ANSWER_MODEL', 'DB_URL', 'NLTK_DATA'):
        if not os.getenv(key):
            os.environ.pop(key, None)
    data_dir = Path(__file__).resolve().parents[1] / 'outputs' / 'agent'
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('DB_URL', 'sqlite:///' + str(data_dir / 'text2sql.db'))
    os.environ.setdefault('NLTK_DATA', str(data_dir.parent / 'nltk_data'))
    # Upstream prints questions, SQL and raw provider errors. Keep stdout machine-readable
    # and keep provider error bodies out of task logs. Phoenix holds execution traces.
    logging.disable(logging.CRITICAL)
    try:
        if args.command == 'init':
            output = initialize()
        elif args.command == 'check':
            output = check()
        elif args.command == 'export-dataset':
            output = golden_examples()
        else:
            from pydantic import BaseModel, ConfigDict, Field
            class Request(BaseModel):
                model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
                question: str = Field(min_length=1, max_length=20000)
                request_id: str = Field(min_length=1, max_length=128)
            request = Request.model_validate_json(sys.stdin.read(65537))
            output = ask(request.question, request.request_id)
        print(json.dumps(output))
    except Exception:
        print(json.dumps({'error': 'application_failure'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
