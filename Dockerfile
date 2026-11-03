FROM apache/airflow:3.3.2-python3.13
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

# Install the same locked environment as host tests, isolated from image packages.
ENV UV_PROJECT_ENVIRONMENT=/opt/airflow/.venv \
    VIRTUAL_ENV=/opt/airflow/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/airflow/.venv/bin:${PATH}" \
    PYTHONPATH=/opt/airflow
WORKDIR /opt/airflow
COPY --chown=airflow:root pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python
COPY --chown=airflow:root dags ./dags
COPY --chown=airflow:root include ./include
COPY --chown=airflow:root scripts ./scripts
COPY --chown=airflow:root docs/airflow-variables.json ./docs/airflow-variables.json
