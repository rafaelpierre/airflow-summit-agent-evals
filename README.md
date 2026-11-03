# Text2SQL evaluation flywheel

A small Airflow workflow for evaluating a Text2SQL agent, inspecting failures in Phoenix, and verifying an application improvement with Codex.

**Status:** This package contains implementation instructions, not a working application yet. The DAG, scripts, tests, and commands referencing project files below are implementation targets. Codex should build them from `docs/mvp-spec.md` and update this README with verified commands and versions.

## Files

- `AGENTS.md`: lasting instructions for Codex and other coding agents.
- `docs/mvp-spec.md`: implementation scope, contracts, task behavior, and acceptance criteria.
- `README.md`: intended setup, operation, and demo workflow.

Place these files in the target repository with this directory structure preserved. Ask Codex: “Read AGENTS.md and implement docs/mvp-spec.md. Build and test the scaffold, preserving existing work.”

## Architecture

```text
Phoenix OSS (Docker Compose + SQLite) versioned dataset
  -> Astro/Airflow calls agent REST API
  -> Phoenix experiment stores outputs and trace references
  -> Airflow LLM judge evaluates SQL
  -> Phoenix stores evaluations
  -> HTML report + failure packet
  -> Developer and Codex inspect traces and improve the application
  -> Evaluate the candidate against the same benchmark
```

The self-hosted Phoenix service owns experiment records and traces in a persistent SQLite volume. Airflow coordinates execution and evaluation. The application owns the agent. Codex assists repair outside the DAG.

## Prerequisites

- Docker Engine/Desktop with Docker Compose v2 for the Phoenix OSS service.
- Existing golden dataset to import or reuse in the self-hosted instance.
- A reachable Phoenix endpoint and configured authentication for remote access.
- Existing agent API and its request/response contract.
- Astronomer workspace and an identified Astro Deployment.
- Existing local `.env` with `ASTRO_API_TOKEN` for workspace access.
- Judge-model credentials and selected model.
- Astro CLI and a supported container engine for local development.

Phoenix OSS runs on your own compute; model inference and Astro compute may incur charges. Keep demo volume and concurrency small.

## Credentials

The local `.env` already stores `ASTRO_API_TOKEN`. Codex should use it for supported Astro CLI/API authentication without printing it or asking you to paste it into chat.

Keep `.env` outside version control. Generate `.env.example` with empty placeholders. Keep workspace-management credentials separate from runtime credentials; do not forward `ASTRO_API_TOKEN` to task containers by default.

The implementation will document exact supported configuration names for the self-hosted Phoenix endpoint/authentication, agent endpoint/authentication, and judge connection. The default host-browser address is `http://localhost:6006`. Configure a different reachable address for containers or cloud workers. Do not substitute a guessed trace URL or browser URL. An isolated loopback-only instance may run without authentication; configure supported Phoenix authentication/API keys for shared or remote access.

Store secrets in supported environment secrets or Airflow Connections. The rubric Variable contains no secrets.

## Phoenix OSS setup

The implementation must create `compose.phoenix.yaml` with one pinned `arizephoenix/phoenix` service, SQLite, and a persistent named volume mounted at `/mnt/phoenix` with `PHOENIX_WORKING_DIR=/mnt/phoenix`. It must not add PostgreSQL. The container receives explicit Phoenix settings only, not every variable from `.env`.

Planned commands after the Compose file is implemented:

```sh
docker compose -f compose.phoenix.yaml up -d
docker compose -f compose.phoenix.yaml ps
docker compose -f compose.phoenix.yaml logs --tail=50 phoenix
```

Open `http://localhost:6006` on the host. The local published port should bind to loopback by default. Import or reuse the golden dataset and record its dataset/version IDs. Configure the application trace exporter and existing Codex Phoenix skill to use this same instance. Data and IDs from another instance do not transfer automatically.

For normal shutdown:

```sh
docker compose -f compose.phoenix.yaml down
```

Do not add `-v`: that removes the named volume and its persisted data. For backup, stop Phoenix and archive the complete named volume before restarting it. The implementation must document verified backup/restore commands and test that records survive container recreation. Back up before upgrading the pinned Phoenix image.

## Local and Astro cloud setup

1. Initialize an Astro project in an empty target directory with `astro dev init`, or reuse the existing project. Do not overwrite an existing project blindly.
2. Inspect the generated Runtime image and select compatible dependencies.
3. Start the Phoenix Compose service, verify its persistence, and configure its endpoint, the agent API, and the judge connection.
4. Import the `text2sql_judge_config` Variable example supplied by the implementation.
5. Run offline tests and DAG parsing. Expected Astro commands are `astro dev pytest` and `astro dev parse`; verify them against the installed CLI.
6. Start local Airflow with `astro dev start`.
7. Run preflight checks before a live experiment.
8. For cloud execution, configure runtime secrets in the selected Astro Deployment. Use an explicit Deployment ID when deploying; the implementation must provide the verified command for the installed CLI.

**Networking:** Both the application API and Phoenix must be reachable from their callers.

