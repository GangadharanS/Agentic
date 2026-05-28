FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal — google-generativeai + aiohttp are pure-python wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
COPY ReAct/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy ReAct/ as the app and bundle mcp_client.py next to it
# so mcp_bridge.py can resolve `../mcp_client_app/mcp_client.py`.
COPY ReAct/ /app/ReAct/
COPY mcp_client_app/mcp_client.py /app/mcp_client_app/mcp_client.py

WORKDIR /app/ReAct

EXPOSE 8090

# Azure App Service / Container Apps inject WEBSITES_PORT or PORT — fall back to 8090.
CMD ["sh", "-c", "uvicorn backend:app --host 0.0.0.0 --port ${PORT:-${WEBSITES_PORT:-8090}}"]
