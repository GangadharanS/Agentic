import os
import shutil
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.config import UPLOAD_DIR, DEFAULT_COLLECTION
from app.document_loader import load_and_chunk, SUPPORTED_EXTENSIONS
from app.rag_engine import rag_engine

app = FastAPI(title="RAG API", version="1.0.0", description="Retrieval Augmented Generation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(UPLOAD_DIR, exist_ok=True)


class QueryRequest(BaseModel):
    question: str
    collection: Optional[str] = DEFAULT_COLLECTION
    top_k: Optional[int] = 5


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list
    context_chunks: int


class IngestResponse(BaseModel):
    filename: str
    chunks_stored: int
    collection: str


@app.get("/health")
async def health_check():
    status = await rag_engine.health_check()
    all_healthy = all(status.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": status,
    }


@app.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    file: UploadFile = File(...),
    collection: str = Query(DEFAULT_COLLECTION, description="Target collection name"),
):
    """Upload and ingest a document into the vector store."""
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Supported: {list(SUPPORTED_EXTENSIONS.keys())}",
        )

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        chunks = load_and_chunk(file_path)

        if not chunks:
            raise HTTPException(status_code=400, detail="No content extracted from document")

        result = rag_engine.ingest_documents(chunks, collection)

        return IngestResponse(
            filename=file.filename,
            chunks_stored=result["chunks_stored"],
            collection=result["collection"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """Ask a question and get a RAG-augmented answer."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = rag_engine.query(
        question=request.question,
        collection_name=request.collection,
        top_k=request.top_k,
    )

    return QueryResponse(**result)


@app.get("/collections")
async def list_collections():
    """List all document collections."""
    collections = rag_engine.list_collections()
    return {"collections": collections}


@app.delete("/collections/{name}")
async def delete_collection(name: str):
    """Delete a document collection."""
    success = rag_engine.delete_collection(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")
    return {"message": f"Collection '{name}' deleted", "success": True}
