# Text2SQL evaluation flywheel

Judge saved Text2SQL experiment outputs with one manually triggered Airflow DAG. Run the application separately through its CLI. Phoenix stores versioned datasets, application outputs, configuration snapshots, and judgments; a shared renderer produces HTML and repair packets. Application repair stays outside the DAG.

## Quick start

With uv and the Colima Docker engine available:

```sh
make setup     # install locked dependencies and prepare local credentials
make up        # build and start Airflow and Phoenix
make status    # check running services
make down      # stop services while preserving database volumes
```

| Service | Local URL | Login |
| --- | --- | --- |
| Airflow | [localhost:8080](http://localhost:8080) | Username `admin`; read `AIRFLOW_ADMIN_PASSWORD` in the gitignored `.env.airflow` file |
| Phoenix | [localhost:6006](http://localhost:6006) | No login for this loopback-only local setup |

Dependencies are managed with **uv**, using `pyproject.toml` and `uv.lock`; the two requirements files have been removed. Local verification on 2026-11-03 passed **26 offline evaluation tests** and **2 offline instrumentation tests**, DAG parsing, service health/login checks, and Phoenix persistence across container recreation.

The evaluation DAG remains paused after setup. No agent or model calls were made during validation. See [Local checks and startup](#local-checks-and-startup) for prerequisites and verification commands.

## Deployment and status

Airflow runs locally with **Docker Compose / LocalExecutor**, using **Airflow 3.3.2 / Python 3.13** and uv-locked dependencies. Colima supplies the Docker engine on macOS. PostgreSQL stores Airflow metadata; Phoenix remains a separate SQLite-backed Compose service.

Implemented: a judge-only DAG with mapped Common AI judging, durable configuration snapshots, retry/resume, baseline comparison, self-contained reports, and a separate host CLI with OpenInference tracing. Airflow never executes the application.

Verified locally on 2026-11-03:

- uv lock/sync and 26 offline evaluation tests, including DAG import, mapping, and serialization.
- Compose image build, PostgreSQL initialization, API/scheduler/DAG-processor health, and authenticated local login.
- DAG parsing inside the scheduler; the evaluation DAG is registered and paused.
- Scheduler-to-Phoenix access through the shared Docker network, with Phoenix client **3.6.0** and server **21.0.0**.
- Synthetic Phoenix dataset and experiment results survive container recreation with the named volume retained.

Real agent and judge model calls still require credentials. See `docs/validation.md` for current import and tracing checks. Startup and validation make no paid inference calls. See `docs/validation.md` for the exact local checks.

## Layout and versions

```text
pyproject.toml / uv.lock        # application and dev dependencies, resolved by uv
Dockerfile                     # Apache Airflow image with a locked uv environment
compose.airflow.yaml           # API, scheduler, DAG processor, init, PostgreSQL
dags/text2sql_evaluation.py     # one DAG, max 1 active run / 2 active tasks
include/text2sql_eval/          # contracts, Phoenix adapter, execution, judging, reporting
include/templates/             # autoescaped, self-contained report
compose.phoenix.yaml            # separate Phoenix project, SQLite named volume
scripts/                       # import, preflight, export, synthetic verification
tests/                         # explicit offline doubles and real Airflow DAG parsing
```

Common AI **1.0.0** / Pydantic AI **2.65.0** are compatible with the tested Airflow version. `SQLJudgeOperator` subclasses `LLMOperator`; a mapped task group pairs each judgment with its persistence task. It loads saved inputs after template rendering so SQL is never treated as an Airflow template. No Python-task judge fallback is needed for the tested Airflow version. The container uses the same locked Airflow and provider versions as host tests.

The existing root Python package metadata and `src/` scaffold are preserved. The DAG imports `include/`; it does not depend on that separate CLI package.

## Credentials and configuration

Keep secrets in gitignored `.env` files or Airflow Connections. Pass only required credentials to each service. Generate an allowlisted runtime file:

```sh
uv run --locked python scripts/write_runtime_env.py --source .env --output .env.runtime
```

This uses `python-dotenv` from the uv `dev` dependency group and never prints values. Runtime variables:

| Name | Purpose |
| --- | --- |
| `PHOENIX_BASE_URL` | Caller-reachable Phoenix REST URL; host default is `http://localhost:6006` |
| `PHOENIX_API_KEY` | Phoenix API key for authenticated access |
| `AIRFLOW_VAR_TEXT2SQL_JUDGE_MODEL` | Optional environment-backed Airflow Variable for the explicit judge model identifier |
| `AIRFLOW_CONN_JUDGE` | Optional environment-backed Airflow Connection, type `pydanticai`, with the model API key in its password |

Set the nonsecret Airflow Variable `text2sql_judge_model` in the UI, CLI, or a supported secrets backend. The DAG reads it through `Variable.get` inside a task; it does not read `JUDGE_MODEL`. Set `text2sql_judge_config` for rubric and temperature. The `judge` Connection holds API credentials. Environment-backed equivalents above are optional; existing Connections/secrets backends work without `.env` credentials. The operator currently uses the OpenAI provider.

Application Modal credentials belong in the separate gitignored `.env.agent`; they are never forwarded to Airflow. `.env.agent.example` contains empty placeholders.

Example connection **shape only** (set the password privately):

```json
{"conn_type":"pydanticai","password":"REPLACE_PRIVATELY"}
```

The operator pins `openai:<text2sql_judge_model>` from the saved snapshot and disables provider fallbacks. A returned model identifier that differs from the snapshot produces an evaluator error rather than silently mixing models. Use a concrete dated model identifier, not a moving alias. The rubric currently supports `temperature`; choose a model supporting it. Unsupported provider settings surface as evaluator errors. Temperature zero does not guarantee deterministic judgment.

Import `docs/airflow-variables.json` through Airflow's Variables UI, or from a configured Airflow environment:

```sh
airflow variables import docs/airflow-variables.json
```

The golden dataset must contain `input.question`, `output.sql`, and metadata `schema_context`, `sql_dialect`, optional `business_rules`, and optional `split`. Every evaluation fetches the experiment's exact dataset version and validates its saved example identities and context. Rubric/model settings are frozen once per configuration and recovered on retry.

## Phoenix service

Install/start Docker Engine and Compose v2, then:

```sh
docker compose -f compose.phoenix.yaml up -d
docker compose -f compose.phoenix.yaml ps
docker compose -f compose.phoenix.yaml logs --tail=50 phoenix
```

The browser UI is [localhost:6006](http://localhost:6006). The single pinned service uses SQLite in `/mnt/phoenix` on `text2sql-phoenix-data`, with a Python-based `/healthz` check and host publishing restricted to loopback. It receives explicit Phoenix settings, not the contents of `.env`.

Phoenix creates the `text2sql-evaluation` network. Airflow joins it and uses `PHOENIX_BASE_URL=http://phoenix:6006`, overriding the host-facing URL in `.env.runtime`. Start Phoenix before Airflow and stop Airflow first. Phoenix has its own persistent volume and can stay running when Airflow is stopped.

Normal shutdown preserves data:

```sh
docker compose -f compose.phoenix.yaml down
```

Never add `-v` as routine cleanup. For a stopped-service backup:

```sh
mkdir -p outputs/backups
docker compose -f compose.phoenix.yaml stop phoenix
docker run --rm --entrypoint python \
  -v text2sql-phoenix-data:/data:ro -v "$PWD/outputs/backups:/backup" \
  arizephoenix/phoenix:version-21.0.0 \
  -c "import tarfile; t=tarfile.open('/backup/phoenix.tar.gz','w:gz'); t.add('/data',arcname='data'); t.close()"
docker compose -f compose.phoenix.yaml start phoenix
```

Restore a trusted backup into a **new empty** named volume with the same pinned image, preserving the original volume:

```sh
docker volume create text2sql-phoenix-restored
docker run --rm --entrypoint python \
  -v text2sql-phoenix-restored:/restore -v "$PWD/outputs/backups:/backup:ro" \
  arizephoenix/phoenix:version-21.0.0 \
  -c "import tarfile,shutil; t=tarfile.open('/backup/phoenix.tar.gz'); t.extractall('/tmp/restore',filter='data'); shutil.copytree('/tmp/restore/data','/restore',dirs_exist_ok=True)"
PHOENIX_VOLUME_NAME=text2sql-phoenix-restored docker compose -f compose.phoenix.yaml up -d --force-recreate
```

Back up before schema-changing upgrades. Backup/restore commands are provided for operation; restore has not been exercised automatically. Persistence verification is recorded in `docs/validation.md`.

For container-persistence verification on a **disposable test instance**, set `PHOENIX_BASE_URL` and run:

```sh
uv run --locked python scripts/verify_phoenix.py --seed
docker compose -f compose.phoenix.yaml down
docker compose -f compose.phoenix.yaml up -d
# Wait for health, then read the same saved records:
uv run --locked python scripts/verify_phoenix.py
```

This creates a clearly labeled synthetic dataset and experiment, never calls a real application/model, and saves IDs under ignored `outputs/`. Do not treat it as a benchmark.

## Application CLI and golden dataset

The application is [agentic-text2sql](https://github.com/rafaelpierre/agentic-text2sql), an independent shallow checkout:

```sh
# Once, if absent:
git clone --depth 1 https://github.com/rafaelpierre/agentic-text2sql.git apps/agentic-text2sql
make agent-setup
make agent-check
```

The initial upstream commit is `d3c34388aef7487a882d260cf290af8115ac4baa`. The clone keeps its own Git remote, is ignored by the parent repository, and is excluded from Airflow's Docker image. The application owns optional OpenInference instrumentation in `text2sql_mvp/app/telemetry.py`. The tracked `workshop_agent/cli.py` wrapper calls its pipeline with narration disabled, adds structured JSON output, and reuses that instrumentation. There is no REST server.

The wrapper has a separate uv lock/environment because the application requires SQLAlchemy 2 while Airflow uses SQLAlchemy 1.4. `make agent-setup` downloads NLTK wordnet/stopwords and initializes demo data once under ignored `outputs/agent/`. It does not call models or reseed an initialized database. Keep these SQLite files across baseline/candidate runs. Setup refuses to overwrite partially initialized tables. `make agent-test` runs explicit offline instrumentation tests.

Copy `.env.agent.example` to `.env.agent` if absent, then privately configure Modal proxy token, model endpoint URLs, and model names. Empty optional model/endpoint settings use the application defaults. Host tracing defaults to `http://localhost:6006/v1/traces` in project `agentic-text2sql`. An authenticated collector uses `PHOENIX_API_KEY`. The wrapper flushes traces before exiting and returns the real root trace ID.

Export the application's existing golden answers with schema metadata, then import them into Phoenix:

```sh
uv run --locked --project workshop_agent python workshop_agent/cli.py export-dataset > outputs/agent-golden.json
PHOENIX_BASE_URL=http://localhost:6006 uv run --locked python scripts/import_dataset.py \
  --name agentic-text2sql-golden --file outputs/agent-golden.json
```

The importer records dataset/version/example IDs in `outputs/dataset-import.json`. Reference SQL comes unchanged from the application's `eval/eval_examples.jsonl`; generated demo database rows are not additional golden answers. Existing datasets are reused without modifying their contents. Review references before treating this workshop dataset as an authoritative benchmark.

Run the application explicitly on the host, outside Airflow:

```sh
uv run --locked python scripts/run_application.py \
  --dataset-id DATASET_ID --dataset-version-id VERSION_ID --run-id baseline --max-examples 12
```

This reads `.env.agent`, sends only the question and stable request ID to the CLI over stdin, and saves outputs/errors to a Phoenix experiment. It does not run a judge. Reusing `--run-id` resumes missing/failed outputs with the same source fingerprint and inputs; a candidate uses a new run ID. A crash before persistence may repeat a CLI/model call. Each subprocess has a 60-second timeout; incorrect answers are never retried merely for being incorrect. Failures produce an incomplete record, not fabricated SQL. The actual application fingerprint and experiment ID are saved to `outputs/application-run.json`.

For a direct question using the application's own CLI and its `.env` credentials:

```sh
cd apps/agentic-text2sql
uv run --locked --extra tracing python cli.py ask "How many products are there?" --trace --no-narrate
```

Tracing is off without `--trace`. Its endpoint defaults to `http://localhost:6006/v1/traces`; set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, optional `PHOENIX_PROJECT_NAME`, and optional `PHOENIX_API_KEY` in the application's `.env` as needed. The CLI prints a real trace ID and flushes before exit. This exports traces only; use the host runner above to create saved experiment outputs for Airflow.

Instrumentation changes live in the nested application's Git repository and must be committed/pushed there separately. The workshop wrapper requires the application revision containing its telemetry module.

## Saved-output contract

The DAG accepts an existing Phoenix experiment ID. Candidate outputs may be a SQL string or an object with required `sql` and optional `trace_id`, `latency_ms`, and `app_revision`. Traces are separate from experiment outputs; exporting spans alone does not create an evaluable experiment.

The experiment pins the golden dataset version. Full-dataset native Phoenix experiments are supported; subset experiments must declare `selected_example_ids` metadata so missing outputs remain visible. The host runner supplies its durable manifest automatically. The MVP supports one repetition; duplicate identities or multiple repetitions fail validation. Missing/malformed application outputs remain incomplete and are not regenerated by Airflow.

## Local checks and startup

Install uv, Docker CLI with Compose, and Colima. Use a Docker engine with at least 4 GB memory (8 GB recommended). If creating a Colima VM:

```sh
colima start --cpu 4 --memory 8
```

For an existing running VM, changing resources may require `colima stop` first; this stops its containers. Keep the existing VM and volumes.

```sh
make setup     # uv sync --locked; allowlisted runtime env; persistent local secrets
make test      # offline tests, including DAG import/mapping/serialization
make up        # Phoenix first, then build/init/start Airflow and wait for health
make parse     # parse and serialize the DAG inside the running scheduler
make verify    # login, component health, and paused-DAG checks; no task execution
make rubric    # explicitly import the example judge rubric
make status
```

Open Airflow at [localhost:8080](http://localhost:8080) and Phoenix at [localhost:6006](http://localhost:6006). Airflow uses the local Simple Auth Manager: username `admin`, password stored privately as `AIRFLOW_ADMIN_PASSWORD` in `.env.airflow`. Read it in your editor. Startup pre-seeds the password file so it is not generated into container logs. Both UIs bind only to loopback. The DAG starts paused and has no schedule; startup makes no agent/model calls.

`make setup` preserves `.env.airflow` across reruns. Keep this file with the Airflow database: it includes the database password, Fernet key, and shared API signing keys. `.env.runtime` is regenerated from the allowlisted keys in `.env`; edit `.env` and rerun setup to change task credentials. Recreate Airflow containers with `make up` after credential changes. Do not print rendered Compose configuration, which contains secret values; use `config --quiet` for validation.

Common commands:

```sh
# Airflow only; keeps Phoenix running and preserves volumes:
docker compose --env-file .env.airflow -f compose.airflow.yaml down
# Stop both projects, preserving database and log volumes:
make down
# Inspect service logs:
docker compose --env-file .env.airflow -f compose.airflow.yaml logs --tail=50 airflow-scheduler
# Worker-side preflight (requires saved outputs and Airflow judge configuration):
docker compose --env-file .env.airflow -f compose.airflow.yaml exec airflow-scheduler \
  python scripts/preflight.py --experiment-id EXPERIMENT_ID
```

Dependencies are declared only in `pyproject.toml`. Use `uv add PACKAGE` or `uv add --dev PACKAGE`, review and commit `uv.lock`, then rebuild with `make up`. Host tests and CI use `uv sync --locked`; the image uses `uv sync --locked --no-dev --no-install-project` in an isolated environment. Keep the Airflow pin aligned with the Docker image version.

Use the explicit Compose filenames or Make targets. `docker-compose.yaml` is an existing, unrelated application example referring to absent `backend/` and `frontend/` directories; it is not the evaluation stack.

Preflight runs inside Airflow and resolves Variables and Connections through its configured secrets backends. It checks Phoenix health/version, pinned dataset, saved outputs, and judge configuration without making paid inference calls.

## Run, diagnose, compare

First run the application on the host and obtain its saved Phoenix experiment ID. Then trigger `text2sql_evaluation`:

```json
{"experiment_id":"OUTPUT_EXPERIMENT_ID"}
```

The DAG only fetches the pinned golden dataset and saved candidate outputs, maps judge/persistence tasks, and generates a report. It has no application task, endpoint, subprocess, or deployment step. On the first evaluation it snapshots the current Airflow rubric/model Variables. Retries recover that snapshot. Later runs reuse the sole saved configuration; supply `evaluation_config_id` when multiple configurations exist.

To deliberately evaluate with updated Airflow settings:

```json
{"experiment_id":"OUTPUT_EXPERIMENT_ID","new_evaluation_config":true}
```

Configuration hashes include rubric, model, context, and schema/evaluator versions. Prior annotations remain under their hash-qualified names. Incorrect SQL is a recorded outcome, not a task failure. Missing outputs or judgments, application errors, and evaluator errors leave the report incomplete and fail the final completeness task.

Each evaluation creates an immutable manifest-only ledger experiment linking to the original output experiment because the pinned client has no public experiment-metadata update method. Judgments are written to exact original experiment-run IDs. Ledger experiments are bookkeeping, not application benchmarks. Use the original output experiment ID for reporting and comparisons. A ledger is recovered by Airflow run identity on retry.

Export durable report inputs from Phoenix on your laptop:

```sh
uv run --locked python scripts/export_report.py --experiment-id ORIGINAL_EXPERIMENT_ID \
  --evaluation-config-id CONFIG_HASH --output-dir outputs/baseline
```

Outputs are `report.html`, `summary.json`, and `failures.json`. No shared worker filesystem is required. The DAG renders and logs aggregate counts; the exporter writes downloadable files. Reports show coverage, denominator, status, SQL pairs, real trace IDs, and provenance. No speculative Phoenix deep links or model costs are invented. Holdout rows remain in reports but are excluded from repair packets.

Use your existing Phoenix troubleshooting skill to inspect a failure's actual trace, propose a focused application fix, and review it outside Airflow. Do not alter reference SQL, scoring, or the rubric merely to improve results. Run the repaired application separately with a new host run ID and the same dataset, then trigger its evaluation with the same judge configuration and include `baseline_experiment_id` plus `baseline_evaluation_config_id` if needed. Exports also accept `--baseline-experiment-id` and `--baseline-evaluation-config-id`. Incompatible configurations are labeled; uncertain/missing/error pairs have no quality delta.

## Remote application routing and tracing

A remote application requires an existing private route or **authenticated HTTPS** endpoint to reach local Phoenix. Never publish this development Compose instance unauthenticated. Configure supported authentication before shared/remote use; provision no tunnel or paid infrastructure automatically. The preflight `--cloud` option checks remote endpoint requirements; it is independent of the local Airflow deployment choice.

Keep the application's current instrumentation and existing Codex Phoenix skill. Point their respective endpoints to this same instance:

- REST/UI: caller-reachable Phoenix base URL.
- OTLP HTTP traces: `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=<reachable-base>/v1/traces`, protocol `http/protobuf`.
- For authenticated tracing, configure an authorization bearer header using the existing exporter's supported secret configuration.

Verify a real application trace is retrievable with the existing skill before claiming the demo is end-to-end. Local Docker service DNS, `localhost`, and `host.docker.internal` do not route to a laptop from a remote host.

## References

- [Apache Airflow installation](https://airflow.apache.org/docs/apache-airflow/stable/installation.html)
- [Phoenix experiment APIs](https://arize-phoenix.readthedocs.io/projects/client/api/experiments.html)
- [Phoenix service configuration and OTLP endpoints](https://arize.com/docs/phoenix/self-hosting/configuration)
- [Common AI LLMOperator](https://airflow.apache.org/docs/apache-airflow-providers-common-ai/stable/operators/llm.html)
