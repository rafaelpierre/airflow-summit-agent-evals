AIRFLOW = docker compose --env-file .env.airflow -f compose.airflow.yaml
PHOENIX = docker compose -f compose.phoenix.yaml

.PHONY: setup test build up down status phoenix parse rubric verify
setup:
	uv sync --locked
	uv run --locked python scripts/write_runtime_env.py
	uv run --locked python scripts/init_airflow_env.py

test:
	uv run --locked pytest -q

build:
	$(AIRFLOW) build airflow-init

phoenix:
	$(PHOENIX) up -d --wait

up: phoenix build
	$(AIRFLOW) up -d --no-build --wait --wait-timeout 180

down:
	$(AIRFLOW) down
	$(PHOENIX) down

status:
	$(AIRFLOW) ps
	$(PHOENIX) ps

parse:
	$(AIRFLOW) exec -T airflow-scheduler python scripts/check_dag.py

rubric:
	$(AIRFLOW) exec -T airflow-scheduler airflow variables import docs/airflow-variables.json

verify:
	uv run --locked python scripts/verify_local_stack.py
