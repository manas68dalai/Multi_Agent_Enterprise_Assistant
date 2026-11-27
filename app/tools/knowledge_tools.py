from langchain_core.tools import tool
from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.rag.retriever import get_vectorstore
from app.tools.base import ok, fail, safe
from app.tools.schemas import KBSearchInput, KBChunk

MIN_SCORE = 0.5


@tool("search_knowledge_base", args_schema=KBSearchInput)
@safe
def search_knowledge_base(query: str, doc_type: str | None = None) -> dict:
    """Search internal company policy documents (HR leave and remote work, IT security, finance and
    expenses). Use for any policy question. Always cite the 'source' file in your answer."""
    flt = None
    if doc_type:
        flt = Filter(must=[FieldCondition(key="metadata.doc_type", match=MatchValue(value=doc_type))])

    results = get_vectorstore().similarity_search_with_score(query, k=5, filter=flt)
    chunks = [
        KBChunk(source=d.metadata.get("source", "?"), doc_type=d.metadata.get("doc_type", "general"),
                page=d.metadata.get("page"), score=round(float(s), 3), text=d.page_content)
        for d, s in results if s >= MIN_SCORE
    ]
    if not chunks:
        return fail("No relevant passages found in the knowledge base. Say you could not find it.")
    return ok([c.model_dump() for c in chunks])