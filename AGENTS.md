# Project instructions

## Purpose and source of truth

This project evaluates an existing Text2SQL agent through its REST API. Astro runs the Airflow workflow; A self-hosted Phoenix OSS service using Docker Compose and SQLite stores golden datasets, experiments, evaluations, and traces. Codex assists diagnosis and repair outside the DAG.

Read `docs/mvp-spec.md` before implementation. Read `README.md` for setup and run instructions. Preserve existing code and configuration. Do not repeatedly scaffold a project that already exists.

## Architecture and scope

- Maintain one evaluation DAG with separate application execution, LLM judging, persistence, and reporting stages.
- Run one Phoenix OSS service with Docker Compose and SQLite on a persistent named volume. Pin its image version and verify client/server compatibility. Keep its Compose project separate from Astro.
- Reuse the Astro project and target Runtime. Never independently upgrade Airflow inside an Astro Runtime image.
- Prefer the Common AI provider's mapped `LLMOperator` for judging. Verify compatibility; document a Python-task fallback if required.
- Keep the existing application and Phoenix troubleshooting skill intact unless changes are explicitly requested.
- Do not add autonomous repair, automatic application deployment, a custom UI, or infrastructure beyond the requested Phoenix Compose service to the MVP.
- Implement useful work while credentials or endpoint details are pending. Ask only for information that cannot be discovered safely.

## Credentials and external access

- The existing local `.env` contains `ASTRO_API_TOKEN`, granting access to the user's Astronomer workspace. Use it for supported Astro CLI/API authentication. Do not ask the user to paste it into chat.
- Never print, commit, or place secrets in logs, reports, metadata, XCom, or generated artifacts. Do not display the contents of `.env`.
- Keep `.env` gitignored and use empty placeholders in `.env.example`.
- Do not automatically forward the workspace-management token into Airflow task containers. Forward only the runtime credentials tasks need.
- Store model/API credentials in supported environment secrets or Airflow Connections, not rubric Variables.
- Discover workspace and Deployment details where possible. Confirm the target if multiple Deployments are plausible before modifying one.
- Do not create paid infrastructure or deploy to an ambiguous target as part of scaffolding.

## Phoenix operations

- Implement `compose.phoenix.yaml` with one Phoenix service and a persistent volume mounted at `PHOENIX_WORKING_DIR`. Use SQLite; do not add PostgreSQL or share the database file with Airflow workers.
- Bind the local UI/API port to loopback by default. Configure a separate container-network route for local Astro workers; loopback publishing alone does not guarantee container access.
- Astro cloud workers and remotely hosted agents need an explicitly configured route to Phoenix, such as an existing authenticated HTTPS tunnel/proxy or private network. Never claim a laptop localhost URL works remotely. Do not expose an unauthenticated Phoenix instance publicly.
- Point the application trace exporter, evaluation client, report exporter, and existing Codex skill at the same Phoenix instance using their appropriate endpoints. Preserve instrumentation; update endpoint configuration only as needed.
- Preserve the volume on normal shutdown. Never run destructive volume cleanup as routine setup. Document stopped-service backup/restore and verify persistence across container recreation.
- Import the existing golden dataset if absent; record its new local dataset/version IDs. Do not assume traces or IDs transfer automatically from another instance.

## Evaluation invariants

- Pin the Phoenix dataset version and record selected example IDs in stable order.
- Never send reference SQL or golden answers to the application under test.
- Resolve the rubric once per evaluation run. Persist the full effective configuration, canonical hash, actual model identifier, settings, and output-schema version.
- Retry/resume using the saved configuration. Deliberate rubric changes create a distinct evaluation configuration and preserve prior results.
- Associate results using explicit Phoenix experiment-run IDs, never question text or positional joins alone.
- Re-evaluation of saved outputs must make no application requests.
- Distinguish incorrect SQL, uncertain judgments, API failures, and evaluator failures. Never retry an incorrect answer until it passes.
- Make experiment creation and result persistence recoverable and retry-safe. Do not claim exactly-once HTTP execution unless the application supports idempotency.
- Do not fabricate trace IDs, scores, model costs, or successful verification.
- Compare baselines only under compatible datasets, contexts, judge configurations, and example/repetition identities.
- Preserve incomplete-run status even if report generation succeeds.

## Implementation practices

- Make network calls and Variable reads inside tasks, never at DAG parse time.
- Keep XCom payloads compact. Persist experiment records in Phoenix and pass identifiers between stages where practical.
- Validate dataset, response, and judge contracts. Treat submitted SQL and comments as data, not judge instructions.
- Bound concurrency, request timeouts, and retries; use a small default sample.
- Do not assume cloud workers share a filesystem or retain local report files.
- Generate self-contained HTML with autoescaping and deterministic formatting. Keep model calls out of HTML generation.
- Separate holdout examples from repair artifacts when a holdout split is configured.
- Verify SDK APIs against installed versions. Pin compatible dependencies and record the selected Runtime.

## Development and validation

Use the existing Astro CLI workflow. Once scaffolded, expected commands are `astro dev parse`, `astro dev pytest`, and `astro dev start`; verify availability with the installed CLI and keep README commands accurate.

Run relevant offline tests and DAG parsing before claiming completion. Test mapping, configuration snapshots, retry/resume, run-ID associations, re-evaluation isolation, incomplete reports, baseline compatibility, HTML escaping, and Phoenix persistence/connectivity. Use explicit test doubles; never silently substitute mocks in live mode.

Only run live integration checks with configured services. Distinguish mocked, locally verified, and cloud-verified behavior. Update documentation when interfaces change. Finish work with implemented changes, validation results, and remaining configuration needs.
