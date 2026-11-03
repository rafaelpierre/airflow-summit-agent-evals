# Local validation — 2026-11-03

The local stack uses Docker Compose on the existing Colima Docker engine. Airflow is 3.3.2 with Python 3.13, Common AI 1.0.0, Pydantic AI 2.65.0, Phoenix client 3.6.0, Phoenix server 21.0.0, and PostgreSQL 16.11 for Airflow metadata only. Phoenix retains SQLite on its own named volume.

## Verified

- `uv lock --check --offline`: lockfile matches project metadata.
- `make setup`: locked dependencies install; runtime credentials are allowlisted; rerunning setup preserves Airflow keys/passwords.
- `uv run --locked pytest -q`: 26 tests pass, including mapping, snapshots, resume, re-evaluation isolation, report behavior, DAG serialization, and local credential handling.
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

Real application/model calls, real application trace delivery, remote connectivity, backup restoration, and a complete judged run through LocalExecutor remain unverified. Configure application credentials in `.env.agent`, generate a saved-output experiment on the host, and configure the Airflow `text2sql_judge_model`/`text2sql_judge_config` Variables and `judge` Connection before a live run. The backup procedure is documented but has not been executed automatically.

No cloud infrastructure was created and no changes were committed or pushed.

## Judge-only workflow and host CLI integration

Verified on 2026-11-03 after removing application execution from Airflow:

- `make up`, `make parse`, and `make verify`: rebuilt local Airflow stack is healthy; the judge-only DAG parses/serializes and remains paused. No DAG was triggered.
- Scheduler-side read of dataset `RGF0YXNldDoy` at version `RGF0YXNldFZlcnNpb246Mg==` returned all 10 examples; the scheduler has no configured application API/Azure credentials or standalone `JUDGE_MODEL`.
- `make test`: 26 offline tests pass, including judge-only preparation, lazy configuration recovery, saved-output normalization, credential isolation, and absence of an application task in the serialized DAG.
- `make agent-test`: 2 offline tests pass. Explicit Pydantic AI test models produce OpenInference CHAIN, AGENT, and LLM spans with the returned trace ID. No real model is substituted in live execution.
- `make agent-setup` / `make agent-check`: the isolated locked CLI environment and persistent local demo SQLite data initialize; all three Azure credential names are reported missing without displaying values.
- Existing application source is unchanged at upstream commit `d3c34388aef7487a882d260cf290af8115ac4baa`; the parent wrapper owns workshop instrumentation and JSON I/O.
- Imported 10 existing golden examples into local Phoenix as `agentic-text2sql-golden`: dataset `RGF0YXNldDoy`, version `RGF0YXNldFZlcnNpb246Mg==`. Full IDs are recorded in `outputs/dataset-import.json`. Reference SQL is unchanged; schema context is exported from the demo metadata.
- `uv run --locked --project workshop_agent python workshop_agent/verify_tracing.py`: sent and retrieved a clearly labeled synthetic trace with three CHAIN/AGENT/LLM spans. Evidence is in `outputs/agent-tracing-smoke.json`. This proves local OTLP delivery and OpenInference conversion, not live application/model behavior.
- `PHOENIX_BASE_URL=http://localhost:6006 uv run --locked python scripts/verify_saved_outputs.py --synthetic`: real Phoenix API check passed for native saved outputs, pinned dataset retrieval, configuration recovery without rereading settings, evaluator-error round-trip, annotation upsert, and completeness reporting. Judgments are explicit synthetic records. Evidence is in `outputs/saved-outputs-smoke.json`.

The app uses OpenInference Pydantic AI instrumentation **0.1.32** with Pydantic AI **2.65.0**, native instrumentation format 5, and locked OpenTelemetry dependencies. The integration follows the [OpenInference Pydantic AI processor documentation](https://arize-ai.github.io/openinference/python/instrumentation/openinference-instrumentation-pydantic-ai/), with installed-API and span-conversion checks. A harmless upstream event-loop deprecation warning remains in the test-model test.

Airflow only evaluates saved outputs. Its runtime allowlist excludes agent endpoints and Azure application credentials. Empty environment-backed Airflow Variables/Connections are omitted so they cannot mask UI or secrets-backend configuration. No paid calls, application deployment, or source push was performed.

## Native application tracing toggle

The nested `agentic-text2sql` checkout now owns `ask --trace` (off by default), optional tracing dependencies, and `text2sql_mvp/app/telemetry.py`. The workshop wrapper reuses that module. These application changes are local to the nested Git repository, not committed or pushed.

- Application offline suite: **53 passed**, including default-off behavior, missing-extra guidance, automatic agent/model spans, actual root IDs, and flush/shutdown on returned errors and exceptions. Existing seed-date deprecation warnings remain.
- Workshop validation after reuse: **26 evaluation tests + 2 instrumentation tests passed**; `make parse` passed.
- Synthetic OpenInference delivery/readback to local Phoenix passed with CHAIN, AGENT, and LLM spans. No paid model calls were made.
- Pydantic AI was updated from 1.73.0 to the tested 2.65.0 tracing pin; its OpenAI extra resolves the compatible OpenAI 3 SDK. Existing request-body tests were updated to use the SDK's httpx2 transport and pass for both Modal model routes.
- The host wrapper's readiness checks, credential allowlist, and `.env.agent.example` now use Modal configuration, matching the refreshed upstream app. Airflow still receives no application credentials.
