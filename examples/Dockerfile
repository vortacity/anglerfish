FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

# Auth credentials via environment variables:
#   ANGLERFISH_CLIENT_ID
#   ANGLERFISH_TENANT_ID
#   ANGLERFISH_CLIENT_SECRET  (or certificate vars)

# Volume mounts:
#   /data/records   — deployment record JSON files
#   /data/state     — persistent monitor state + heartbeat
#   /data/logs      — JSONL alert log

VOLUME ["/data/records", "/data/state", "/data/logs"]

ENTRYPOINT ["anglerfish", "monitor", \
    "--records-dir", "/data/records", \
    "--state-file", "/data/state/monitor-state.json", \
    "--alert-log", "/data/logs/alerts.jsonl", \
    "--no-console"]
