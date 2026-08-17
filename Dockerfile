FROM python:3.12.3-slim-bookworm

RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements.txt

COPY smart_playlists.py new_releases.py ./
COPY utils ./utils

RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs

USER appuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "smart_playlists.py"]
