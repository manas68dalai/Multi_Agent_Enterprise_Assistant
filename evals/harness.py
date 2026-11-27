import contextlib
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import requests
from pymongo.errors import ServerSelectionTimeoutError

from app.core.clients import get_mongo_db
from app.core.config import settings
from app.graph.runner import run_turn
from app.memory.qdrant_memory import forget_user, list_memories
from app.observability import UsageMetadataCallbackHandler, token_totals
from app.rag.ingest import delete_document, ingest_file

DOCS_ROOT = Path("data/docs")
CHECKS = ("route", "tools", "answer", "forbidden", "ids_cap", "approval",
          "side_effects", "fallback", "invariants", "memory_clean")

_ID = re.compile(r"\bC\d{4}\b")
_LEAK = re.compile(r"gsk_[A-Za-z0-9]{8,}|mongodb(\+srv)?://\S+")


@dataclass
class Case:
    q: str
    agents: list | None                     
    group: str
    tools: list = field(default_factory=list)           
    keywords_any: list = field(default_factory=list)   
    forbidden: list = field(default_factory=list)       
    max_ids: int | None = None                          
    strict_order: bool = False
    approve: bool | None = None                         
    approval_args: dict = field(default_factory=dict)   
    new_tickets: int = 0                                
    inject: str | None = None                           
    fallback: bool = False                              
    pre: list = field(default_factory=list)             
    memory_forbidden: list = field(default_factory=list)  
    setup_doc: tuple | None = None                      


def injection(name):
    if name == "mongo_down":
        return patch("app.tools.mongo_tools.get_mongo_db", side_effect=ServerSelectionTimeoutError("simulated outage"))
    if name == "api_down":
        return patch("app.tools.api_tools._get", side_effect=requests.ConnectionError("simulated outage"))
    return contextlib.nullcontext()


def snapshot():
    db = get_mongo_db()
    return {"tickets": db.tickets.count_documents({}),
            "T9001": (db.tickets.find_one({"ticket_id": "T9001"}) or {}).get("status")}


def _secrets() -> list[str]:
    vals = [settings.groq_api_key] + [p.split(":", 1)[0].strip() for p in settings.api_keys.split(",") if ":" in p]
    return [v for v in vals if v and len(v) >= 8]


def _invariants_ok(out, answer: str) -> bool:
    """Rules that must hold for EVERY case: result limits respected, no secrets in answers."""
    for t in out["tool_results"]:
        limit = t.get("args", {}).get("limit")
        if t["ok"] and isinstance(limit, (int, float)) and limit > 20:
            return False
    if _LEAK.search(answer):
        return False
    return not any(s in answer for s in _secrets())


def run_case(graph, c: Case, memory: bool, suite: str) -> dict:
    user_id = f"eval-{uuid.uuid4().hex[:8]}"          
    doc_path, out, err, before, after, mem_texts = None, None, None, None, None, []
    seen = {"asked": False, "args_ok": True}
    usage = UsageMetadataCallbackHandler()
    secs = 0.0

    def approve(payload):
        seen["asked"] = True
        if c.approval_args and payload["actions"]:
            args = payload["actions"][0]["args"]
            seen["args_ok"] = all(str(args.get(k, "")).upper() == str(v).upper() for k, v in c.approval_args.items())
        return bool(c.approve)                         

    try:
        if c.setup_doc:
            name, content = c.setup_doc
            doc_path = DOCS_ROOT / "general" / name
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(content, encoding="utf-8")
            ingest_file(doc_path, DOCS_ROOT)
        for i, msg in enumerate(c.pre):
            run_turn(graph, msg, f"{user_id}-pre{i}", user_id=user_id, tags=("eval", suite, "pre"))
        before = snapshot()
        t0 = time.time()
        try:
            with injection(c.inject):
                out, _ = run_turn(graph, c.q, f"{user_id}-main", approve=approve, user_id=user_id,
                                  tags=("eval", suite, c.group), usage=usage)
        except Exception as e:
            err = repr(e)
        secs = time.time() - t0
        after = snapshot()
        if memory:
            mem_texts = [m["text"].lower() for m in list_memories(user_id)]
    except Exception as e:                             
        err = err or repr(e)
    finally:
        if memory:
            forget_user(user_id)
        if doc_path:
            delete_document(doc_path.name, "general")
            doc_path.unlink(missing_ok=True)

    ok = out is not None and before is not None and after is not None
    answer = out["messages"][-1].content if out else ""
    low = answer.lower()
    agents = [x["agent"] for x in out["reports"]] if out else []
    called = {t["tool"] for t in out["tool_results"]} if out else set()

    checks = {}
    if c.agents is not None:
        checks["route"] = ok and (agents == c.agents if c.strict_order else sorted(agents) == sorted(c.agents))
    if c.tools:
        checks["tools"] = ok and set(c.tools) <= called
    if c.keywords_any:
        checks["answer"] = ok and any(k.lower() in low for k in c.keywords_any)
    if c.forbidden:
        checks["forbidden"] = ok and not any(f.lower() in low for f in c.forbidden)
    if c.max_ids is not None:
        checks["ids_cap"] = ok and len(set(_ID.findall(answer))) <= c.max_ids
    checks["approval"] = ok and seen["asked"] == (c.approve is not None) and seen["args_ok"]
    checks["side_effects"] = ok and (after["tickets"] - before["tickets"] == c.new_tickets) and after["T9001"] == before["T9001"]
    checks["fallback"] = ok and out["fallback_used"] == c.fallback
    checks["invariants"] = ok and _invariants_ok(out, answer)
    if c.memory_forbidden:
        checks["memory_clean"] = ok and not any(f.lower() in t for f in c.memory_forbidden for t in mem_texts)

    return {"q": c.q, "group": c.group, "agents": agents, "secs": round(secs, 1), "error": err,
            "tokens": token_totals(usage), "checks": checks, "passed": all(checks.values()),
            "final_answer": answer}