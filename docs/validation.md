# Local validation — 2026-11-03

The local stack uses Docker Compose on the existing Colima Docker engine. Airflow is 3.3.2 with Python 3.13, Common AI 1.0.0, Pydantic AI 2.65.0, Phoenix client 3.6.0, Phoenix server 21.0.0, and PostgreSQL 16.11 for Airflow metadata only. Phoenix retains SQLite on its own named volume.

## Verified

- `uv lock --check --offline`: lockfile matches project metadata.
- `make setup`: locked dependencies install; runtime credentials are allowlisted; rerunning setup preserves Airflow keys/passwords.
- `uv run --locked pytest -q`: 21 tests pass, including mapping, snapshots, resume, re-evaluation isolation, report behavior, DAG serialization, and local credential handling.
- `docker compose --env-file .env.airflow -f compose.airflow.yaml config --quiet`: configuration validates without printing secrets.
- Airflow image builds using `uv sync --locked --no-dev --no-install-project`.
- Airflow metadata migrations succeed; API, scheduler, DAG processor, PostgreSQL, and Phoenix reach healthy status.
- `python scripts/check_dag.py` inside the scheduler: evaluation DAG imports and serializes.
- `uv run --locked python scripts/verify_local_stack.py`: local admin login, database/scheduler/parser health, no import errors, and registered paused DAG.
- Scheduler HTTP request to `http://phoenix:6006/healthz`: succeeds over the shared Docker network.
- Recreating Airflow containers retains metadata and login credentials.
- Phoenix synthetic API smoke test passes before and after `docker compose -f compose.phoenix.yaml up -d --force-recreate --wait`, retaining its named volume. The same dataset, experiment, application output, and two evaluation configurations remain available. Local identifiers are recorded in ignored `outputs/compose-phoenix-smoke.json`.

The Phoenix check uses explicitly synthetic application responses and judgments, with no agent/model requests. It verifies persistence and API compatibility, not evaluation quality. The evaluation DAG remains paused and was not triggered.

Colima currently has 2 GB of memory. The idle stack reached healthy status at that size; this is not a loaded-run capacity test. Configure at least 4 GB, preferably 8 GB, before running evaluations.

## Not verified

Real agent and model calls, golden dataset import, application trace delivery, remote connectivity, backup restoration, and a complete evaluation run through the LocalExecutor remain unverified. Configure the caller-reachable agent URL, dataset/version IDs, judge model/connection, and rubric before a live run. The backup procedure is documented but has not been executed automatically.

No cloud infrastructure was created and no changes were committed or pushed.
