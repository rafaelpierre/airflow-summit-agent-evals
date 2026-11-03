"""Parse and serialize the evaluation DAG in the running Airflow environment."""
from pathlib import Path
from airflow.models import DagBag
from airflow.serialization.serialized_objects import DagSerialization

bag = DagBag(dag_folder=str(Path(__file__).resolve().parents[1] / 'dags'))
if bag.import_errors:
    raise SystemExit('DAG import errors; inspect the Airflow import-error view.')
dag = bag.dags['text2sql_evaluation']
DagSerialization.to_dict(dag)
print('Evaluation DAG parsed and serialized successfully.')