| Caller | Phoenix address/routing |
| --- | --- |
| Host browser, report exporter, or Codex | `http://localhost:6006` when Phoenix runs on that host |
| Local Astro worker | `http://phoenix:6006` on an explicitly shared Docker network; otherwise a verified host-gateway route |
| Astro cloud worker or remote application | Configured reachable endpoint through an existing private route or authenticated HTTPS tunnel/proxy |

A shared network is not automatic across Compose projects. The implementation must document and verify it. Host-gateway routing is platform-dependent, and loopback-only publishing may not be reachable through it.

An Astro cloud worker cannot reach your laptop through `localhost`, `phoenix` Docker DNS, or `host.docker.internal`. Configure remote routing and Phoenix authentication before claiming cloud readiness. Do not expose an unauthenticated Phoenix instance publicly. The application trace exporter needs its own reachable collector endpoint, using the pinned version's verified OTLP HTTP configuration.

You can complete the local demo with Astro CLI and Phoenix Compose while the cloud route is pending; keep that status explicit.

Do not rely on local worker report files surviving or being shared across tasks.

## Rubric configuration

Create an Airflow Variable named `text2sql_judge_config` using the JSON example in the specification. It contains rubric text, a version label, and model settings such as temperature.

At run start, the DAG snapshots the rubric, effective settings, context, and actual model identifier. It hashes that configuration and saves it with the experiment. All judge instances use the same snapshot.

Editing a Variable must not change an in-progress evaluation. A deliberate re-evaluation with a new rubric preserves earlier judgments under a new configuration identifier. Keep judge settings fixed when measuring application improvements.

## Run a new experiment

Trigger `text2sql_evaluation` with parameters shaped like:

```json
{
  "mode": "new_experiment",
  "dataset_version_id": "REPLACE_WITH_PHOENIX_VERSION_ID",
  "app_revision": "baseline-revision",
  "max_examples": 12
}
```

The DAG validates the selected dataset, calls the API with questions only, persists outputs, judges valid responses, and generates reports. Reference SQL is never sent to the agent.

Judgments are `correct`, `incorrect`, or `uncertain`. Scores are 1, 0, or absent respectively. API errors and evaluator errors appear separately. The report shows coverage alongside its score denominator.

## Re-evaluate saved responses

Trigger with:

```json
{
  "mode": "evaluate_existing",
  "experiment_id": "REPLACE_WITH_EXPERIMENT_ID"
}
```

This mode reads saved outputs and makes no application requests. The implementation must document how to select a previous evaluation configuration or deliberately create one from the current rubric.

## Export reports

The planned command is:

```sh
python scripts/export_report.py --experiment-id EXPERIMENT_ID --output-dir outputs/EXPERIMENT_ID
```

It connects to self-hosted Phoenix using the configured authentication, retrieves saved records, and uses the same renderer as the DAG to create:

- `report.html`: human-readable overview and example details.
- `summary.json`: structured metrics and provenance.
- `failures.json`: repair packet with trace references.

When multiple evaluation configurations exist, select one explicitly. Optional baseline comparison must use compatible dataset/context/judge conditions. Exact selector flags will be documented after implementation.

An existing object-storage destination can be supported for durable cloud artifacts. The MVP does not require provisioning one.

## Conference demo

1. Run a small baseline experiment against a pinned dataset.
2. Open a failed SQL example and its judge explanation.
3. Use the Phoenix trace ID with the existing Codex skill.
4. Review a focused application patch.
5. Run the candidate with the same dataset, context, and judge configuration, supplying the baseline experiment ID.
6. Show improved and regressed examples in Phoenix and the HTML report.

Suggested Codex repair prompt:

> Read failures.json. Use my existing Phoenix skill to inspect the linked traces and identify the earliest step responsible for incorrect SQL. Propose the smallest general application fix. Do not change golden answers, evaluation data, the rubric, or scoring. Explain likely regression risks. After review, evaluate the candidate under the same conditions and summarize improvements and regressions.

Keep holdout examples outside the repair packet when configured. Prepare recorded results as a clearly labeled fallback for network/provider interruptions.

## Validation and limitations

Verify Phoenix records survive container recreation with the volume retained, and test connectivity from actual worker/application environments. Offline tests must cover contracts, association IDs, snapshots, resumption, re-evaluation isolation, incomplete reports, compatible baseline comparisons, and HTML escaping. Live validation requires configured credentials and services; mocks must be explicitly labeled.

An LLM judge is an assessment, not a proof of SQL equivalence. Calibrate against manually labeled valid and invalid SQL pairs. An incorrect answer is an evaluation result, while missing work or failed judging makes the workflow incomplete.

Without application idempotency support, an HTTP call can repeat after a crash between response receipt and persistence. Do not claim exactly-once execution.

## Official references

- [Astro CLI project workflow](https://github.com/astronomer/astro-cli)
- [Phoenix experiment client](https://arize-phoenix.readthedocs.io/projects/client/api/experiments.html)
- [Phoenix self-hosting and SQLite storage](https://arize.com/docs/phoenix/self-hosting/deploying-phoenix)
- [Phoenix authentication](https://arize.com/docs/phoenix/deployment/authentication)
- [Airflow Variables](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/variables.html)
- [Airflow Common AI LLM operator](https://airflow.apache.org/docs/apache-airflow-providers-common-ai/stable/operators/llm.html)

Verify exact APIs and supported features against the installed versions during implementation.
