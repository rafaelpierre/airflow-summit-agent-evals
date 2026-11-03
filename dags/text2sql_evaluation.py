"""One manual evaluation DAG. All external access happens inside tasks."""
from datetime import timedelta
from airflow.sdk import dag, task, task_group, Param, Variable, get_current_context
from include.text2sql_eval.judge import SQLJudgeOperator


@dag(schedule=None, catchup=False, max_active_runs=1, max_active_tasks=2,
     default_args={'retries': 1, 'retry_delay': timedelta(seconds=30), 'execution_timeout': timedelta(minutes=20)},
     params={
         'mode': Param('new_experiment', enum=['new_experiment', 'evaluate_existing']),
         'dataset_version_id': Param(None, type=['null', 'string']),
         'app_revision': Param(None, type=['null', 'string']),
         'max_examples': Param(12, type='integer', minimum=1, maximum=100),
         'experiment_id': Param(None, type=['null', 'string']),
         'evaluation_config_id': Param(None, type=['null', 'string']),
         'new_evaluation_config': Param(False, type='boolean'),
         'baseline_experiment_id': Param(None, type=['null', 'string']),
         'baseline_evaluation_config_id': Param(None, type=['null', 'string']),
     }, tags=['text2sql', 'evaluation'])
def text2sql_evaluation():
    @task
    def prepare_run():
        import os
        from include.text2sql_eval.phoenix_adapter import PhoenixStore
        from include.text2sql_eval.workflow import prepare
        c = get_current_context()
        return prepare(PhoenixStore(), c['params'], [c['dag'].dag_id, c['run_id']],
            lambda: Variable.get('text2sql_judge_config', deserialize_json=True),
            os.getenv('JUDGE_MODEL'), os.getenv('PHOENIX_DATASET_ID'),
            Variable.get('text2sql_field_mapping', default={}, deserialize_json=True),
            Variable.get('text2sql_shared_context', default={}, deserialize_json=True))

    @task
    def run_experiment(ref):
        from include.text2sql_eval.phoenix_adapter import PhoenixStore
        from include.text2sql_eval.workflow import execute_application
        return execute_application(PhoenixStore(), ref)

    @task(trigger_rule='all_done')
    def prepare_judge_inputs(ref):
        from include.text2sql_eval.phoenix_adapter import PhoenixStore
        from include.text2sql_eval.workflow import judge_refs
        return judge_refs(PhoenixStore(), ref)

    @task_group
    def evaluate(ref):
        judgment = SQLJudgeOperator(task_id='judge_sql', ref=ref, retries=0, execution_timeout=timedelta(minutes=4))

        @task
        def persist_evaluation(envelope):
            from include.text2sql_eval.phoenix_adapter import PhoenixStore
            from include.text2sql_eval.workflow import persist
            return persist(PhoenixStore(), envelope)
        persist_evaluation(judgment.output)

    @task(trigger_rule='all_done')
    def consolidate(ref):
        import logging
        from include.text2sql_eval.phoenix_adapter import PhoenixStore
        from include.text2sql_eval.config import digest
        from include.text2sql_eval.reporting import build_report, render
        store = PhoenixStore()
        manifest = store.manifest(ref['manifest_id'])
        report = build_report(store, ref['experiment_id'], digest(manifest['config']),
                              manifest.get('baseline_experiment_id'), manifest.get('baseline_evaluation_config_id'))
        render(report)  # Validate renderability; export later from Phoenix, not a worker's temporary disk.
        logging.info('Evaluation counts: %s; complete=%s', report['summary']['counts'], report['summary']['complete'])
        return {'complete': report['summary']['complete'], **ref}

    @task
    def check_completeness(result):
        if not result['complete']:
            raise ValueError('Evaluation is incomplete; inspect saved Phoenix results and export the report')

    ref = prepare_run()
    application = run_experiment(ref)
    inputs = prepare_judge_inputs(ref)
    application >> inputs
    judgments = evaluate.expand(ref=inputs)
    report = consolidate(ref)
    judgments >> report
    check_completeness(report)


text2sql_evaluation()
