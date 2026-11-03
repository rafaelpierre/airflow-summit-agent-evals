"""Explicit offline doubles: never imported by the live workflow."""
import copy
import json
import httpx
import pytest
from include.text2sql_eval.config import normalize, digest
from include.text2sql_eval.models import Judgment, RunParams, Response
from include.text2sql_eval.workflow import prepare, execute_application, judge_refs, persist
from include.text2sql_eval.reporting import build_report, render
from include.text2sql_eval.phoenix_adapter import annotation_name
from include.text2sql_eval.agent_api import call_agent

RUBRIC = {'rubric_version': 'v1', 'rubric': 'Compare semantics, not syntax.', 'temperature': 0}
RAW = [{'id': str(i), 'input': {'question': 'same question'}, 'output': {'sql': 'select 1'},
        'metadata': {'schema_context': 'no tables', 'sql_dialect': 'sqlite', 'split': 'holdout' if i == 2 else ''}}
       for i in [2, 1]]
PARAMS = {'dataset_version_id': 'version-1', 'app_revision': 'baseline'}


class MemoryStore:
    def __init__(self):
        self.manifests, self.runs, self.evaluations = {}, {}, {}

    def dataset(self, dataset_id, version_id):
        assert version_id == 'version-1'
        return copy.deepcopy(RAW)

    def manifest(self, eid):
        return copy.deepcopy(self.manifests[eid])

    def find(self, dataset_id, key):
        return next((k for k, v in self.manifests.items() if v['run_key'] == key), None)

    def create(self, manifest):
        eid = f'exp-{len(self.manifests)}'
        self.manifests[eid] = copy.deepcopy(manifest)
        self.runs[eid], self.evaluations[eid] = [], []
        return eid

    def records(self, eid):
        return copy.deepcopy(self.runs[eid]), copy.deepcopy(self.evaluations[eid])

    def save_run(self, eid, example_id, output, start, end):
        prior = next((r for r in self.runs[eid] if r['dataset_example_id'] == example_id), None)
        row = {'id': prior['id'] if prior else f'run-{eid}-{example_id}', 'dataset_example_id': example_id,
               'repetition_number': 1, 'output': output, 'error': output.get('error')}
        if prior:
            self.runs[eid].remove(prior)
        self.runs[eid].append(row)
        return row

    def save_evaluation(self, run_id, config_id, config, result):
        eid = next(e for e, runs in self.runs.items() if any(r['id'] == run_id for r in runs))
        name = annotation_name(config_id)
        self.evaluations[eid] = [e for e in self.evaluations[eid] if (e['experiment_run_id'], e['name']) != (run_id, name)]
        self.evaluations[eid].append({'experiment_run_id': run_id, 'name': name, 'error': result.get('error'),
            'result': {'label': result['judgment']['verdict']} if 'judgment' in result else None,
            'metadata': {'judgment': result.get('judgment'), 'config': config}})

    def select_config(self, eid, config_id=None):
        configs = {digest(m['config']): m['config'] for k, m in self.manifests.items()
                   if k == eid or m.get('source_experiment_id') == eid}
        if not config_id and len(configs) != 1:
            raise ValueError('Multiple configurations')
        return copy.deepcopy(configs[config_id or next(iter(configs))])


def new(store, identity='run-1', params=None, rubric=None):
    return prepare(store, params or PARAMS, identity, lambda: rubric or RUBRIC, 'gpt-test-snapshot', 'dataset-1')


def successful(*args):
    return {'status': 'ok', 'sql': 'select 1', 'trace_id': None}


def judge(store, ref, verdict='correct'):
    env = {'ref': ref, 'actual_model': 'gpt-test-snapshot', 'judgment': {
        'verdict': verdict, 'failure_category': 'none' if verdict == 'correct' else 'other',
        'explanation': 'A semantic explanation.', 'suggested_check': 'Inspect the filter.'}}
    persist(store, env)
    return env


