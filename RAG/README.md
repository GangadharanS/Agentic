# RAG System - Retrieval Augmented Generation

A general-purpose RAG system built with FastAPI, ChromaDB, Ollama, and sentence-transformers.

## Architecture

- **FastAPI** (port 8085) - REST API for document ingestion and querying
- **ChromaDB** (port 8200) - Open-source vector database for document storage
- **Ollama** (port 11434) - Local LLM inference with Mistral 7B
- **sentence-transformers** - Open-source embedding model (all-MiniLM-L6-v2)

## Quick Start

### 1. Launch all services

```bash
cd RAG
docker-compose up --build -d
```

### 2. Pull the Mistral model (first time only)

```bash
docker exec -it rag-ollama ollama pull mistral
```

### 3. Check health

```bash
curl http://localhost:8085/health
```

## API Endpoints

### Ingest a document

```bash
curl -X POST http://localhost:8085/ingest \
  -F "file=@your-document.pdf" \
  -F "collection=my-docs"
```

Supported file types: PDF, MD, TXT, CSV, Python, Java, JS, TS, Go, SQL, YAML, JSON, XML, HTML, CSS, Shell, Gradle, Properties

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

### Delete a collection

```bash
curl -X DELETE http://localhost:8085/collections/my-docs
```

## Configuration

All settings are configurable via environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `mistral` | LLM model name |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence transformer model |
| `CHUNK_SIZE` | `500` | Document chunk size in characters |
| `CHUNK_OVERLAP` | `50` | Overlap between chunks |
| `TOP_K` | `5` | Number of similar chunks to retrieve |

## Stop services

```bash
docker-compose down
```

To also remove stored data:

```bash
docker-compose down -v
```
