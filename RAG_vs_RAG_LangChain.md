# RAG vs RAG_LangChain — Code & Logic Comparison

Both projects expose the same REST API (`/ingest`, `/query`, `/health`, `/collections`) and support the same modes via `.env` (`RAG_MODE=local|cloud`, pluggable embeddings and LLMs). The difference is **how** the RAG pipeline is implemented.

| | **RAG** | **RAG_LangChain** |
|---|---|---|
| **Port** | 8085 | 8086 |
| **Pinecone index (default)** | `rag-index-gemini` | `rag-index-langchain` |
| **Architecture** | Custom provider classes | LangChain integrations |
| **Learning focus** | RAG mechanics under the hood | Production-style LangChain usage |

---

## Project structure

| **RAG** | **RAG_LangChain** |
|---|---|
| `app/embedding_provider.py` | — |
| `app/llm_provider.py` | — |
| `app/vector_store.py` | — |
| — | `app/langchain_components.py` (all factories) |
| `app/rag_engine.py` (manual steps) | `app/rag_engine.py` (LangChain chain) |

Shared files (nearly identical): `main.py`, `config.py`, `document_loader.py`.

---

## Logic flow

### RAG — manual 3-step pipeline

```
Ingest:  chunks → embed_documents() → manually upsert to Pinecone/Chroma
Query:   question → embed_query() → vector_store.search() → join text → llm.generate()
```

You orchestrate each step yourself:

1. Embed texts yourself
2. Search the vector DB yourself
3. Build a context string yourself
4. Call the LLM with a raw prompt via **httpx** (Ollama / Groq / Gemini HTTP APIs)

### RAG_LangChain — LangChain RAG chain

```
Ingest:  chunks → vectorstore.add_documents()   (embedding happens inside LangChain)
Query:   create_retrieval_chain(retriever, stuff_documents_chain).invoke()
```

LangChain handles retrieve → prompt → LLM in one chain:

1. `vectorstore.as_retriever()` — search
2. `create_stuff_documents_chain()` — stuff docs into prompt
3. `create_retrieval_chain()` — wire retriever + LLM
4. LLM via **LangChain chat models** (`ChatGroq`, `ChatGoogleGenerativeAI`, `ChatOllama`)

### Visual summary

```
RAG (manual):
  ingest:  chunks → embed_documents() → vector_store.ingest(vectors)
  query:   question → embed_query() → search() → join text → llm.generate()

RAG_LangChain:
  ingest:  chunks → vectorstore.add_documents()
  query:   question → create_retrieval_chain(...).invoke()
                      └─ retriever → prompt → ChatGroq / ChatGemini / ChatOllama
```

---

## Code differences

### 1. Ingest — manual vs one call

**RAG** — embed, then upsert yourself (`RAG/app/rag_engine.py`):

```python
def ingest_documents(self, chunks, collection_name=DEFAULT_COLLECTION) -> dict:
    texts = [chunk.page_content for chunk in chunks]
    embeddings = self.embeddings.embed_documents(texts)
    total_stored = self.vector_store.ingest(chunks, embeddings, collection_name)
    return {"chunks_stored": total_stored, "collection": collection_name}
```

**RAG_LangChain** — LangChain vector store embeds + stores in one step (`RAG_LangChain/app/rag_engine.py`):

```python
def ingest_documents(self, chunks, collection_name=DEFAULT_COLLECTION) -> dict:
    vectorstore = get_vectorstore(collection_name)
    ids = vectorstore.add_documents(chunks)
    return {"chunks_stored": len(ids), "collection": collection_name}
```

---

### 2. Query — manual pipeline vs retrieval chain

**RAG** — four explicit steps (`RAG/app/rag_engine.py`):

```python
def query(self, question, collection_name=DEFAULT_COLLECTION, top_k=TOP_K) -> dict:
    query_embedding = self.embeddings.embed_query(question)
    documents, metadatas, scores = self.vector_store.search(
        query_embedding, collection_name, top_k
    )

    context = "\n\n---\n\n".join(documents) if documents else "No relevant context found."

    sources = []
    for meta, score in zip(metadatas, scores):
        if self.vector_store.name == "pinecone":
            similarity = round(score, 4)
        else:
            similarity = round(1 - score, 4)
        sources.append({
            "source": meta.get("source", "unknown"),
            "chunk_index": meta.get("chunk_index", -1),
            "similarity": similarity,
        })

    answer = self.llm.generate(question, context)

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "context_chunks": len(documents),
    }
```

**RAG_LangChain** — LangChain chain (`RAG_LangChain/app/rag_engine.py`):

```python
RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant. Answer the question based only on "
               "the provided context. If the context does not contain enough "
               "information, say so honestly."),
    ("human", "Context:\n{context}\n\nQuestion: {input}"),
])

def query(self, question, collection_name=DEFAULT_COLLECTION, top_k=TOP_K) -> dict:
    vectorstore = get_vectorstore(collection_name)
    retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})

    question_answer_chain = create_stuff_documents_chain(self.llm, RAG_PROMPT)
    rag_chain = create_retrieval_chain(retriever, question_answer_chain)
    result = rag_chain.invoke({"input": question})

    # ... build sources from result["context"] ...

    return {
        "question": question,
        "answer": result.get("answer", "No answer generated."),
        "sources": sources,
        "context_chunks": len(result.get("context", [])),
    }
```

