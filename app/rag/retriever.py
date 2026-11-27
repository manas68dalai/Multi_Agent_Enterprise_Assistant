from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Filter, FieldCondition, MatchValue
from app.core.config import settings
from app.core.clients import get_qdrant_client
from app.core.llm import get_embeddings


def get_vectorstore() -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_docs_collection,
        embedding=get_embeddings(),
    )


def get_retriever(k: int = 4, doc_type: str | None = None):
    search_kwargs = {"k": k}
    if doc_type:
        search_kwargs["filter"] = Filter(must=[
            FieldCondition(key="metadata.doc_type", match=MatchValue(value=doc_type))
        ])
    return get_vectorstore().as_retriever(search_kwargs=search_kwargs)