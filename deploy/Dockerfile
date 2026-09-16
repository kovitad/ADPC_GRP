FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 grp \
    && useradd --system --uid 10001 --gid grp --home-dir /nonexistent grp

WORKDIR /app
COPY pyproject.toml README.md ./
COPY api ./api
COPY core ./core
COPY worker ./worker
COPY migrations ./migrations
COPY alembic.ini ./

RUN python -m pip install --no-cache-dir ".[gis]"

USER 10001:10001
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
