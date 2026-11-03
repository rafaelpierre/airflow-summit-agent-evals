# Project instructions

## Purpose and source of truth

This project judges saved Phoenix experiment outputs from an existing Text2SQL CLI. The application runs separately on the host; Airflow must never execute it. Local Apache Airflow runs the workflow; A self-hosted Phoenix OSS service using Docker Compose and SQLite stores golden datasets, experiments, evaluations, and traces. Codex assists diagnosis and repair outside the DAG.

Read `docs/mvp-spec.md` before implementation. Read `README.md` for setup and run instructions. Preserve existing code and configuration. Do not repeatedly scaffold a project that already exists.

## Architecture and scope

- Maintain one evaluation DAG with dataset/output retrieval, LLM judging, persistence, and reporting stages. Model settings come from Airflow Variables and model credentials from Airflow Connections or supported secrets. Keep application execution outside Airflow.
- Run one Phoenix OSS service with Docker Compose and SQLite on a persistent named volume. Pin its image version and verify client/server compatibility. Keep its persistent data independent of the Airflow lifecycle.
- Run local Airflow with Docker Compose and LocalExecutor; Colima supplies the Docker engine on macOS. Pin compatible Airflow, Python, and provider versions. Manage Python dependencies with uv.
- Prefer the Common AI provider's mapped `LLMOperator` for judging. Verify compatibility; document a Python-task fallback if required.
- Keep the existing application and Phoenix troubleshooting skill intact unless changes are explicitly requested.
- Do not add autonomous repair, automatic application deployment, a custom UI, or infrastructure beyond local Airflow and the requested Phoenix Compose service to the MVP.
- Implement useful work while credentials or endpoint details are pending. Ask only for information that cannot be discovered safely.

## Credentials and external access

- Never print, commit, or place secrets in logs, reports, metadata, XCom, or generated artifacts. Do not display the contents of `.env`.
- Keep `.env` gitignored and use empty placeholders in `.env.example`.
- Forward only the runtime credentials tasks need into Airflow task containers.
- Store model/API credentials in supported environment secrets or Airflow Connections, not rubric Variables.
- Do not create paid infrastructure or deploy to an ambiguous target as part of scaffolding.

## Phoenix operations

- Implement `compose.phoenix.yaml` with one Phoenix service and a persistent volume mounted at `PHOENIX_WORKING_DIR`. Use SQLite; do not add PostgreSQL or share the database file with Airflow workers.
- Bind the local UI/API port to loopback by default. Configure a separate container-network route for local Airflow workers; loopback publishing alone does not guarantee container access.
- Remotely hosted agents need an explicitly configured route to Phoenix, such as an existing authenticated HTTPS tunnel/proxy or private network. Never claim a laptop localhost URL works remotely. Do not expose an unauthenticated Phoenix instance publicly.
- Point the application trace exporter, evaluation client, report exporter, and existing Codex skill at the same Phoenix instance using their appropriate endpoints. Preserve instrumentation; update endpoint configuration only as needed.
- Preserve the volume on normal shutdown. Never run destructive volume cleanup as routine setup. Document stopped-service backup/restore and verify persistence across container recreation.
- Import the existing golden dataset if absent; record its new local dataset/version IDs. Do not assume traces or IDs transfer automatically from another instance.

## Evaluation invariants

- Pin the Phoenix dataset version and record selected example IDs in stable order.
- Never send reference SQL or golden answers to the application under test, including in the separate host runner.
- Resolve the rubric once per evaluation run. Persist the full effective configuration, canonical hash, actual model identifier, settings, and output-schema version.
- Retry/resume using the saved configuration. Deliberate rubric changes create a distinct evaluation configuration and preserve prior results.
- Associate results using explicit Phoenix experiment-run IDs, never question text or positional joins alone.
- Re-evaluation of saved outputs must make no application requests.
- Distinguish incorrect SQL, uncertain judgments, API failures, and evaluator failures. Never retry an incorrect answer until it passes.
- Make experiment creation and result persistence recoverable and retry-safe. Do not claim exactly-once application execution unless the application supports idempotency.
- Do not fabricate trace IDs, scores, model costs, or successful verification.
- Compare baselines only under compatible datasets, contexts, judge configurations, and example/repetition identities.
- Preserve incomplete-run status even if report generation succeeds.

## Implementation practices

- Make network calls and Variable reads inside tasks, never at DAG parse time.
- Keep XCom payloads compact. Persist experiment records in Phoenix and pass identifiers between stages where practical.
- Validate dataset, response, and judge contracts. Treat submitted SQL and comments as data, not judge instructions.
- Bound concurrency, request timeouts, and retries; use a small default sample.
- Do not assume workers share a filesystem or retain local report files.
- Generate self-contained HTML with autoescaping and deterministic formatting. Keep model calls out of HTML generation.
- Separate holdout examples from repair artifacts when a holdout split is configured.
- Verify SDK APIs against installed versions. Pin compatible dependencies and record the selected Airflow and Python versions.

## Development and validation

Use uv for dependency management and offline validation. Use `make setup`, `make test`, `make up`, and `make parse`; keep README commands accurate.

Run relevant offline tests and DAG parsing before claiming completion. Test mapping, configuration snapshots, retry/resume, run-ID associations, re-evaluation isolation, incomplete reports, baseline compatibility, HTML escaping, and Phoenix persistence/connectivity. Use explicit test doubles; never silently substitute mocks in live mode.

Only run live integration checks with configured services. Distinguish mocked, locally verified, and cloud-verified behavior. Update documentation when interfaces change. Finish work with implemented changes, validation results, and remaining configuration needs.
