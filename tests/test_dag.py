from pathlib import Path
from airflow.models import DagBag
from airflow.serialization.serialized_objects import DagSerialization
from airflow.providers.common.ai.operators.llm import LLMOperator


def test_dag_parses_maps_and_serializes_without_external_access(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network at parse time')))
    bag = DagBag(dag_folder=str(Path(__file__).parents[1] / 'dags'))
    assert not bag.import_errors
    dag = bag.dags['text2sql_evaluation']
    assert dag.max_active_runs == 1 and dag.max_active_tasks == 2
    assert not dag.catchup
    judge = dag.get_task('evaluate.judge_sql')
    assert isinstance(judge, LLMOperator)
    assert 'ref' in judge.template_fields
    assert type(judge.task_group).__name__ == 'MappedTaskGroup'
    assert dag.get_task('consolidate').trigger_rule == 'all_done'
    assert dag.get_task('check_completeness').trigger_rule == 'all_success'
    assert 'run_experiment' in dag.get_task('prepare_judge_inputs').upstream_task_ids
    DagSerialization.to_dict(dag)
