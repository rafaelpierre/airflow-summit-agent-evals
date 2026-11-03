# Text2SQL evaluation flywheel

Generate and judge Text2SQL experiment outputs with one manually triggered Airflow DAG. The Experiment stage calls the separately hosted application API for each golden dataset row; evaluation-only runs can reuse saved outputs. Phoenix stores versioned datasets, application outputs, configuration snapshots, and judgments; a shared renderer produces HTML and repair packets. Application repair stays outside the DAG.

## Setup: first successful API experiment

Run the commands below from this repository's root unless a step says otherwise. You need uv, Docker CLI with Compose v2, Colima, and access to the application and judge model endpoints. The application and judge can use different Modal endpoints/models.

### 1. Start Airflow and Phoenix

Start your existing Colima VM, or create one with sufficient memory:

```sh
colima start --cpu 4 --memory 8
make setup
make up
make parse
make status
```

If Colima is already running, reuse it; changing VM resources can require a stop/start. `make setup` installs locked dependencies and creates persistent local credentials. `make up` builds the Airflow image, starts Phoenix, initializes Airflow, and waits for service health. These commands do not trigger model calls. Do not run `make down` until you want to stop the stack.

| Service | Local URL | Login |
| --- | --- | --- |
| Airflow | [localhost:8080](http://localhost:8080) | Username `admin`; read `AIRFLOW_ADMIN_PASSWORD` privately in the gitignored `.env.airflow` file |
| Phoenix | [localhost:6006](http://localhost:6006) | No login for this loopback-only local setup |

Keep `.env.airflow` and the Docker volumes across restarts. The DAG is initially paused. `make verify` checks startup health and expects it to still be paused; use it before unpausing your first run.

### 2. Prepare the application and golden dataset

If `apps/agentic-text2sql` is absent, clone it once:

```sh
git clone --depth 1 https://github.com/rafaelpierre/agentic-text2sql.git apps/agentic-text2sql
```

Use a revision containing `text2sql_mvp/app/api.py` and its tracing support. Preserve an existing checkout and its local changes. Initialize the workshop database and download NLTK data:

```sh
make agent-setup
make agent-check
```

Create `.env.agent` from `.env.agent.example` only if it does not exist. Edit it privately with the application's `MODAL_API_TOKEN` (combined proxy token), `FAST_MODEL_BASE_URL`, `SQL_MODEL_BASE_URL`, and any required `FAST_MODEL`/`SQL_MODEL` overrides. Both model base URLs include `/v1`. These are application credentials; the judge is configured separately in step 4.

Export and import the golden examples once, reusing the existing dataset if present:

```sh
uv run --locked --project workshop_agent python workshop_agent/cli.py export-dataset > outputs/agent-golden.json
PHOENIX_BASE_URL=http://localhost:6006 uv run --locked python scripts/import_dataset.py \
  --name agentic-text2sql-golden --file outputs/agent-golden.json
```

Open `outputs/dataset-import.json` and retain its `dataset_id` and `dataset_version_id`. Use the IDs from your instance, not IDs copied from another installation. If the dataset is already imported and those IDs are available, skip this import.

### 3. Start the application API

In a separate terminal, start from this repository's root. The following command explicitly reuses the workshop database and NLTK files created above and loads `.env.agent`:

```sh
EVAL_PROJECT_ROOT="$PWD"
(
  cd apps/agentic-text2sql
  DB_URL="sqlite:///$EVAL_PROJECT_ROOT/outputs/agent/text2sql.db" \
  NLTK_DATA="$EVAL_PROJECT_ROOT/outputs/nltk_data" \
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:6006/v1/traces \
  TEXT2SQL_TRACING=true \
  uv run --locked --extra tracing --env-file "$EVAL_PROJECT_ROOT/.env.agent" \
    uvicorn text2sql_mvp.app.api:app --host 0.0.0.0 --port 8000
)
```

Leave this terminal running. If you already have a configured API and database, keep using them and use their reachable URL in step 4. The upstream API does not automatically use the workshop wrapper's database paths; explicit paths avoid accidentally opening an empty database. Its own `.env` is also loaded, but explicit environment settings take precedence.

`0.0.0.0` allows the Colima containers to reach the host API. This application has no authentication middleware, so use a trusted local/private network. The API docs are at [localhost:8000/docs](http://localhost:8000/docs). Check liveness from an Airflow container without making an inference call:

```sh
docker compose --env-file .env.airflow -f compose.airflow.yaml exec -T airflow-scheduler \
  python -c "import httpx; r=httpx.get('http://host.lima.internal:8000/health', timeout=10); r.raise_for_status(); print(r.json())"
```

Expect `{"status":"ok"}`. The Colima route is `host.lima.internal`; `localhost` inside Airflow refers to the Airflow container. If your engine uses another host route, verify it and use it consistently. A health check verifies connectivity, not model credentials or inference.

### 4. Configure the two Airflow Connections and judge Variables

Log into Airflow and open **Admin → Connections → Add Connection**. Save these two Connections:

| Field | Application Connection | Judge Connection (Modal) |
| --- | --- | --- |
| Connection ID | `text2sql_api` | `judge` |
| Connection type | HTTP (`http`) | Pydantic AI (`pydanticai`) |
| Host | `http://host.lima.internal:8000/ask` | `https://YOUR-ENDPOINT.modal.run/v1` |
| Password | Empty for the local API; bearer token only if your proxy requires it | Endpoint bearer API key, or combined Modal proxy token `TOKEN_ID.TOKEN_SECRET` |
| Login, Schema/Model, Port, Extra | Leave empty | Leave empty; the model is selected by the Variable below |

Use the **full URL** in Host. The application URL ends in `/ask`; the judge URL ends in `/v1`, without `/chat/completions`. The judge speaks the OpenAI-compatible Chat Completions protocol; it does not require an OpenAI-hosted model or a Modal-specific Airflow provider. The Modal server must support tool calls for structured judgments.

The pinned HTTP provider **6.3.0** supplies the HTTP option, and Common AI **1.0.0** supplies Pydantic AI. If either is missing from the menu, run `make setup` followed by `make up` to rebuild/recreate the containers, then refresh the browser. Installing a package only in the host virtual environment does not update Airflow's containers.

Import the sample rubric from the repository root:

```sh
make rubric
```

Then open **Admin → Variables** and verify both required Variables:

| Key | Value |
| --- | --- |
| `text2sql_judge_config` | JSON rubric imported by `make rubric`; includes `rubric_version`, `rubric`, and `temperature` |
| `text2sql_judge_model` | The exact model ID served by your Modal endpoint, as a plain string with no provider prefix |

**You must create `text2sql_judge_model` yourself.** `make rubric` does not set it. Use the model's exact served ID, without `openai:` or `openai-chat:`. It must match the response's model identifier. Setting a model on the Connection does not replace this Variable. Keep credentials out of Variables.

For Modal proxy authentication, Password contains the proxy token ID and secret joined by a period; see [Modal's bearer authentication format](https://modal.com/docs/guide/webhook-proxy-auth). Do not use a Modal workspace API token. For a custom bearer-authenticated endpoint, use its API key instead.

### 5. Trigger a one-row test

Open **DAGs → text2sql_evaluation**, unpause it, and choose **Trigger DAG**. Fill the dataset fields using `outputs/dataset-import.json`, set `max_examples` to `1`, and leave `experiment_id` empty. The equivalent JSON is:

```json
{
  "experiment_id": null,
  "dataset_id": "YOUR_DATASET_ID",
  "dataset_version_id": "YOUR_DATASET_VERSION_ID",
  "max_examples": 1
}
```

Leave the baseline and evaluation configuration selectors empty for the first run, and leave `new_evaluation_config` false. `experiment_id` is optional and is used only to re-evaluate an existing experiment. Confirm the trigger; this performs real application and judge inference calls.

Watch the run in Graph/Grid view:

```text
prepare_run → prepare_experiment_inputs → run_experiment (mapped)
            → prepare_judge_inputs → evaluate.judge_sql → evaluate.persist_evaluation
            → consolidate → check_completeness
```

Inspect failed task logs if a task turns red. `prepare_run` returns the original `experiment_id` in its XCom; use that ID to find the experiment in Phoenix. Successful application outputs receive judge annotations there. An `incorrect` verdict is a valid result and does not by itself fail the DAG. API/evaluator failures and missing results make the final completeness task fail.

After the one-row test succeeds, trigger a new run with `max_examples` empty/null to process the full dataset, up to 1024 rows. A new dataset-triggered run creates a new experiment and calls the API again. See [Run, diagnose, compare](#run-diagnose-compare) for re-evaluation without application calls and report export.

### 6. Recover from configuration mistakes

| Symptom | Fix |
| --- | --- |
| `VARIABLE_NOT_FOUND: text2sql_judge_model` | Add the exact Variable in step 4, save it, then clear the failed `prepare_run` task to retry. No experiment snapshot was created by this failure. |
| Missing `text2sql_judge_config` | Run `make rubric`, then retry `prepare_run`. This command overwrites that Variable with the example rubric, so preserve an intentional custom rubric first. |
| `experiment_id` appears mandatory | Refresh the trigger page after the DAG processor loads the current DAG. `make parse` verifies the file imports. New experiments accept an empty field or JSON `null`. |
| HTTP/Pydantic AI absent from connection types | Rebuild with `make up` after installing the locked dependencies; refresh the UI. |
| API connection refused or timeout | Keep the API terminal running, verify the container-side `/health` command, and check the bind interface and host route. |
| Judge authentication failure | Verify the `judge` Host and Password. Modal proxy credentials use the combined proxy token, not a workspace API token. |
| `model_identity_mismatch` | Use the exact model ID returned by the endpoint. For an already saved configuration, create a new evaluation configuration rather than expecting a Variable edit to change it. |
| Judge requests `/responses` against a Chat Completions endpoint | Current new snapshots explicitly select `openai-chat`. For a legacy saved experiment, trigger re-evaluation with `new_evaluation_config: true`. |
| “Skipping masking for a secret as it's too short” | This warning is separate from a missing Variable. Follow the actual task exception; do not paste credentials into logs or chat. |

Once preparation has succeeded, the saved rubric/model configuration is immutable for retries. To change it deliberately, use the existing output experiment ID with `new_evaluation_config: true`. API results, including saved API failures, survive task clearing; to repeat application requests, create a new dataset-triggered experiment. Do not repeatedly clear tasks to turn incorrect SQL into a passing answer.

To stop the local infrastructure while retaining data:

```sh
make down
```

Stop the separate API terminal with Ctrl-C. Do not use volume deletion flags.

## Deployment and status

Airflow runs locally with **Docker Compose / LocalExecutor**, using **Airflow 3.3.2 / Python 3.13** and uv-locked dependencies. Colima supplies the Docker engine on macOS. PostgreSQL stores Airflow metadata; Phoenix remains a separate SQLite-backed Compose service.

Implemented: mapped HTTP Experiment tasks followed by Common AI judging, durable configuration snapshots, retry/resume, baseline comparison, self-contained reports, and an optional host CLI with OpenInference tracing. The application API runs separately; Airflow invokes it over HTTP.

Verified locally on 2026-11-03:

- 38 offline tests, including nullable trigger parameters, mapping, configuration snapshots, and Modal-compatible Chat Completions through an explicit HTTP test double.
- Compose image build, PostgreSQL initialization, API/scheduler/DAG-processor health, and authenticated local login.
- DAG parsing and serialization inside the scheduler; the evaluation DAG is registered.
- Scheduler-to-Phoenix access through the shared Docker network, with Phoenix client **3.6.0** and server **21.0.0**.
- Synthetic Phoenix dataset and experiment results survive container recreation with the named volume retained.

The user reported a working setup after the HTTP provider, optional experiment ID, judge model Variable, and Chat Completions fixes. The automated checks above use offline/synthetic model responses and do not independently verify that live result. Startup and offline validation make no paid inference calls. `docs/validation.md` retains historical checks from earlier workflow versions.

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

The HTTP provider **6.3.0** registers the HTTP connection type used by `text2sql_api` in the Airflow UI. Common AI **1.0.0** / Pydantic AI **2.65.0** are compatible with the tested Airflow version. `SQLJudgeOperator` subclasses `LLMOperator`; a mapped task group pairs each judgment with its persistence task. It loads saved inputs after template rendering so SQL is never treated as an Airflow template. No Python-task judge fallback is needed for the tested Airflow version. The container uses the same locked Airflow and provider versions as host tests.

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
| `AIRFLOW_CONN_TEXT2SQL_API` | Optional environment-backed HTTP Connection for the application `/ask` endpoint |

Set the nonsecret Airflow Variable `text2sql_judge_model` in the UI, CLI, or a supported secrets backend. The DAG reads it through `Variable.get` inside a task; it does not read `JUDGE_MODEL`. Set `text2sql_judge_config` for rubric and temperature. The `judge` Connection holds API credentials. Environment-backed equivalents above are optional; existing Connections/secrets backends work without `.env` credentials. The operator uses the OpenAI-compatible protocol, including Modal-hosted models.

Application Modal credentials belong in the separate gitignored `.env.agent`; load it explicitly when starting the API as shown above. They are never forwarded to Airflow. `.env.agent.example` contains empty placeholders.

Example connection **shape only** (set the password privately):

```json
{"conn_type":"pydanticai","password":"REPLACE_PRIVATELY"}
```

For an **OpenAI-compatible Modal judge**, keep Connection ID `judge` and type `pydanticai` (shown as Pydantic AI in the UI). Set Host to the endpoint's full base URL, for example `https://YOUR-ENDPOINT.modal.run/v1` (not `/chat/completions`). Set Password to its bearer API key. For Modal proxy authentication, use the combined proxy token `TOKEN_ID.TOKEN_SECRET` in Password; [Modal supports this bearer format](https://modal.com/docs/guide/webhook-proxy-auth). Do not use a Modal workspace API token. Leave Login and Extra empty for this setup.

Set Variable `text2sql_judge_model` to the exact served model name, without an `openai:` prefix. It must match the model identifier returned by the endpoint. The server must support Chat Completions tool calls for the structured judgment and the configured temperature; a text-only endpoint is not sufficient. Credentials remain in the Connection. No additional Modal Airflow provider is needed.

New configurations pin `openai-chat:<text2sql_judge_model>` and the Chat Completions API in the saved snapshot and disable provider fallbacks. A returned model identifier that differs from the snapshot produces an evaluator error rather than silently mixing models. Use a stable served model identifier (a dated identifier for OpenAI), not a moving alias. The rubric currently supports `temperature`; choose a model supporting it. Unsupported provider settings surface as evaluator errors. Temperature zero does not guarantee deterministic judgment.

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

The initial upstream commit is `d3c34388aef7487a882d260cf290af8115ac4baa`. The clone keeps its own Git remote, is ignored by the parent repository, and is excluded from Airflow's Docker image. The application owns optional OpenInference instrumentation in `text2sql_mvp/app/telemetry.py`. The tracked `workshop_agent/cli.py` wrapper calls its pipeline with narration disabled, adds structured JSON output, and reuses that instrumentation. The application also provides a FastAPI server at `text2sql_mvp.app.api:app`.

The wrapper has a separate uv lock/environment to keep application dependencies isolated from the Airflow runtime. `make agent-setup` downloads NLTK wordnet/stopwords and initializes demo data once under ignored `outputs/agent/`. It does not call models or reseed an initialized database. Keep these SQLite files across baseline/candidate runs. Setup refuses to overwrite partially initialized tables. `make agent-test` runs explicit offline instrumentation tests.

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

For evaluation-only runs, the DAG accepts an existing Phoenix experiment ID. Candidate outputs may be a SQL string or an object with required `sql` and optional `trace_id`, `latency_ms`, and `app_revision`. Traces are separate from experiment outputs; exporting spans alone does not create an evaluable experiment.

The experiment pins the golden dataset version. Full-dataset native Phoenix experiments are supported; subset experiments must declare `selected_example_ids` metadata so missing outputs remain visible. The host runner supplies its durable manifest automatically. The MVP supports one repetition; duplicate identities or multiple repetitions fail validation. Missing/malformed saved outputs remain incomplete during evaluation-only runs. New API experiments generate outputs only for rows without a persisted run.

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

For a new experiment, start the existing application API separately with its database/model configuration. Configure Airflow Connection **`text2sql_api`** (type `http`): set **Host** to the full worker-reachable URL including `/ask`, and optionally **Password** to an authenticated proxy bearer token. The current application API itself has no authentication middleware. Keep it on a trusted local/private network. With Colima, use a host route such as `http://host.lima.internal:8000/ask` and verify worker connectivity; container `localhost` points to the container. Bind the application to an interface reachable through that route.

An optional environment-backed Connection uses `AIRFLOW_CONN_TEXT2SQL_API` in the gitignored `.env`, then `make setup` and `make up`. Its JSON shape is `{"conn_type":"http","host":"http://host.lima.internal:8000/ask","password":""}`. Keep credentials private. No application model credentials are forwarded to Airflow.

Trigger `text2sql_evaluation` with the IDs recorded in `outputs/dataset-import.json`:

```json
{"dataset_id":"DATASET_ID","dataset_version_id":"VERSION_ID"}
```

This processes every row in stable example-ID order. Add `"max_examples": 12` for a small initial check. The workflow supports up to 1024 selected rows per run (the default Airflow mapping limit), with at most two tasks active. Larger datasets require an explicit sample. Each HTTP request has a 60-second timeout and sends only `question`, `narrate: false`, and `verbose: false`. The adapter saves `generated_sql`, measured latency, and the actual `X-Trace-ID` when present; returned rows and narration are not needed for SQL judging. The API does not report a source revision, so it remains unknown.

The rubric/model snapshot is saved before requests begin. Each mapped `run_experiment` task persists its result to Phoenix; the Evaluation group then compares its SQL with the pinned golden SQL using the existing LLM judge. Persisted successes and failures are preserved on task retries. A crash after HTTP execution but before Phoenix persistence may repeat a call: the API does not implement idempotency. A new DAG run with dataset IDs creates a new experiment and calls the API again. Incomplete runs still produce reports and fail the final completeness check.

For evaluation only, supply the existing Phoenix output experiment ID (from `prepare_run` XCom or Phoenix):

```json
{"experiment_id":"OUTPUT_EXPERIMENT_ID"}
```

With `experiment_id`, the Experiment stage is skipped and the DAG fetches the pinned golden dataset and saved candidate outputs, maps judge/persistence tasks, and generates a report without API calls. Leave the optional `experiment_id` field empty (JSON `null`) for new experiments. Do not combine an existing experiment ID with dataset selection parameters. On the first evaluation it snapshots the current Airflow rubric/model Variables. Retries recover that snapshot. Later runs reuse the sole saved configuration; supply `evaluation_config_id` when multiple configurations exist.

To deliberately evaluate with updated Airflow settings:

```json
{"experiment_id":"OUTPUT_EXPERIMENT_ID","new_evaluation_config":true}
```

Configuration hashes include rubric, model, context, and schema/evaluator versions. Prior annotations remain under their hash-qualified names. Incorrect SQL is a recorded outcome, not a task failure. Missing outputs or judgments, application errors, and evaluator errors leave the report incomplete and fail the final completeness task.

Each evaluation-only run creates an immutable manifest-only ledger experiment linking to the original output experiment because the pinned client has no public experiment-metadata update method. Judgments are written to exact original experiment-run IDs. Ledger experiments are bookkeeping, not application benchmarks. Use the original output experiment ID for reporting and comparisons. A ledger is recovered by Airflow run identity on retry.

Export durable report inputs from Phoenix on your laptop:

```sh
PHOENIX_BASE_URL=http://localhost:6006 uv run --locked python scripts/export_report.py --experiment-id ORIGINAL_EXPERIMENT_ID \
  --evaluation-config-id CONFIG_HASH --output-dir outputs/baseline
```

Outputs are `report.html`, `summary.json`, and `failures.json`. No shared worker filesystem is required. The DAG renders and logs aggregate counts; the exporter writes downloadable files. Reports show coverage, denominator, status, SQL pairs, real trace IDs, and provenance. No speculative Phoenix deep links or model costs are invented. Holdout rows remain in reports but are excluded from repair packets.

Use your existing Phoenix troubleshooting skill to inspect a failure's actual trace, propose a focused application fix, and review it outside Airflow. Do not alter reference SQL, scoring, or the rubric merely to improve results. Run the repaired application separately with a new host run ID and the same dataset, then trigger its evaluation with the same judge configuration and include `baseline_experiment_id` plus `baseline_evaluation_config_id` if needed. Exports also accept `--baseline-experiment-id` and `--baseline-evaluation-config-id`. Incompatible configurations are labeled; uncertain/missing/error pairs have no quality delta.

## Remote application routing and tracing

A remote application requires an existing private route or **authenticated HTTPS** endpoint to reach local Phoenix. Never publish this development Compose instance unauthenticated. Configure supported authentication before shared/remote use; provision no tunnel or paid infrastructure automatically. The saved-output preflight checks Phoenix and judge configuration; it does not provision or verify a remote route.

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
