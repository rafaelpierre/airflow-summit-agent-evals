# Text2SQL evaluation MVP specification

## Current scope

The workshop separates application execution from evaluation:

1. Run the existing `agentic-text2sql` application through a host-side CLI.
2. Save its candidate SQL, actual trace IDs, and errors as Phoenix experiment runs.
3. Trigger one local Airflow DAG with the saved output experiment ID.
4. Airflow fetches the pinned golden dataset and existing outputs, runs mapped LLM judgments, persists annotations, and reports completeness.
5. Codex assists diagnosis and repair outside the DAG. Run the repaired application separately, then evaluate its saved candidate outputs under compatible conditions.

Airflow must not call a REST endpoint, spawn the application CLI, deploy the application, or generate missing candidate outputs. Application traces alone are not experiment outputs. No REST server is required. This scope supersedes the earlier application-execution DAG design.

## Runtime and source repositories

Preserve the existing project, source, and configuration. Keep the independently cloned application at `apps/agentic-text2sql`, excluded from parent Git tracking and the Airflow build context. Its own repository owns application repairs. The parent owns the tracked CLI adapter in `workshop_agent/` and the evaluation workflow.

Use uv with locked environments. Airflow uses Apache Airflow 3.3.2 / Python 3.13 / Common AI 1.0.0. The application has a separate uv lock because its SQLAlchemy 2 dependency conflicts with Airflow's SQLAlchemy 1.4 constraint. Do not install the application into Airflow.

Run local Airflow with Docker Compose, LocalExecutor, and its PostgreSQL metadata database. Colima supplies the macOS engine. Maintain a separate, pinned Phoenix OSS Compose service using SQLite in a persistent named volume at `PHOENIX_WORKING_DIR`. Keep Phoenix persistence independent of Airflow. Do not add PostgreSQL to Phoenix, share its database file, provision paid infrastructure, add a custom UI, or implement autonomous repair.

## Application execution and tracing

The host wrapper imports the existing pipeline, disables answer narration for SQL evaluation, and emits a validated JSON result. It sends only the question and stable request ID to the application. Never send reference SQL or golden answers. Capture the actual source/runtime fingerprint rather than inventing a revision. Run only a small selected sample by default.

Enable automatic Pydantic AI tracing with OpenInference and the OTLP HTTP exporter. Preserve existing application instrumentation and troubleshooting skills. Send traces to the same Phoenix instance used for datasets/evaluations. Return the actual root trace ID; flush spans before the short-lived CLI exits. Test instrumentation with explicit test models, and label this separately from real model verification.

The host runner saves a durable manifest before execution, with dataset/version, selected example IDs in stable order, and application revision. Save each output/error by explicit Phoenix example and experiment-run IDs. Bound execution time and kill timed-out subprocess groups. Keep credentials out of child arguments, logs, XCom, and output artifacts. Reuse a run identity to resume only unsuccessful/missing outputs with unchanged inputs. A crash between execution and persistence can repeat a model call; do not claim exactly-once execution.

Initialize the demo database explicitly, once; retain it across comparisons. Never silently reseed or overwrite a partial/existing database. Golden reference SQL comes from the application's existing examples, not newly invented answers. Preserve holdout split metadata where configured.

## Phoenix connectivity and persistence

Bind Phoenix UI/API to `127.0.0.1:6006` by default. Airflow uses `http://phoenix:6006` on the shared `text2sql-evaluation` Docker network. The host application uses the host-reachable OTLP endpoint, normally `http://localhost:6006/v1/traces`.

Remote applications need an explicitly configured private route or authenticated HTTPS proxy/tunnel; laptop localhost and Docker DNS do not work remotely. Never expose unauthenticated Phoenix publicly. Keep normal shutdown non-destructive; preserve named volumes. Document stopped-service backup/restore. Verify client/server compatibility and persistence across container recreation.

Import golden data if absent, and record local dataset/version IDs. Old IDs and traces do not automatically migrate. Importing an existing named dataset must not silently replace its content.

## Evaluation input contract

The DAG takes:

- `experiment_id`: required ID of an existing output experiment, not an evaluation ledger.
- `evaluation_config_id`: optional saved configuration selector.
- `new_evaluation_config`: explicit request to snapshot current Airflow settings.
- `baseline_experiment_id` and `baseline_evaluation_config_id`: optional comparison selectors.

Reject application execution/selection parameters in this DAG. Infer dataset/version and selected identities from the saved experiment. Fetch the exact pinned golden dataset, normalize and validate the selected examples, and confirm saved context matches. Do not join on question text or position.

