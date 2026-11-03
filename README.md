# Text2SQL evaluation flywheel

Evaluate an existing Text2SQL REST API with one manually triggered Airflow DAG. Phoenix stores versioned datasets, application outputs, configuration snapshots, and judgments; a shared renderer produces HTML and repair packets. Application repair stays outside the DAG.

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

Dependencies are managed with **uv**, using `pyproject.toml` and `uv.lock`; the two requirements files have been removed. Local verification on 2026-11-03 passed **21 tests**, DAG parsing, service health/login checks, and Phoenix persistence across container recreation.

The evaluation DAG remains paused after setup. No agent or model calls were made during validation. See [Local checks and startup](#local-checks-and-startup) for prerequisites and verification commands.

## Deployment and status

Airflow runs locally with **Docker Compose / LocalExecutor**, using **Airflow 3.3.2 / Python 3.13** and uv-locked dependencies. Colima supplies the Docker engine on macOS. PostgreSQL stores Airflow metadata; Phoenix remains a separate SQLite-backed Compose service.

Implemented: mapped Common AI judging, durable manifests, retry/resume, re-evaluation without application calls, baseline comparison, self-contained reports, import/preflight scripts, and an isolated Phoenix Compose service.

Verified locally on 2026-11-03:

- uv lock/sync and 21 offline tests, including DAG import, mapping, and serialization.
- Compose image build, PostgreSQL initialization, API/scheduler/DAG-processor health, and authenticated local login.
- DAG parsing inside the scheduler; the evaluation DAG is registered and paused.
- Scheduler-to-Phoenix access through the shared Docker network, with Phoenix client **3.6.0** and server **21.0.0**.
- Synthetic Phoenix dataset and experiment results survive container recreation with the named volume retained.

Real agent/model calls, golden-data import, and application tracing still require configuration. Startup and validation make no paid inference calls. See `docs/validation.md` for the exact local checks.

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
| `PHOENIX_DATASET_ID` | Imported dataset ID |
| `AGENT_URL` | Agent's POST inference endpoint |
| `AGENT_API_KEY` | Optional bearer credential |
| `AGENT_HEALTH_URL` | Optional read-only GET health endpoint for preflight |
| `JUDGE_MODEL` | Explicit dated OpenAI model identifier supported by your account and temperature setting |
| `AIRFLOW_CONN_JUDGE` | JSON Airflow Connection, type `pydanticai`, password containing model API key |

Example connection **shape only** (set the password privately):

```json
{"conn_type":"pydanticai","password":"REPLACE_PRIVATELY"}
```

The operator pins `openai:<JUDGE_MODEL>` from the saved snapshot and disables provider fallbacks. A returned model identifier that differs from the snapshot produces an evaluator error rather than silently mixing models. Use a concrete dated model identifier, not a moving alias. The rubric currently supports `temperature`; choose a model supporting it. Unsupported provider settings surface as evaluator errors. Temperature zero does not guarantee deterministic judgment.

Import `docs/airflow-variables.json` through Airflow's Variables UI, or from a configured Airflow environment:

```sh
airflow variables import docs/airflow-variables.json
```

Optional Variables `text2sql_field_mapping` and `text2sql_shared_context` are JSON objects. Default source paths are `input.question`, `output.sql`, and `metadata.schema_context`, `metadata.sql_dialect`, `metadata.business_rules`, `metadata.split`. Field mapping overrides these dotted paths. Shared context supplies missing context fields. Every selected example's effective context is frozen in the manifest.

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

## Golden dataset and API contract

Import the user's existing data from a JSON array of normalized examples:

```json
[{"example_id":"source-id","question":"...","reference_sql":"...","schema_context":"...","sql_dialect":"postgresql","business_rules":"...","split":"holdout"}]
```

```sh
uv run --locked python scripts/import_dataset.py --name text2sql-golden --file /path/to/existing-golden.json
```

The script reuses an existing named dataset without modifying it, or creates one. It records new Phoenix dataset/version/example IDs in `outputs/dataset-import.json`; source IDs are metadata, not Phoenix IDs. Pin the returned version in every run. Historical traces/IDs do not migrate automatically. `docs/calibration.json` contains separate, manually labeled synthetic valid/invalid SQL pairs for judge calibration, not replacement golden data.

The application receives **only** `{"question":"...","request_id":"..."}`. Default response:

```json
{"sql":"SELECT ...","trace_id":null,"latency_ms":null,"app_revision":null}
```

Only `sql` is required. Trace IDs, if supplied, must be real 32-character lowercase hexadecimal OpenTelemetry trace IDs. Missing latency is measured and labeled `client`; reported revisions are checked against the requested revision. Adapt `agent_api.py` to a different real API contract before live execution. Requests have a 60-second timeout, no redirects, and stable IDs. There is no exactly-once guarantee: a crash after an HTTP response but before persistence can repeat the request unless the application implements idempotency.

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

For a host-run agent, use a container-reachable `AGENT_URL`; `localhost` inside Airflow means that container. On Colima, `host.lima.internal` is the host route; verify the agent is listening on an interface reachable from the VM. Remote agents need their own reachable URL. The application trace exporter and host scripts still use their own caller-reachable Phoenix URL.

Common commands:

```sh
# Airflow only; keeps Phoenix running and preserves volumes:
docker compose --env-file .env.airflow -f compose.airflow.yaml down
# Stop both projects, preserving database and log volumes:
make down
# Inspect service logs:
docker compose --env-file .env.airflow -f compose.airflow.yaml logs --tail=50 airflow-scheduler
# Worker-side preflight (requires dataset, agent, and judge configuration):
docker compose --env-file .env.airflow -f compose.airflow.yaml exec airflow-scheduler \
  python scripts/preflight.py --dataset-version-id VERSION_ID
```

Dependencies are declared only in `pyproject.toml`. Use `uv add PACKAGE` or `uv add --dev PACKAGE`, review and commit `uv.lock`, then rebuild with `make up`. Host tests and CI use `uv sync --locked`; the image uses `uv sync --locked --no-dev --no-install-project` in an isolated environment. Keep the Airflow pin aligned with the Docker image version.

Use the explicit Compose filenames or Make targets. `docker-compose.yaml` is an existing, unrelated application example referring to absent `backend/` and `frontend/` directories; it is not the evaluation stack.

Before a live run, from the actual caller environment:

```sh
uv run --locked python scripts/preflight.py --dataset-version-id VERSION_ID
```

Preflight checks configured names, Phoenix health/server version, dataset access, optional agent health, and the judge connection shape. It makes no paid inference calls. A successful host check does not prove worker connectivity. Test the same command inside the scheduler and from the remote application environment as appropriate.

## Run, diagnose, compare

Trigger `text2sql_evaluation` with:

```json
{"mode":"new_experiment","dataset_version_id":"PHOENIX_VERSION_ID","app_revision":"baseline-revision","max_examples":12}
```

The DAG selects examples in stable ID order, persists a full manifest before application calls, saves responses as they complete, and maps judge/persistence pairs for successful outputs. Retries recover the same manifest and preserve successful responses. Incorrect SQL is a result, not something to retry until it passes. Missing work, API failures, and evaluator failures leave the report incomplete; the final task fails for incomplete results.

Re-evaluate saved outputs with no application calls:

```json
{"mode":"evaluate_existing","experiment_id":"ORIGINAL_EXPERIMENT_ID","evaluation_config_id":"SAVED_CONFIG_HASH"}
```

Omit the configuration selector only when exactly one exists. To deliberately use the current rubric/model, set `new_evaluation_config:true` instead. Configuration hashes include rubric, model, context, and schema/evaluator versions. Existing annotations remain under their original hash-qualified names.

Phoenix does not expose an experiment-metadata update method in the selected public client. Each re-evaluation therefore creates an immutable **manifest-only ledger experiment** linking to the original output experiment. Results are still annotated on the original experiment's exact run IDs. Ledger experiments are bookkeeping, not application benchmarks; their Phoenix run counts are intentionally empty. Use the original experiment ID when reporting/comparing. The ledger records the frozen configuration and baseline selectors before judging. Recovery uses an Airflow-run identity stored in metadata; keep this DAG's single-writer setting. Ambiguous duplicate manifests fail explicitly.

Export durable report inputs from Phoenix on your laptop:

```sh
uv run --locked python scripts/export_report.py --experiment-id ORIGINAL_EXPERIMENT_ID \
  --evaluation-config-id CONFIG_HASH --output-dir outputs/baseline
```

Outputs are `report.html`, `summary.json`, and `failures.json`. No shared worker filesystem is required. The DAG renders and logs aggregate counts; the exporter writes downloadable files. Reports show coverage, denominator, status, SQL pairs, real trace IDs, and provenance. No speculative Phoenix deep links or model costs are invented. Holdout rows remain in reports but are excluded from repair packets.

Use your existing Phoenix troubleshooting skill to inspect a failure's actual trace, propose a focused application fix, and review it outside Airflow. Do not alter reference SQL, scoring, or the rubric merely to improve results. Run a candidate with the same dataset/context/judge and include `baseline_experiment_id` plus `baseline_evaluation_config_id` if needed. Exports also accept `--baseline-experiment-id` and `--baseline-evaluation-config-id`. Incompatible configurations are labeled; uncertain/missing/error pairs have no quality delta.

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
