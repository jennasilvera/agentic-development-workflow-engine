FROM python:3.12-slim

ARG UV_VERSION=0.12.19
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv==${UV_VERSION} && \
    useradd --uid 10001 --create-home --shell /usr/sbin/nologin adwe

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "adwe.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
