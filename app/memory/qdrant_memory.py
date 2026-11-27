import logging
import uuid
from datetime import datetime, timezone

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import (Distance, FieldCondition, Filter, FilterSelector, MatchAny,
                                  MatchValue, PayloadSchemaType, VectorParams)

from app.core.clients import get_qdrant_client
from app.core.config import settings
from app.core.llm import get_embeddings

log = logging.getLogger("memory")
USER_KEY = "metadata.user_id"     
KIND_KEY = "metadata.kind"
_ready = False


def _user_filter(user_id: str) -> Filter:
    return Filter(must=[FieldCondition(key=USER_KEY, match=MatchValue(value=user_id))])


def ensure_collection():
    global _ready
    if _ready:
        return
    client, name = get_qdrant_client(), settings.qdrant_memory_collection
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE))
    for key in (USER_KEY, KIND_KEY):
        try:
            client.create_payload_index(collection_name=name, field_name=key,
                                        field_schema=PayloadSchemaType.KEYWORD)
        except Exception:
            pass                                  
    _ready = True


def _store() -> QdrantVectorStore:
    ensure_collection()
    return QdrantVectorStore(client=get_qdrant_client(),
                             collection_name=settings.qdrant_memory_collection,
                             embedding=get_embeddings())


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _to_item(point) -> dict:
    return {"text": point.payload.get("page_content", ""), **(point.payload.get("metadata") or {})}


def save_memories(user_id: str, facts: list[dict], thread_id: str | None = None) -> list[str]:
    """Store facts [{text, kind}] for a user. Skips near-duplicates. Returns the texts saved."""
    store, saved = _store(), []
    now = datetime.now(timezone.utc).isoformat()
    for f in facts:
        text = f["text"].strip()
        if len(text) < 8:
            continue
        hits = store.similarity_search_with_score(text, k=1, filter=_user_filter(user_id))
        if hits and hits[0][1] >= settings.memory_dedup_score:
            continue                               # already known
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{_norm(text)}"))
        doc = Document(page_content=text, metadata={
            "user_id": user_id, "kind": f.get("kind", "context"),
            "thread_id": thread_id or "", "created_at": now})
        store.add_documents([doc], ids=[pid])
        saved.append(text)
    return saved


def search_memories(user_id: str, query: str, k: int | None = None, min_score: float | None = None) -> list[dict]:
    """Semantic search over one user's memories."""
    k = k or settings.memory_top_k
    min_score = settings.memory_min_score if min_score is None else min_score
    hits = _store().similarity_search_with_score(query, k=k, filter=_user_filter(user_id))
    return [{"text": d.page_content, "kind": d.metadata.get("kind"), "score": round(float(s), 3),
             "created_at": d.metadata.get("created_at")} for d, s in hits if s >= min_score]


def get_core_memories(user_id: str, limit: int | None = None) -> list[dict]:
    """The user's most recent profile + preference facts. Always relevant, so no similarity needed
    (a question like 'show my tickets' is not semantically close to 'customer ID is C1002')."""
    ensure_collection()
    limit = limit or settings.memory_core_limit
    flt = Filter(must=[FieldCondition(key=USER_KEY, match=MatchValue(value=user_id)),
                       FieldCondition(key=KIND_KEY, match=MatchAny(any=["profile", "preference"]))])
    points, _ = get_qdrant_client().scroll(
        collection_name=settings.qdrant_memory_collection, scroll_filter=flt,
        limit=100, with_payload=True, with_vectors=False)
    items = [_to_item(p) for p in points]
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items[:limit]


def list_memories(user_id: str, limit: int = 100) -> list[dict]:
    ensure_collection()
    points, _ = get_qdrant_client().scroll(
        collection_name=settings.qdrant_memory_collection, scroll_filter=_user_filter(user_id),
        limit=limit, with_payload=True, with_vectors=False)
    return [_to_item(p) for p in points]


def forget_user(user_id: str) -> int:
    """Delete ALL memories of a user. Returns how many were removed."""
    ensure_collection()
    client, name, flt = get_qdrant_client(), settings.qdrant_memory_collection, _user_filter(user_id)
    n = client.count(collection_name=name, count_filter=flt, exact=True).count
    if n:
        client.delete(collection_name=name, points_selector=FilterSelector(filter=flt))
    return n