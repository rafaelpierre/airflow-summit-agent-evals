from types import SimpleNamespace
import pytest
from airflow.providers.common.ai.operators.llm import LLMOperator
from airflow.providers.common.ai.utils.logging import MODEL_NAME_XCOM_KEY
from include.text2sql_eval import judge


@pytest.mark.parametrize('actual,expected', [('frozen-model', None), ('different-model', 'model_identity_mismatch')])
def test_judge_frozen_model_and_explicit_envelope(monkeypatch, actual, expected):
    ref = {'experiment_id': 'exp', 'manifest_id': 'manifest', 'run_id': 'run-explicit'}
    config = {'model': 'frozen-model', 'rubric': {'rubric': 'Frozen rubric', 'temperature': 0}}
    monkeypatch.setattr(judge, 'PhoenixStore', lambda: None)
    monkeypatch.setattr(judge, 'judge_input', lambda *a: (config, {'candidate_sql': '{{ secrets }}'}))
    def execute(self, context):
        assert self.model_id == 'openai:frozen-model'
        assert self.fallback_conn_ids == []
        assert self.model_settings['temperature'] == 0
        assert '{{ secrets }}' in self.prompt  # Data is hydrated after template rendering.
        return {'verdict': 'incorrect', 'failure_category': 'other', 'explanation': 'Wrong SQL', 'suggested_check': 'Review filter'}
    monkeypatch.setattr(LLMOperator, 'execute', execute)
    def pull(**kwargs):
        assert kwargs['key'] == MODEL_NAME_XCOM_KEY
        return actual
    operator = judge.SQLJudgeOperator(task_id='judge', ref=ref)
    result = operator.execute({'ti': SimpleNamespace(xcom_pull=pull, map_index=0)})
    assert result['ref'] == ref and result.get('error') == expected


def test_judge_failure_is_safe_envelope(monkeypatch):
    monkeypatch.setattr(judge, 'PhoenixStore', lambda: None)
    monkeypatch.setattr(judge, 'judge_input', lambda *a: ({'model': 'model', 'rubric': {'rubric': 'test', 'temperature': 0}}, {}))
    monkeypatch.setattr(LLMOperator, 'execute', lambda *a: (_ for _ in ()).throw(RuntimeError('credential secret')))
    result = judge.SQLJudgeOperator(task_id='judge', ref={'run_id': 'run'}).execute({})
    assert result == {'ref': {'run_id': 'run'}, 'error': 'evaluator_failure'}
