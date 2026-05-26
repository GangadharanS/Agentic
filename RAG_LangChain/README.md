# RAG LangChain — Retrieval Augmented Generation

A RAG system built with **FastAPI + LangChain**, using LangChain's native integrations for each layer:

| Layer | LangChain integration | Local option | Cloud option (free tier) |
|-------|----------------------|--------------|---------------------------|
| **Vector DB** | `langchain-chroma` / `langchain-pinecone` | ChromaDB (Docker) | Pinecone |
| **LLM** | `langchain-ollama` / `langchain-groq` / `langchain-google-genai` | Ollama / Mistral (host) | Groq (Llama) or Gemini Flash |
| **Embeddings** | `langchain-huggingface` / `langchain-google-genai` | `all-MiniLM-L6-v2` (384 dim) | `gemini-embedding-001` (3072 dim, truncatable) |
| **RAG chain** | `create_retrieval_chain` + `create_stuff_documents_chain` | — | — |

Runs on **port 8086** (separate from the custom `RAG/` project on 8085).

Two top-level modes via `RAG_MODE`:

| Mode | Vector DB | LLM | Best for |
|------|-----------|-----|----------|
| **local** (default) | ChromaDB (Docker) | Ollama/Mistral (host) | Privacy, offline, no API keys |
| **cloud** (Option A) | Pinecone (free tier) | Groq or Gemini (free tier) | Fast inference, no local GPU/CPU load |

The embedding layer is **independent** of `RAG_MODE` — set `EMBEDDING_PROVIDER=local` or `gemini` separately. You can, for example, run local ChromaDB + Ollama with Gemini cloud embeddings.

> **Image size note:** `torch` + `sentence-transformers` (~600 MB) are **not** baked into the Docker image. They are lazily installed at runtime on the **first request** only if `EMBEDDING_PROVIDER=local`. This means:
> - Cloud-only users get a fast ~1 min image build and a small image.
> - Local-embedding users see a one-time 2–5 min install on their first `/ingest` or `/query`. Subsequent requests are fast.
> - To avoid the runtime install, pre-bake the packages by uncommenting the lines in `requirements-local.txt` and adding them to the `Dockerfile`.

## Architecture

```
/ingest  →  LangChain document loaders + RecursiveCharacterTextSplitter
         →  vectorstore.add_documents()  (Chroma / Pinecone)

/query   →  vectorstore.as_retriever()
         →  create_retrieval_chain(retriever, create_stuff_documents_chain(llm, prompt))
         →  answer + source documents
```

Key files:
- `app/langchain_components.py` — LangChain factories for embeddings, LLM, vector stores
- `app/rag_engine.py` — `create_retrieval_chain` RAG pipeline
- `app/document_loader.py` — LangChain document loaders + text splitter

### Local mode (`RAG_MODE=local`)

- **FastAPI** (port **8086**) — REST API (Docker)
- **ChromaDB** (port **8201**) — vector storage (Docker)
- **Ollama** (port 11434) — LLM on the host (`host.docker.internal`)
- **Embeddings** — `HuggingFaceEmbeddings` or `GoogleGenerativeAIEmbeddings`

### Cloud mode (`RAG_MODE=cloud`)