**RAG** builds the prompt as a plain string (`RAG/app/llm_provider.py`):

```python
def _build_prompt(question: str, context: str) -> str:
    return f"""You are a helpful assistant. Answer the question based on the provided context.
If the context doesn't contain enough information, say so honestly.

Context:
{context}

Question: {question}

Answer:"""
```

---

### 3. Embeddings — raw HTTP vs LangChain class

**RAG** — custom `httpx` calls to Gemini API (`RAG/app/embedding_provider.py`):

```python
def _embed(self, texts: List[str], task_type: str) -> List[List[float]]:
    url = f"{self._BASE_URL}/models/{self._model}:batchEmbedContents"
    payload = {
        "requests": [self._build_request(text, task_type) for text in texts]
    }
    response = httpx.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    return [item["values"] for item in data.get("embeddings", [])]
```

**RAG_LangChain** — LangChain wrapper with 768-dim Matryoshka fix (`RAG_LangChain/app/langchain_components.py`):

```python
class _GeminiEmbeddingsWithDim(Embeddings):
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._inner.embed_documents(texts, output_dimensionality=self._dim)

    def embed_query(self, text: str) -> List[float]:
        return self._inner.embed_query(text, output_dimensionality=self._dim)

def get_embeddings() -> Embeddings:
    if EMBEDDING_PROVIDER == "gemini":
        return _GeminiEmbeddingsWithDim(
            model=f"models/{GEMINI_EMBEDDING_MODEL}",
            google_api_key=GEMINI_API_KEY,
            output_dimensionality=EMBEDDING_DIMENSION,
        )
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
```

> **Note:** `langchain-google-genai` 2.0.x ignores `output_dimensionality` on the constructor but honors it on `embed_query` / `embed_documents`. RAG avoids this by sending `outputDimensionality` directly in the Gemini HTTP JSON payload.

---

### 4. LLM — raw HTTP vs LangChain chat models

**RAG** — `httpx.post` to Ollama / Groq / Gemini (`RAG/app/llm_provider.py`):

```python
def generate(self, question: str, context: str) -> str:
    prompt = _build_prompt(question, context)
    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=OLLAMA_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("response", "No response from model.")
```

**RAG_LangChain** — LangChain chat model (`RAG_LangChain/app/langchain_components.py`):

```python
def get_llm() -> BaseChatModel:
    if RAG_MODE == "cloud":
        if LLM_PROVIDER == "gemini":
            return ChatGoogleGenerativeAI(
                model=GEMINI_MODEL,
                google_api_key=GEMINI_API_KEY,
                temperature=0.2,
            )
        return ChatGroq(api_key=GROQ_API_KEY, model=GROQ_MODEL, temperature=0.2)

    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=OLLAMA_MODEL,
        timeout=OLLAMA_TIMEOUT,
    )
```

---

### 5. Vector store — manual upsert vs LangChain store

**RAG** — builds Pinecone vectors by hand (`RAG/app/vector_store.py`):

```python
def ingest(self, chunks, embeddings, collection_name) -> int:
    vectors = []
    for chunk, embedding in zip(chunks, embeddings):
        metadata = {
            "text": chunk.page_content,
            "source": str(chunk.metadata.get("source", "unknown")),
            "chunk_index": int(chunk.metadata.get("chunk_index", -1)),
        }
        vectors.append({
            "id": str(uuid.uuid4()),
            "values": embedding,
            "metadata": metadata,
        })
    self._index.upsert(vectors=batch, namespace=collection_name)
```

**RAG_LangChain** — LangChain `PineconeVectorStore` / `Chroma` (`RAG_LangChain/app/langchain_components.py`):

```python
def get_vectorstore(collection_name: str = DEFAULT_COLLECTION) -> VectorStore:
    embeddings = get_embeddings()

    if RAG_MODE == "cloud":
        from langchain_pinecone import PineconeVectorStore
        return PineconeVectorStore(
            index=index,
            embedding=embeddings,
            namespace=collection_name,
        )

    from langchain_chroma import Chroma
    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embeddings,
    )
```

---

## Practical comparison

| Aspect | **RAG** | **RAG_LangChain** |
|---|---|---|
| **Control** | Full control over every step | Less boilerplate, LangChain conventions |
| **Embeddings (Gemini)** | Custom HTTP with `outputDimensionality` in JSON | `GoogleGenerativeAIEmbeddings` + wrapper for 768-dim |
| **Vector store** | Custom `PineconeVectorStore` / `ChromaVectorStore` | LangChain `PineconeVectorStore` / `Chroma` |
| **LLM calls** | Raw REST via `httpx` | LangChain chat models + prompt templates |
| **Dependencies** | Lighter base image | More LangChain integration packages |
| **Best for** | Learning how RAG works internally | Using LangChain patterns in production |

---

## One-line summary

**RAG** builds the pipeline manually (embed → search → prompt → HTTP LLM).  
**RAG_LangChain** does the same thing but delegates to LangChain's vector stores, retrievers, and `create_retrieval_chain` — same outcome, different abstraction layer.
