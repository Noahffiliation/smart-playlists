FROM python:3.14.7-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r appuser && \
    useradd -r -g appuser -u 1000 appuser

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-build --no-dev --no-install-project && \
    rm -f /bin/uv /bin/uvx && \
    pip uninstall -y pip setuptools wheel

COPY smart_playlists.py new_releases.py ./
COPY utils ./utils

RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "smart_playlists.py"]
