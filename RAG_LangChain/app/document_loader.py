import os
from typing import List
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredMarkdownLoader,
    CSVLoader,
)
from langchain_core.documents import Document
from app.config import CHUNK_SIZE, CHUNK_OVERLAP


SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "markdown",
    ".csv": "csv",
    ".py": "code",
    ".java": "code",
    ".js": "code",
    ".ts": "code",
    ".jsx": "code",
    ".tsx": "code",
    ".go": "code",
    ".rs": "code",
    ".rb": "code",
    ".yml": "text",
    ".yaml": "text",
    ".json": "text",
    ".xml": "text",
    ".html": "text",
    ".css": "text",
    ".sql": "code",
    ".sh": "code",
    ".gradle": "code",
    ".properties": "text",
}


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def load_document(file_path: str) -> List[Document]:
    """Load a single document based on its file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    file_type = SUPPORTED_EXTENSIONS.get(ext)

    if file_type is None:
        raise ValueError(f"Unsupported file type: {ext}")

    if file_type == "pdf":
        loader = PyPDFLoader(file_path)
    elif file_type == "markdown":
        loader = UnstructuredMarkdownLoader(file_path)
    elif file_type == "csv":
        loader = CSVLoader(file_path)
    else:
        loader = TextLoader(file_path, encoding="utf-8")

    documents = loader.load()

    for doc in documents:
        doc.metadata["source"] = os.path.basename(file_path)
        doc.metadata["file_type"] = file_type

    return documents


def chunk_documents(documents: List[Document]) -> List[Document]:
    """Split documents into smaller chunks for embedding."""
    splitter = get_text_splitter()
    chunks = splitter.split_documents(documents)

    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i

    return chunks


def load_and_chunk(file_path: str) -> List[Document]:
    """Load a document and split it into chunks."""
    documents = load_document(file_path)
    return chunk_documents(documents)