def test_mapping_validates_all_and_stable_order():
    assert [e['example_id'] for e in normalize(RAW)] == ['1', '2']
    custom = copy.deepcopy(RAW); custom[0]['input'] = {'prompt': 'question'}; custom[1]['input'] = {'prompt': 'question'}
    assert normalize(custom, {'question': 'input.prompt'})[0]['question'] == 'question'
    with pytest.raises(ValueError): normalize([])
    with pytest.raises(ValueError): normalize([RAW[0], RAW[0]])
    with pytest.raises(ValueError): normalize([{'id': 'bad'}])


def test_retry_recovers_snapshot_without_rereading_variable():
    s = MemoryStore(); ref = new(s)
    again = prepare(s, PARAMS, 'run-1', lambda: pytest.fail('Rubric read during retry'), 'changed', 'dataset-1')
    assert again == ref and len(s.manifests) == 1
    assert s.manifest(ref['manifest_id'])['config']['model'] == 'gpt-test-snapshot'
    assert digest({'a': 1, 'b': 2}) == digest({'b': 2, 'a': 1})


def test_resume_preserves_success_and_retries_error_only():
    s = MemoryStore(); ref = new(s); calls = []
    def first(eid, e, rev):
        calls.append(e['example_id'])
        return successful() if e['example_id'] == '1' else {'status': 'api_error', 'error': 'timeout'}
    execute_application(s, ref, first)
    execute_application(s, ref, lambda eid, e, rev: calls.append(e['example_id']) or successful())
    assert calls == ['1', '2', '2']
    assert len(s.runs[ref['experiment_id']]) == 2


def test_reevaluate_zero_agent_calls_and_new_config_preserves_previous():
    s = MemoryStore(); ref = new(s); execute_application(s, ref, successful)
    for r in judge_refs(s, ref): judge(s, r)
    changed = {**RUBRIC, 'rubric': 'Updated semantics'}
    ree = new(s, 'run-2', {'mode': 'evaluate_existing', 'experiment_id': ref['experiment_id'], 'new_evaluation_config': True}, changed)
    execute_application(s, ree, lambda *a: pytest.fail('Re-evaluation called the agent'))
    for r in judge_refs(s, ree): judge(s, r, 'incorrect')
    assert len(s.evaluations[ref['experiment_id']]) == 4
    with pytest.raises(ValueError): build_report(s, ref['experiment_id'])
    old = digest(s.manifest(ref['manifest_id'])['config'])
    assert build_report(s, ref['experiment_id'], old)['summary']['counts']['correct'] == 2


def test_run_ids_not_question_text_and_upsert():
    s = MemoryStore(); ref = new(s); execute_application(s, ref, successful)
    a, b = judge_refs(s, ref)
    judge(s, b, 'incorrect'); judge(s, a); judge(s, a)
    assert len(s.evaluations[ref['experiment_id']]) == 2
    report = build_report(s, ref['experiment_id'])
    assert [r['status'] for r in report['rows']] == ['correct', 'incorrect']
    assert judge_refs(s, ref) == []  # An incorrect answer is never retried until it passes.
    with pytest.raises(StopIteration): persist(s, {'ref': {**ref, 'run_id': 'foreign'}, 'error': 'bad'})


def test_partial_report_uncertain_denominator_and_holdout_escaping():
    s = MemoryStore(); ref = new(s); execute_application(s, ref, successful)
    a, b = judge_refs(s, ref)
    judge(s, a, 'uncertain')
    s.manifests[ref['experiment_id']]['examples'][0]['question'] = '<script>alert(1)</script>'
    report = build_report(s, ref['experiment_id'])
    assert not report['summary']['complete']
    assert report['summary']['pass_rate'] is None
    assert report['summary']['counts']['missing_evaluation'] == 1
    assert len(report['failures']['examples']) == 1
    assert '<script>alert(1)</script>' not in render(report)
    assert '&lt;script&gt;' in render(report)
    persist(s, {'ref': b, 'error': 'evaluator_failure'})
    assert build_report(s, ref['experiment_id'])['summary']['counts']['evaluator_error'] == 1