- **FastAPI** (port **8086**) — REST API (Docker)
- **Pinecone** — managed vector DB via `PineconeVectorStore`
- **Groq** or **Gemini** — cloud LLM via `ChatGroq` / `ChatGoogleGenerativeAI`
- **Embeddings** — `GoogleGenerativeAIEmbeddings` (recommended) or lazy `HuggingFaceEmbeddings`

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Local mode:** [Ollama](https://ollama.com) on your Mac (`brew install ollama`)
- **Cloud mode:** free API keys from [Pinecone](https://app.pinecone.io/) and [Groq](https://console.groq.com/)
- **Gemini embeddings (optional):** free API key from [Google AI Studio](https://aistudio.google.com/apikey)

---

## Setup

```bash
cd RAG_LangChain
cp .env.example .env
# Edit .env — set RAG_MODE and API keys as needed
```

---

## Quick Start — Local mode

### 1. Configure

```bash
# .env
RAG_MODE=local
```

### 2. Start Ollama and pull Mistral

```bash
brew services start ollama
ollama pull mistral
curl http://localhost:11434/api/tags
```

### 3. Start Docker services

```bash
docker-compose up --build -d
```

### 4. Health check

```bash
curl http://localhost:8086/health
```

Expected (service keys reflect the active providers):

```json
{
  "status": "healthy",
  "mode": "local",
  "services": {
    "chromadb": true,
    "ollama": true,
    "sentence_transformers": true
  }
}
```

If `EMBEDDING_PROVIDER=gemini`, the third key becomes `"gemini_embedding": true`.

---

## Quick Start — Cloud mode (Option A)

### 1. Get free API keys

1. **Pinecone:** https://app.pinecone.io/ → create project → copy API key
2. **Groq:** https://console.groq.com/keys → create API key

### 2. Configure `.env`

```bash
RAG_MODE=cloud
PINECONE_API_KEY=your-pinecone-key
GROQ_API_KEY=your-groq-key
GROQ_MODEL=llama-3.1-8b-instant
LLM_PROVIDER=groq
```

Pinecone index `rag-index` is **created automatically** on first ingest, using the dimension that matches your `EMBEDDING_PROVIDER`:

| `EMBEDDING_PROVIDER` | Model | Dimensions |
|----------------------|-------|------------|
| `local` (default) | `all-MiniLM-L6-v2` | **384** |
| `gemini` | `gemini-embedding-001` | **3072** (or 768 / 1536 via `EMBEDDING_DIMENSION`) |

Important: an existing Pinecone index keeps its original dimension. If you switch providers later, delete or recreate the index (see *Switching embedding providers* below).

### 3. Start Docker (Ollama not required)

```bash
docker-compose up --build -d
```

### 4. Health check

```bash
curl http://localhost:8086/health
```

Expected (service keys reflect the active providers):

```json
{
  "status": "healthy",
  "mode": "cloud",
  "services": {
    "pinecone": true,
    "groq": true,
    "sentence_transformers": true
  }
}
```

Keys change with config:

- LLM key: `ollama` / `groq` / `gemini`
- Vector store key: `chromadb` / `pinecone`
- Embedding key: `sentence_transformers` / `gemini_embedding`

### Optional: use Gemini instead of Groq

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.0-flash
```

Get a key: https://aistudio.google.com/apikey

---

## Free cloud embeddings — Gemini `gemini-embedding-001`

Free via Google AI Studio. Works in both `local` and `cloud` modes.

> The previous default `text-embedding-004` was retired by Google on **Jan 14, 2026** and now returns 404. The current GA model is `gemini-embedding-001`. It supports **Matryoshka truncation** — you can request 768 / 1536 / 3072-dim vectors from the same model via `EMBEDDING_DIMENSION` without quality loss at 768.

### 1. Get a free Gemini key

https://aistudio.google.com/apikey

### 2. Configure `.env`

```bash
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
# Blank = auto (3072). Set 768 to stay compatible with an old Pinecone index
# that was created at 768 dim (e.g. previous text-embedding-004 setup).
EMBEDDING_DIMENSION=
```

### 3. Rebuild

```bash
docker-compose up -d --build rag-api
curl http://localhost:8086/health
```

Expected:

```json
{
  "status": "healthy",
  "mode": "cloud",
  "services": {
    "pinecone": true,
    "groq": true,
    "gemini_embedding": true
  }
}
```

### Notes

- Uses Gemini's `RETRIEVAL_DOCUMENT` task type at ingest and `RETRIEVAL_QUERY` at search for best retrieval quality.
- Sends texts in batches of 100 per `:batchEmbedContents` HTTP call.
- The single `GEMINI_API_KEY` covers both the embedding and (if used) the Gemini LLM.
- `gemini-embedding-001` produces **3072-dim** vectors by default. Setting `EMBEDDING_DIMENSION=768` (or 1536) sends `outputDimensionality` to the API, returning a smaller truncated vector — useful for keeping an existing 768-dim Pinecone index. If you change the dimension after data has been ingested, see [Switching embedding providers](#switching-embedding-providers).

---

## API Endpoints

Same endpoints for both modes.

### Ingest a document

```bash
curl -X POST "http://localhost:8085/ingest?collection=my-docs" \
  -F "file=@your-document.pdf"
```

### Ask a question

```bash
curl -X POST http://localhost:8085/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is this document about?", "collection": "my-docs", "top_k": 5}'
```

### List collections

```bash
curl http://localhost:8085/collections
```

In cloud mode, collections map to **Pinecone namespaces**.

### Delete a collection

```bash
curl -X DELETE http://localhost:8085/collections/my-docs
```

Supported file types: PDF, MD, TXT, CSV, Python, Java, JS, TS, Go, SQL, YAML, JSON, XML, HTML, CSS, Shell, Gradle, Properties

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_MODE` | `local` | `local` or `cloud` |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama API (local mode) |
| `OLLAMA_MODEL` | `mistral` | Ollama model name |
| `OLLAMA_TIMEOUT` | `600` | Ollama request timeout (seconds) |
| `PINECONE_API_KEY` | — | Pinecone API key (cloud mode) |
| `PINECONE_INDEX_NAME` | `rag-index` | Pinecone index name |
| `PINECONE_CLOUD` | `aws` | Pinecone cloud provider |
| `PINECONE_REGION` | `us-east-1` | Pinecone region |
| `PINECONE_AUTO_RECREATE_INDEX` | `false` | If `true`, auto-deletes & recreates the index on dim mismatch (data loss) |
| `GROQ_API_KEY` | — | Groq API key (cloud mode) |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model |
| `GEMINI_API_KEY` | — | Gemini API key (optional) |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model |
| `LLM_PROVIDER` | `groq` | `groq` or `gemini` (cloud mode) |
| `EMBEDDING_PROVIDER` | `local` | `local` (sentence-transformers) or `gemini` (cloud) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformers model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Gemini embedding model (text-embedding-004 was retired Jan 2026) |
| `EMBEDDING_DIMENSION` | auto (384 / 768) | Override only if needed; must match Pinecone index |
| `CHUNK_SIZE` | `500` | Document chunk size |
| `CHUNK_OVERLAP` | `50` | Chunk overlap |
| `TOP_K` | `5` | Chunks retrieved per query |

After changing `.env`:

```bash
docker-compose up -d --build rag-api
```

---

## Switching modes

```bash
# Local → Cloud
# Edit .env: RAG_MODE=cloud, add PINECONE_API_KEY + GROQ_API_KEY
docker-compose up -d --build rag-api

# Cloud → Local
# Edit .env: RAG_MODE=local, start Ollama
brew services start ollama
docker-compose up -d --build rag-api
```

Note: data in ChromaDB and Pinecone are **separate** — re-ingest documents when switching.

### Switching embedding providers

Changing `EMBEDDING_PROVIDER` changes the vector dimension (384 ↔ 768). The app **detects and handles dimension mismatches automatically** — you just need to re-ingest your documents after restart.

**Pinecone (cloud mode)** — controlled by `PINECONE_AUTO_RECREATE_INDEX`:

| Setting | Behavior on dimension mismatch |
|---------|--------------------------------|
| `PINECONE_AUTO_RECREATE_INDEX=true` | Deletes the index and recreates it at the new dimension (logs a warning). All stored vectors are lost. |
| `PINECONE_AUTO_RECREATE_INDEX=false` (default) | Raises a clear error on startup with instructions. Safer for production. |

Alternative: leave the existing index alone and point the app at a new one:

```bash
PINECONE_INDEX_NAME=rag-index-gemini  # new index, created fresh at correct dim
```

**ChromaDB (local mode)** — handled automatically on ingest. If a collection's existing dimension doesn't match the new embedding provider, the app drops and recreates that collection (logs a warning). No manual volume wipe needed.

Either way, **re-ingest your documents** after switching providers:

```bash
docker-compose up -d --build rag-api
curl -X POST "http://localhost:8085/ingest?collection=my-docs" -F "file=@your-document.pdf"
```

---

## Stop services

```bash
docker-compose down          # keep ChromaDB data
docker-compose down -v       # remove ChromaDB volume
brew services stop ollama    # local mode only
```

---

## Troubleshooting

**Container name conflict:**

```bash
docker rm -f rag-chromadb rag-api
docker-compose up -d
```

**Local mode — `"ollama": false`:**

```bash
brew services start ollama
curl http://localhost:11434/api/tags
```

**Local mode — `"chromadb": false`:**

```bash
docker-compose up -d --force-recreate chromadb rag-api
```

**Cloud mode — `"pinecone": false`:** check `PINECONE_API_KEY` and region in `.env`.

**Cloud mode — `"groq": false`:** check `GROQ_API_KEY` at https://console.groq.com/keys.

**`"gemini_embedding": false`:** check `GEMINI_API_KEY` at https://aistudio.google.com/apikey.

**Dimension mismatch on Pinecone** (startup error like `Pinecone index 'rag-index' has dimension 384, but the configured embedding dimension is 768`):

```bash
# Option A: let the app handle it automatically (data loss)
PINECONE_AUTO_RECREATE_INDEX=true

# Option B: keep the old index, point to a new one
PINECONE_INDEX_NAME=rag-index-gemini
```

Then rebuild:

```bash
docker-compose up -d --build rag-api
```

**Ollama timeout (local mode):** Mistral on CPU is slow. Use cloud mode, or `ollama pull llama3.2:1b` for a faster local model.
