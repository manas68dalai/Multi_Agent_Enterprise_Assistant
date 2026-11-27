import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.observability import METRICS, request_id_var, setup_logging, setup_tracing

setup_logging()
TRACING = setup_tracing()          

from app.api import service
from app.api.schemas import (SESSION_RE, ApproveRequest, ChatRequest, ChatResponse,
                             HistoryResponse)
from app.api.security import admin_users, get_current_user, require_admin
from app.core.clients import get_mongo_db, get_qdrant_client
from app.core.config import settings
from app.core.llm import active_model_name, get_embeddings
from app.memory.qdrant_memory import forget_user, list_memories
from app.rag.ingest import SUPPORTED, delete_document, ingest_file

log = logging.getLogger("api")

DOCS_ROOT = Path("data/docs")
DOC_TYPES = {"hr", "it", "finance", "general"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_embeddings().embed_query("warm up")      
    service.get_graph()                          
    log.info("Ready: %s/%s, checkpointer=%s, tracing=%s",
             settings.llm_provider, active_model_name(), settings.checkpointer, TRACING)
    yield


app = FastAPI(title="Multi-Agent Enterprise Assistant", version="1.1", lifespan=lifespan)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an ID (echoed in X-Request-ID) and log one access line."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    t0 = time.time()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    if request.url.path != "/health":
        log.info("request", extra={"fields": {"method": request.method, "path": request.url.path,
                                              "status": response.status_code,
                                              "ms": round((time.time() - t0) * 1000)}})
    return response


def _begin_turn(user: str, session_id: str, *, resuming: bool):
    """Checks and locks before any work starts. Returns release()."""
    tid = service.thread_id_for(user, session_id)
    pending = service.pending_actions(tid)
    if resuming and not pending:
        raise HTTPException(409, "Nothing is waiting for approval in this session.")
    if not resuming and pending:
        raise HTTPException(409, {"error": "approval_pending", "pending_actions": pending,
                                  "message": "Approve or reject the pending action first."})
    try:
        return service.acquire_turn(tid)
    except service.SessionBusy as e:
        raise HTTPException(409, str(e))
    except service.ServerBusy as e:
        raise HTTPException(429, str(e), headers={"Retry-After": "5"})


def _safe_name(name: str) -> str:
    return _UNSAFE.sub("_", Path(name or "").name).strip("._ ")


def _check_session(session_id: str):
    if not SESSION_RE.match(session_id):
        raise HTTPException(422, "Invalid session id")


@app.get("/health")
def health():
    checks = {}
    try:
        get_mongo_db().command("ping")
        checks["mongodb"] = "ok"
    except Exception:
        checks["mongodb"] = "down"
    try:
        get_qdrant_client().get_collections()
        checks["qdrant"] = "ok"
    except Exception:
        checks["qdrant"] = "down"
    return {"status": "ok" if all(v == "ok" for v in checks.values()) else "degraded",
            "checks": checks, "llm": f"{settings.llm_provider}/{active_model_name()}",
            "checkpointer": settings.checkpointer, "memory_enabled": settings.memory_enabled,
            "tracing": TRACING}


@app.get("/me")
def me(user: str = Depends(get_current_user)):
    return {"user_id": user, "is_admin": user in admin_users()}


@app.get("/metrics")
def metrics(admin: str = Depends(require_admin)):
    """Operational numbers since the server started (single-worker, in-memory)."""
    return METRICS.snapshot()


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, user: str = Depends(get_current_user)):
    session_id = req.session_id or service.new_session_id()
    release = _begin_turn(user, session_id, resuming=False)
    try:
        return service.run_chat(user, session_id, req.message)
    except Exception:
        log.exception("chat failed")
        raise HTTPException(500, "Something went wrong while processing your request.")
    finally:
        release()


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, user: str = Depends(get_current_user)):
    session_id = req.session_id or service.new_session_id()
    release = _begin_turn(user, session_id, resuming=False)
    graph_input = {"messages": [HumanMessage(content=req.message)], "user_id": user}
    return StreamingResponse(service.stream_turn(graph_input, user, session_id, False, release),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/approve", response_model=ChatResponse)
def approve(req: ApproveRequest, user: str = Depends(get_current_user)):
    release = _begin_turn(user, req.session_id, resuming=True)
    try:
        return service.run_approval(user, req.session_id, req.approved)
    except Exception:
        log.exception("approval failed")
        raise HTTPException(500, "Something went wrong while processing your request.")
    finally:
        release()


@app.post("/approve/stream")
def approve_stream(req: ApproveRequest, user: str = Depends(get_current_user)):
    release = _begin_turn(user, req.session_id, resuming=True)
    graph_input = Command(resume={"approved": bool(req.approved)})
    return StreamingResponse(
        service.stream_turn(graph_input, user, req.session_id, True, release, approved=req.approved),
        media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/history/{session_id}", response_model=HistoryResponse)
def history(session_id: str, user: str = Depends(get_current_user)):
    _check_session(session_id)
    data = service.get_history(user, session_id)
    if data is None:
        raise HTTPException(404, "Session not found")
    return data


@app.get("/sessions")
def sessions(user: str = Depends(get_current_user)):
    return {"sessions": service.list_sessions(user)}


@app.get("/memory")
def get_memory(user: str = Depends(get_current_user)):
    return {"memories": list_memories(user)}


@app.delete("/memory")
def delete_memory(user: str = Depends(get_current_user)):
    return {"deleted": forget_user(user)}


@app.post("/ingest")
def ingest(file: UploadFile = File(...), doc_type: str = Form("general"), admin: str = Depends(require_admin)):
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"doc_type must be one of {sorted(DOC_TYPES)}")
    name = _safe_name(file.filename)
    if not name or Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(400, f"Only {sorted(SUPPORTED)} files are accepted")

    dest = DOCS_ROOT / doc_type / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit, size, too_big = settings.max_upload_mb * 1024 * 1024, 0, False
    with open(dest, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                too_big = True
                break
            out.write(chunk)
    if too_big:
        dest.unlink(missing_ok=True)
        raise HTTPException(413, f"File larger than {settings.max_upload_mb} MB")

    try:
        delete_document(name, doc_type)            
        chunks = ingest_file(dest, DOCS_ROOT)
    except Exception:
        log.exception("ingest failed")
        raise HTTPException(500, "Could not process this document.")
    if chunks == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, "No extractable text found in this document.")
    log.info("ingest by %s: %s/%s -> %d chunks", admin, doc_type, name, chunks)
    return {"file": name, "doc_type": doc_type, "chunks": chunks}


@app.delete("/documents/{doc_type}/{filename}")
def remove_document(doc_type: str, filename: str, admin: str = Depends(require_admin)):
    if doc_type not in DOC_TYPES or _safe_name(filename) != filename:
        raise HTTPException(400, "Invalid document reference")
    removed = delete_document(filename, doc_type)
    path = DOCS_ROOT / doc_type / filename
    existed = path.exists()
    if existed:
        path.unlink()
    if removed == 0 and not existed:
        raise HTTPException(404, "Document not found")
    return {"deleted_chunks": removed, "file_removed": existed}