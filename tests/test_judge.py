from types import SimpleNamespace
import pytest
from airflow.providers.common.ai.operators.llm import LLMOperator
from airflow.providers.common.ai.utils.logging import MODEL_NAME_XCOM_KEY
from include.text2sql_eval import judge


@pytest.mark.parametrize('actual,expected', [('frozen-model', None), ('different-model', 'model_identity_mismatch')])
def test_judge_frozen_model_and_explicit_envelope(monkeypatch, actual, expected):
    ref = {'experiment_id': 'exp', 'manifest_id': 'manifest', 'run_id': 'run-explicit'}
    config = {'model': 'frozen-model', 'model_api': 'openai-chat', 'rubric': {'rubric': 'Frozen rubric', 'temperature': 0}}
    monkeypatch.setattr(judge, 'PhoenixStore', lambda: None)
    monkeypatch.setattr(judge, 'judge_input', lambda *a: (config, {'candidate_sql': '{{ secrets }}'}))
    def execute(self, context):
        assert self.model_id == 'openai-chat:frozen-model'
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


def test_modal_judge_connection_routes_structured_request(monkeypatch):
    """Exercise the installed Common AI/Pydantic AI stack with an explicit HTTP double."""
    import json
    import httpx
    from openai import AsyncOpenAI
    from pydantic_ai import Agent
    from pydantic_ai.providers.openai import OpenAIProvider
    from airflow.providers.common.ai.hooks import pydantic_ai as hooks
    from include.text2sql_eval.models import Judgment

    seen = []
    def handler(request):
        seen.append(request)
        assert str(request.url) == 'https://judge.example.modal.run/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer wk-test.ws-test'
        body = json.loads(request.content)
        assert body['model'] == 'served-model'
        tool = body['tools'][0]['function']['name']
        return httpx.Response(200, json={
            'id': 'mock-completion', 'object': 'chat.completion', 'created': 1, 'model': 'served-model',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'mock-call', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps({
                        'verdict': 'incorrect', 'failure_category': 'other',
                        'explanation': 'Different semantics', 'suggested_check': 'Check filter'})}}]}}]})

    def provider(**kwargs):
        assert kwargs == {'base_url': 'https://judge.example.modal.run/v1', 'api_key': 'wk-test.ws-test'}
        return OpenAIProvider(openai_client=AsyncOpenAI(**kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    monkeypatch.setattr(hooks, 'infer_provider_class', lambda name: provider)
    hook = hooks.PydanticAIHook(llm_conn_id='judge', model_id='openai-chat:served-model', fallback_conn_ids=[])
    hook._seed_connection(SimpleNamespace(host='https://judge.example.modal.run/v1',
        password='wk-test.ws-test', extra_dejson={}))
    result = Agent(hook.get_conn(), output_type=Judgment).run_sync('Compare these SQL statements')
    assert result.output.verdict == 'incorrect'
    assert next(m for m in result.all_messages() if getattr(m, 'model_name', None)).model_name == 'served-model'
    assert len(seen) == 1
