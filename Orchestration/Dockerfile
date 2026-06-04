FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Orchestration deps + ReAct deps (reviewer reuses ReAct/PRReviewAgent).
COPY Orchestration/requirements.txt /app/orch-requirements.txt
COPY ReAct/requirements.txt /app/react-requirements.txt
RUN pip install -r /app/orch-requirements.txt -r /app/react-requirements.txt

COPY Orchestration/ /app/Orchestration/
COPY ReAct/ /app/ReAct/
COPY mcp_client_app/mcp_client.py /app/mcp_client_app/mcp_client.py

# Persist SQLite checkpoints across restarts when a volume is mounted at /data.
RUN mkdir -p /data
ENV ORCH_CHECKPOINT_DB=/data/.orchestration_state.db

WORKDIR /app/Orchestration

EXPOSE 8091

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-${WEBSITES_PORT:-8091}}"]