Golden examples contain `example_id`, `question`, `reference_sql`, `schema_context`, `sql_dialect`, optional `business_rules`, and optional `split`. The default Phoenix paths are `input.question`, `output.sql`, and metadata fields for context/dialect/rules/split.

Candidate outputs may be SQL strings or objects with `sql`, optional actual `trace_id`, `latency_ms`, and `app_revision`. Missing/malformed outputs and application failures remain distinct from incorrect SQL and evaluator failures. Full-dataset native Phoenix experiments work directly. Subset experiments require explicit `selected_example_ids` metadata or the host runner's durable manifest so missing outputs cannot disappear. Support one repetition; reject ambiguous duplicate identities and unsupported repetitions.

## Airflow configuration and secrets

Read Variables and make network calls only inside tasks, never at DAG parse time. Read the explicit model identifier through Airflow Variable `text2sql_judge_model`. Read rubric/version/temperature from JSON Variable `text2sql_judge_config`. Store model credentials in Airflow Connection `judge` (`pydanticai`) or a supported secrets backend, never in rubric Variables.

Environment-backed Airflow secrets (`AIRFLOW_VAR_TEXT2SQL_JUDGE_MODEL`, `AIRFLOW_CONN_JUDGE`) are optional. Do not forward empty values that mask UI/backend configuration. Do not read a standalone `JUDGE_MODEL` environment variable from the DAG. Forward only required evaluation secrets into Airflow; keep application Modal credentials in the separate gitignored `.env.agent`.

Resolve the model and rubric once for a new evaluation configuration, validate supported settings, and snapshot the complete effective configuration, canonical SHA-256 hash, model identifier, context, and schema/evaluator versions. Recover that snapshot on retry without rereading current Variables. Reuse a unique saved configuration by default; require an explicit selector if ambiguous. Deliberate changes create a distinct configuration and preserve prior annotations. Temperature zero does not guarantee deterministic judging.

The current judge uses the OpenAI provider. Reject unexpected returned model identifiers; do not silently combine model aliases/fallbacks. Do not fabricate costs, scores, or successful checks.

## DAG and persistence

Flow:

```text
prepare_run -> prepare_judge_inputs -> [judge_sql -> persist_evaluation] mapped
                                   -> consolidate -> check_completeness
```

Use `schedule=None`, `catchup=False`, one active DAG run, and bounded task concurrency (2). Preparation creates or recovers an immutable evaluation ledger linking the output experiment; the pinned client has no public experiment metadata-update API. Keep compact identifiers in XCom; durable data lives in Phoenix.

Prefer the mapped Common AI `LLMOperator`; document a Python-task fallback only if compatibility requires it. Carry explicit experiment-run IDs outside model-generated output. Treat SQL/comments/example content as untrusted data, not judge instructions. Supply both SQL queries, question, schema, dialect, and business rules from the frozen context.

Validate structured judgments with verdict `correct`, `incorrect`, or `uncertain`; failure category; explanation; and suggested check. Derive scores in code: 1, 0, and no score respectively. Retry only bounded transient/validation errors, never incorrect answers until they pass. Pair judgment and persistence per example so successful judgments survive unrelated failures. Upsert under stable configuration-qualified annotation names and preserve prior configurations.

If preparation succeeds, consolidate despite downstream failures. Read persisted results instead of relying on complete mapped XCom collections. Preserve incomplete status even when report generation succeeds; the final completeness task fails for missing runs, missing evaluations, and evaluator/application errors.

## Reporting and repair

Generate self-contained autoescaped HTML, deterministic JSON summaries, and repair packets without model calls. Report expected/completed/judged counts, incorrect/uncertain/error categories, coverage, pass-rate denominators, SQL pairs, run IDs, actual trace IDs, and complete provenance. Use IDs rather than fabricated deep links. Exclude holdout rows from repair packets while retaining authorized report visibility.

Export from Phoenix on the host; never assume workers share or preserve local report files. Compare baselines only under matching dataset/version/context/judge/selected-example/repetition identities. Mark incompatible comparisons explicitly. Repairs must not alter golden answers, scoring, or rubrics merely to improve results.

## Validation and delivery

Use `make setup`, `make test`, `make up`, and `make parse` for the evaluation stack. Use `make agent-setup`, `make agent-check`, and `make agent-test` separately on the host. Keep README commands accurate.

Test pinned-dataset reads, saved-output normalization, configuration snapshots/retries, explicit run-ID association, zero application execution from the DAG, partial reports, baseline compatibility, HTML escaping, and OpenInference span conversion. Live checks require configured services. Use explicit test doubles; never silently substitute them in production. Distinguish offline, local synthetic, and real model verification. Finish with implemented changes, validation results, and missing configuration.
