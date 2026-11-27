import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
from qdrant_client.models import (Distance, FieldCondition, Filter, FilterSelector,
                                  MatchValue, VectorParams)

from app.core.clients import get_qdrant_client
from app.core.config import settings
from app.rag.retriever import get_vectorstore

SUPPORTED = {".pdf", ".md", ".txt"}
CHUNK_SIZE, CHUNK_OVERLAP = 800, 100
MIN_CHUNK_CHARS = 60                 


def ensure_collection():
    client = get_qdrant_client()
    name = settings.qdrant_docs_collection
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
        )
        print(f"Created collection '{name}'")


def load_file(path: Path, root: Path):
    if path.suffix.lower() == ".pdf":
        docs = PyPDFLoader(str(path)).load()
    else:
        docs = TextLoader(str(path), encoding="utf-8").load()

    rel = path.relative_to(root)
    doc_type = rel.parts[0] if len(rel.parts) > 1 else "general"
    now = datetime.now(timezone.utc).isoformat()

    for d in docs:
        meta = {
            "source": path.name,
            "doc_type": doc_type,
            "file_type": path.suffix.lstrip(".").lower(),
            "ingested_at": now,
        }
        if "page" in d.metadata:
            meta["page"] = d.metadata["page"]
        d.metadata = meta
    return docs


def split(docs, suffix: str):
    if suffix == ".md":
        splitter = RecursiveCharacterTextSplitter.from_language(
            Language.MARKDOWN, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    return splitter.split_documents(docs)


def ingest_file(path: Path, root: Path) -> int:
    """Chunk, embed and store one file. Returns the number of chunks stored."""
    ensure_collection()
    chunks = split(load_file(path, root), path.suffix.lower())
    chunks = [c for c in chunks if len(c.page_content.strip()) > MIN_CHUNK_CHARS]
    for i, c in enumerate(chunks):
        c.metadata["chunk_index"] = i
    if not chunks:
        return 0
    key = str(path.relative_to(root))
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{key}:{i}")) for i in range(len(chunks))]
    get_vectorstore().add_documents(chunks, ids=ids)
    return len(chunks)


def delete_document(source: str, doc_type: str | None = None) -> int:
    """Remove every chunk of a document from the knowledge base. Returns chunks removed."""
    ensure_collection()
    conds = [FieldCondition(key="metadata.source", match=MatchValue(value=source))]
    if doc_type:
        conds.append(FieldCondition(key="metadata.doc_type", match=MatchValue(value=doc_type)))
    flt = Filter(must=conds)
    client, name = get_qdrant_client(), settings.qdrant_docs_collection
    n = client.count(collection_name=name, count_filter=flt, exact=True).count
    if n:
        client.delete(collection_name=name, points_selector=FilterSelector(filter=flt))
    return n


def ingest_folder(root: Path) -> int:
    total = 0
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in SUPPORTED:
            continue
        n = ingest_file(path, root)
        print(f"{path.relative_to(root)}: {n} chunks")
        total += n
    print(f"Done. {total} chunks ingested.")
    return total


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/docs")
    ingest_folder(folder)