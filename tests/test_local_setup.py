import json
import os

from dotenv import dotenv_values
from scripts.init_airflow_env import initialize
from scripts import start_airflow_api, write_runtime_env


def test_local_secrets_survive_setup_without_logging(tmp_path, capsys):
    path = tmp_path / '.env.airflow'
    initialize(path)
    original = path.read_bytes()
    initialize(path)
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600
    values = dotenv_values(path)
    assert values['POSTGRES_PASSWORD'] in values['AIRFLOW__DATABASE__SQL_ALCHEMY_CONN']
    output = capsys.readouterr().out
    for value in values.values():
        assert value not in output


def test_api_seeds_password_before_starting_without_logging(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'passwords.json'
    monkeypatch.setenv('AIRFLOW_ADMIN_PASSWORD', 'test-password')
    monkeypatch.setenv('AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE', str(path))
    calls = []
    monkeypatch.setattr(os, 'execvp', lambda *args: calls.append(args))
    start_airflow_api.main()
    assert json.loads(path.read_text()) == {'admin': 'test-password'}
    assert path.stat().st_mode & 0o777 == 0o600
    assert 'AIRFLOW_ADMIN_PASSWORD' not in os.environ
    assert calls == [('airflow', ['airflow', 'api-server'])]
    assert 'test-password' not in capsys.readouterr().out


def test_runtime_env_only_forwards_allowlisted_keys(tmp_path, monkeypatch):
    source = tmp_path / '.env'
    output = tmp_path / '.env.runtime'
    source.write_text("UNRELATED_SECRET=never-forward\nAGENT_API_KEY=never-forward\nAZURE_OPENAI_API_KEY=never-forward\nAIRFLOW_CONN_JUDGE='abc$123'\n")
    for key in write_runtime_env.ALLOWED:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr('sys.argv', ['write_runtime_env', '--source', str(source), '--output', str(output)])
    write_runtime_env.main()
    values = dotenv_values(output, interpolate=False)
    assert set(values) == write_runtime_env.ALLOWED - {'AIRFLOW_VAR_TEXT2SQL_JUDGE_MODEL', 'AIRFLOW_CONN_TEXT2SQL_API'}
    assert values['AIRFLOW_CONN_JUDGE'] == 'abc$123'
    assert 'never-forward' not in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600