def test_baseline_incompatible_config_and_compatible_delta():
    s = MemoryStore(); baseline = new(s); execute_application(s, baseline, successful)
    for r in judge_refs(s, baseline): judge(s, r, 'incorrect')
    candidate = new(s, 'candidate', {**PARAMS, 'app_revision': 'candidate'}); execute_application(s, candidate, successful)
    for r in judge_refs(s, candidate): judge(s, r)
    report = build_report(s, candidate['experiment_id'], baseline_id=baseline['experiment_id'])
    assert all(r['change'] == 'improved' for r in report['summary']['comparison']['examples'])
    s.manifests[candidate['experiment_id']]['config']['rubric']['temperature'] = 1
    report = build_report(s, candidate['experiment_id'], baseline_id=baseline['experiment_id'])
    assert not report['summary']['comparison']['compatible']


@pytest.mark.parametrize('verdict,score', [('correct', 1), ('incorrect', 0), ('uncertain', None)])
def test_scores(verdict, score):
    assert Judgment(verdict=verdict, failure_category='none', explanation='test', suggested_check='').score == score


def test_contracts():
    with pytest.raises(ValueError): Response(sql=' ')
    with pytest.raises(ValueError): Response(sql='select 1', trace_id='fabricated')
    with pytest.raises(ValueError): RunParams(mode='evaluate_existing', experiment_id='exp', app_revision='new')
    with pytest.raises(ValueError): RunParams(**PARAMS, max_examples=0)
    with pytest.raises(ValueError): Judgment(verdict='pass', failure_category='none', explanation='bad', suggested_check='')


def test_agent_never_receives_golden_and_errors_are_redacted(monkeypatch):
    monkeypatch.setenv('AGENT_URL', 'https://agent.example/sql')
    monkeypatch.setenv('AGENT_API_KEY', 'secret-test-value')
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={'sql': 'select 1'})
    out = call_agent('exp', normalize(RAW)[0], 'baseline', httpx.Client(transport=httpx.MockTransport(handler)))
    assert out['status'] == 'ok' and out['latency_origin'] == 'client'
    assert set(payloads[0]) == {'question', 'request_id'}
    assert 'reference_sql' not in payloads[0]
    def bad(request):
        return httpx.Response(500, text='secret-test-value')
    out = call_agent('exp', normalize(RAW)[0], 'baseline', httpx.Client(transport=httpx.MockTransport(bad)))
    assert out == {'status': 'api_error', 'error': 'http_failure'}


def test_missing_and_api_errors_have_no_quality_score():
    s = MemoryStore(); ref = new(s)
    report = build_report(s, ref['experiment_id'])
    assert report['summary']['counts']['missing_run'] == 2
    assert not report['summary']['complete']
    execute_application(s, ref, lambda *a: {'status': 'api_error', 'error': 'http_failure'})
    report = build_report(s, ref['experiment_id'])
    assert report['summary']['counts']['api_error'] == 2
    assert report['summary']['pass_rate'] is None and judge_refs(s, ref) == []


def test_persistence_failure_resume_does_not_repeat_saved_success():
    s = MemoryStore(); ref = new(s); save = s.save_run
    def fail_second(eid, example_id, *args):
        if example_id == '2': raise RuntimeError('storage unavailable')
        return save(eid, example_id, *args)
    s.save_run = fail_second
    with pytest.raises(RuntimeError): execute_application(s, ref, successful)
    s.save_run = save
    calls = []
    execute_application(s, ref, lambda eid, e, rev: calls.append(e['example_id']) or successful())
    assert calls == ['2']  # The unpersisted HTTP request may repeat, as documented.
