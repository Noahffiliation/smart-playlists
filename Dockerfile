FROM python:3.14.7-slim-bookworm

RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r appuser && \
    useradd -r -g appuser -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements.txt && \
    pip uninstall -y pip setuptools wheel

COPY smart_playlists.py new_releases.py ./
COPY utils ./utils

RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs

USER appuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "smart_playlists.py"]
