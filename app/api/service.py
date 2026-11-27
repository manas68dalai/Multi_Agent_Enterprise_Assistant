import json
import logging
import re
import threading
import time
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.core.clients import get_mongo_db
from app.core.config import settings
from app.graph.builder import build_graph
from app.graph.utils import message_text
from app.observability import METRICS, log_turn, make_run_config, token_totals

log = logging.getLogger("api")

GRAPH_CACHE: dict = {}
GRAPH_LOCK = threading.Lock()


def get_graph():
    graph = GRAPH_CACHE.get("graph")
    if graph is None:
        with GRAPH_LOCK:
            graph = GRAPH_CACHE.get("graph")
            if graph is None:
                graph = build_graph()            
                GRAPH_CACHE["graph"] = graph
    return graph


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def thread_id_for(user_id: str, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def config_for(thread_id: str) -> dict:
    """Plain config for reading state (no tracing)."""
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


class SessionBusy(Exception):
    pass


class ServerBusy(Exception):
    pass


TURN_TTL = 300                                  
ACTIVE_TURNS: dict[str, float] = {}               
ACTIVE_LOCK = threading.Lock()


def acquire_turn(thread_id: str):
    """One running turn per session, and a global cap. Returns a release() function."""
    now = time.time()
    with ACTIVE_LOCK:
        for key, started in list(ACTIVE_TURNS.items()):
            if now - started > TURN_TTL:
                del ACTIVE_TURNS[key]
        if thread_id in ACTIVE_TURNS:
            raise SessionBusy("This session is still processing the previous message.")
        if len(ACTIVE_TURNS) >= settings.api_max_concurrent_turns:
            raise ServerBusy("The server is busy. Please try again in a few seconds.")
        ACTIVE_TURNS[thread_id] = now

    def release():
        with ACTIVE_LOCK:
            ACTIVE_TURNS.pop(thread_id, None)
    return release


def pending_actions(thread_id: str) -> list:
    snap = get_graph().get_state(config_for(thread_id))
    if snap and snap.next and "approval" in snap.next:
        return snap.values.get("pending_actions", []) or []
    return []


def _slim_tool(t: dict) -> dict:
    return {"agent": t["agent"], "tool": t["tool"], "args": t.get("args", {}),
            "ok": bool(t["ok"]), "error": t.get("error")}


def summarize(values: dict, paused: bool, session_id: str, t0: float, usage=None) -> dict:
    msgs = values.get("messages", [])
    answer = None
    if not paused and msgs and isinstance(msgs[-1], AIMessage):
        answer = message_text(msgs[-1])
    return {
        "session_id": session_id,
        "status": "approval_required" if paused else "complete",
        "answer": answer,
        "agents": [r["agent"] for r in values.get("reports", [])],
        "route": values.get("route_log", []),
        "tool_calls": [_slim_tool(t) for t in values.get("tool_results", [])],
        "sources": values.get("sources", []),
        "memories_used": values.get("memories", []),
        "memories_saved": values.get("memory_saved", []),
        "fallback_used": bool(values.get("fallback_used", False)),
        "pending_actions": (values.get("pending_actions") or []) if paused else [],
        "latency_s": round(time.time() - t0, 1),
        "usage": token_totals(usage) if usage is not None else {},
    }


def _final_summary(thread_id: str, session_id: str, t0: float, usage=None) -> dict:
    snap = get_graph().get_state(config_for(thread_id))
    paused = bool(snap.next and "approval" in snap.next)
    return summarize(snap.values, paused, session_id, t0, usage)


def run_chat(user_id: str, session_id: str, message: str) -> dict:
    t0, tid = time.time(), thread_id_for(user_id, session_id)
    config, usage = make_run_config(tid, user_id, session_id, kind="chat")
    try:
        get_graph().invoke({"messages": [HumanMessage(content=message)], "user_id": user_id}, config)
        summary = _final_summary(tid, session_id, t0, usage)
    except Exception:
        METRICS.record_error()
        raise
    METRICS.record_turn(summary)
    log_turn("chat", user_id, session_id, summary)
    return summary


def run_approval(user_id: str, session_id: str, approved: bool) -> dict:
    t0, tid = time.time(), thread_id_for(user_id, session_id)
    config, usage = make_run_config(tid, user_id, session_id, kind="approve")
    METRICS.record_decision(approved)
    try:
        get_graph().invoke(Command(resume={"approved": bool(approved)}), config)
        summary = _final_summary(tid, session_id, t0, usage)
    except Exception:
        METRICS.record_error()
        raise
    METRICS.record_turn(summary)
    log_turn("approve", user_id, session_id, summary)
    return summary


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _events_for(node: str, update: dict, st: dict):
    """Translate one graph node update into zero or more (event, data) pairs."""
    if node == "recall":
        yield "memory_recalled", {"memories": update.get("memories", [])}
    elif node == "supervisor":
        yield "route", {"next": update.get("next_agent"), "reason": update.get("route_reason"),
                        "step": update.get("step_count")}
    elif node in ("research", "data", "task_execute", "task_plan"):
        if node == "task_plan" and update.get("pending_actions"):
            yield "proposal", {"actions": update["pending_actions"]}
            return
        results = update.get("tool_results", [])
        new, st["tools_seen"] = results[st["tools_seen"]:], len(results)
        reports = update.get("reports", [])
        report = reports[-1] if reports else {}
        yield "agent", {"agent": "task" if node.startswith("task") else node,
                        "status": report.get("status"), "summary": report.get("summary"),
                        "tool_calls": [_slim_tool(t) for t in new]}
    elif node == "synthesizer":
        msgs = update.get("messages", [])
        yield "answer", {"text": message_text(msgs[-1]) if msgs else "", "sources": update.get("sources", [])}
    elif node == "memory_write":
        yield "memory_saved", {"memories": update.get("memory_saved", [])}


def stream_turn(graph_input, user_id: str, session_id: str, resume: bool, release, approved: bool | None = None):
    """Generator of SSE strings. Always releases the session lock when finished."""
    graph, tid, t0 = get_graph(), thread_id_for(user_id, session_id), time.time()
    kind = "approve.stream" if resume else "chat.stream"
    config, usage = make_run_config(tid, user_id, session_id, kind=kind)
    try:
        st = {"tools_seen": 0}
        if resume:                               
            st["tools_seen"] = len(graph.get_state(config_for(tid)).values.get("tool_results", []))
            if approved is not None:
                METRICS.record_decision(approved)
        yield sse("start", {"session_id": session_id, "resume": resume})

        for chunk in graph.stream(graph_input, config, stream_mode="updates"):
            for node, update in chunk.items():
                if not isinstance(update, dict):  
                    continue
                for event, data in _events_for(node, update, st):
                    yield sse(event, data)

        summary = _final_summary(tid, session_id, t0, usage)
        METRICS.record_turn(summary)
        log_turn(kind, user_id, session_id, summary)
        if summary["status"] == "approval_required":
            yield sse("approval_required", {"actions": summary["pending_actions"]})
        yield sse("done", summary)
    except Exception:
        METRICS.record_error()
        log.exception("stream failed")
        yield sse("error", {"message": "Something went wrong while processing your request."})
    finally:
        release()


def get_history(user_id: str, session_id: str):
    """Messages of one of the user's sessions, or None if it doesn't exist."""
    tid = thread_id_for(user_id, session_id)
    snap = get_graph().get_state(config_for(tid))
    if not snap or not snap.values:
        return None
    messages = []
    for m in snap.values.get("messages", []):
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        else:
            continue
        text = message_text(m)
        if text:
            messages.append({"role": role, "content": text})
    paused = bool(snap.next and "approval" in snap.next)
    return {"session_id": session_id, "messages": messages,
            "pending_actions": (snap.values.get("pending_actions") or []) if paused else []}


def list_sessions(user_id: str) -> list[str]:
    """The user's session ids (read from the checkpoint store). Empty if the store is in-memory."""
    try:
        coll = get_mongo_db().client[settings.checkpoint_db]["checkpoints"]
        prefix = user_id + ":"
        ids = coll.distinct("thread_id", {"thread_id": {"$regex": "^" + re.escape(prefix)}})
        return sorted((i[len(prefix):] for i in ids), reverse=True)
    except Exception:
        log.warning("could not list sessions", exc_info=True)
        return []