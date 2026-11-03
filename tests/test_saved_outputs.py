from types import SimpleNamespace
import pytest
from include.text2sql_eval.phoenix_adapter import PhoenixStore


def test_native_saved_outputs_normalize_and_fail_closed():
    runs = [
        {'id': 'run1', 'dataset_example_id': '1', 'repetition_number': 1, 'output': {'sql': 'select 1'}},
        {'id': 'run2', 'dataset_example_id': '2', 'repetition_number': 1, 'output': 'select 2'},
        {'id': 'run3', 'dataset_example_id': '3', 'repetition_number': 1, 'output': {'answer': 'not SQL'}},
        {'id': 'run4', 'dataset_example_id': '4', 'repetition_number': 1, 'output': None, 'error': 'private-error'},
    ]
    client = SimpleNamespace(experiments=SimpleNamespace(get_experiment=lambda **k: {'task_runs': runs, 'evaluation_runs': []}))
    normalized, _ = PhoenixStore(client).records('exp')
    assert [r['output']['status'] for r in normalized] == ['ok', 'ok', 'api_error', 'api_error']
    assert 'private-error' not in str(normalized)
    runs.append(runs[0])
    with pytest.raises(ValueError, match='unique'):
        PhoenixStore(client).records('exp')


def test_cli_child_receives_only_question_and_allowlisted_environment(tmp_path, monkeypatch):
    import sys
    from include.text2sql_eval.agent_cli import invoke
    script = tmp_path / 'echo_contract.py'
    script.write_text("import json, os, sys\nprint(json.dumps({'payload': json.load(sys.stdin), 'judge_present': 'AIRFLOW_CONN_JUDGE' in os.environ, 'airflow_present': 'AIRFLOW__CORE__FERNET_KEY' in os.environ}))\n")
    monkeypatch.setenv('AGENT_CLI_PYTHON', sys.executable)
    monkeypatch.setenv('AGENT_CLI_SCRIPT', str(script))
    monkeypatch.setenv('AIRFLOW_CONN_JUDGE', 'never-forward')
    monkeypatch.setenv('AIRFLOW__CORE__FERNET_KEY', 'never-forward')
    result = invoke('ask', {'question': 'Question', 'request_id': 'request'})
    assert result == {'payload': {'question': 'Question', 'request_id': 'request'},
                      'judge_present': False, 'airflow_present': False}


def test_host_cli_failure_and_request_contract(monkeypatch):
    import subprocess
    from include.text2sql_eval import agent_cli
    calls = []
    def invoke(command, payload):
        calls.append(payload)
        raise subprocess.TimeoutExpired('redacted', 60)
    monkeypatch.setattr(agent_cli, 'invoke', invoke)
    output = agent_cli.call_cli('exp', {'example_id': 'id', 'question': 'Question', 'reference_sql': 'secret-golden'}, 'revision')
    assert output == {'status': 'api_error', 'error': 'cli_timeout'}
    assert set(calls[0]) == {'question', 'request_id'}
