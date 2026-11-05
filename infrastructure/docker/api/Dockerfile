# FastAPI backend. Build from the repo root:
#   docker build -f infrastructure/docker/api/Dockerfile -t sei-api .
FROM python:3.11-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Runtime groups only: API + model loading (mlflow/sklearn/xgboost). No dev, dbt, dl, notebooks.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --group backend --group ml

FROM python:3.11-slim-bookworm AS runtime
# libgomp: OpenMP runtime needed by xgboost/scikit-learn wheels.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root backend ./backend
COPY --chown=root:root ml ./ml
COPY --chown=root:root config ./config
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
