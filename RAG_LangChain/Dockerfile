# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# build-essential is kept because some wheels (e.g., chromadb's onnxruntime
# subdeps on certain arches) may need a compiler. It is also required if
# sentence-transformers is lazy-installed at runtime in local mode.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Base requirements only. torch + sentence-transformers are deliberately NOT
# installed here — they are lazily installed at first use when
# EMBEDDING_PROVIDER=local. See app/langchain_components.py and
# requirements-local.txt for details. This keeps the image ~600 MB smaller
# and the first build ~4 min faster for cloud-mode users.
COPY requirements.txt requirements-local.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /app/data

EXPOSE 8086

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086"]
