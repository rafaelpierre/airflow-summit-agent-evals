import json
import httpx
import pytest
from test_workflow import MemoryStore, RUBRIC, successful, judge
from include.text2sql_eval.experiment import prepare_experiment, experiment_refs, run_example
from include.text2sql_eval.agent_api import call_agent
from include.text2sql_eval.workflow import judge_refs
from include.text2sql_eval.reporting import build_report

PARAMS = {'dataset_id': 'dataset-1', 'dataset_version_id': 'version-1'}


def prepare(store, params=None, identity='api'):
    return prepare_experiment(store, params or PARAMS, identity, lambda: RUBRIC, lambda: 'gpt-test-snapshot')


def test_all_rows_resume_and_judge_by_run_id():
    s = MemoryStore()
    ref = prepare(s)
    refs = experiment_refs(s, ref)
    assert [r['example_id'] for r in refs] == ['1', '2']
    assert prepare_experiment(s, PARAMS, 'api', lambda: pytest.fail('rubric reread'),
                              lambda: pytest.fail('model reread')) == ref
    calls = []
    def caller(eid, example):
        assert set(example) == {'example_id', 'question'}
        calls.append(example['example_id'])
        return successful()
    for r in reversed(refs):
        run_example(s, r, caller)
        run_example(s, r, lambda *a: pytest.fail('Saved output rerun'))
    assert calls == ['2', '1']
    for r in judge_refs(s, ref):
        judge(s, r, 'incorrect')
    report = build_report(s, ref['experiment_id'])
    assert report['summary']['complete']
    assert report['summary']['counts']['incorrect'] == 2
    ree = prepare(s, {'experiment_id': ref['experiment_id']}, 'reevaluate')
    assert experiment_refs(s, ree) == []
    with pytest.raises(ValueError):
        run_example(s, {**ree, 'example_id': '1'}, caller)


def test_failures_survive_resume_and_report_incomplete():
    s = MemoryStore(); ref = prepare(s)
    refs = experiment_refs(s, ref)
    run_example(s, refs[0], lambda *a: {'status': 'api_error', 'error': 'http_failure'})
    run_example(s, refs[0], lambda *a: pytest.fail('Persisted failure retried'))
    report = build_report(s, ref['experiment_id'])
    assert not report['summary']['complete']
    assert report['summary']['counts']['api_error'] == 1
    assert report['summary']['counts']['missing_run'] == 1


def test_selection_validation_and_sample():
    s = MemoryStore()
    ref = prepare(s, {**PARAMS, 'max_examples': 1})
    assert len(experiment_refs(s, ref)) == 1
    with pytest.raises(ValueError): prepare(s)
    with pytest.raises(ValueError): prepare(s, {'dataset_id': 'dataset-1'})
    with pytest.raises(ValueError): prepare(s, {**PARAMS, 'experiment_id': ref['experiment_id']})


@pytest.mark.parametrize('status,body,error', [
    (200, {'generated_sql': ''}, 'malformed_response'),
    (200, [], 'malformed_response'),
    (200, {'generated_sql': 'select 1', 'error': 'private details'}, 'application_failure'),
    (502, {'error': 'private details'}, 'application_failure'),
    (401, {'detail': 'private details'}, 'http_failure'),
])
def test_api_failures_redacted(status, body, error):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)))
    out = call_agent('exp', {'example_id': '1', 'question': 'q'}, client=client, url='http://app/ask')
    assert out == {'status': 'api_error', 'error': error}


def test_api_contract_trace_and_timeout():
    def handler(request):
        assert json.loads(request.content) == {'question': 'q', 'narrate': False, 'verbose': False}
        assert request.headers['Authorization'] == 'Bearer private-token'
        assert request.headers['X-Request-ID']
        return httpx.Response(200, json={'generated_sql': 'select 1', 'rows': [], 'error': ''},
                              headers={'X-Trace-ID': 'a' * 32})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = call_agent('exp', {'example_id': '1', 'question': 'q'}, client=client,
                     url='http://app/ask', api_key='private-token')
    assert out['sql'] == 'select 1' and out['trace_id'] == 'a' * 32
    assert out['app_revision'] is None
    def timeout(request):
        raise httpx.ReadTimeout('private-token')
    client = httpx.Client(transport=httpx.MockTransport(timeout))
    assert call_agent('exp', {'example_id': '1', 'question': 'q'}, client=client,
                      url='http://app/ask')['error'] == 'http_failure'


@pytest.mark.parametrize('experiment_id', [None, ''])
def test_new_experiment_accepts_empty_trigger_field(experiment_id):
    s = MemoryStore()
    ref = prepare(s, {**PARAMS, 'experiment_id': experiment_id, 'max_examples': 1})
    assert len(experiment_refs(s, ref)) == 1
