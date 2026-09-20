FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10

RUN groupadd --system --gid 10001 grp \
    && useradd --system --uid 10001 --gid grp --home-dir /nonexistent grp \
    && apt-get update \
    && apt-get install --yes --no-install-recommends gosu libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY api ./api
COPY core ./core
COPY grp ./grp
COPY worker ./worker
COPY migrations ./migrations
COPY alembic.ini ./
COPY deploy/container-entrypoint.sh /usr/local/bin/grp-entrypoint

RUN python -m pip install --no-cache-dir ".[gis]" \
    && chmod 0755 /usr/local/bin/grp-entrypoint

ENTRYPOINT ["/usr/local/bin/grp-entrypoint"]
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
