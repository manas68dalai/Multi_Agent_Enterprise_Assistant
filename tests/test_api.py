import json
import os

os.environ["API_KEYS"] = "key-a:test_user_a,key-b:test_user_b"
os.environ["ADMIN_USERS"] = "test_user_a"

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.clients import get_mongo_db
from app.core.config import settings
from app.memory.qdrant_memory import forget_user

A, B = {"X-API-Key": "key-a"}, {"X-API-Key": "key-b"}
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} | {name}" + (f"   [{detail}]" if not cond and detail else ""))


def parse_sse(lines):
    events, ev, data = [], "message", []
    for line in lines:
        if line == "":
            if data:
                events.append((ev, json.loads("\n".join(data))))
            ev, data = "message", []
        elif line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    return events


def ticket_count():
    return get_mongo_db().tickets.count_documents({})


try:
    with TestClient(app) as c:

        # ---- observability
        r = c.get("/me", headers=A)
        check("X-Request-ID header present", bool(r.headers.get("X-Request-ID")))
        m = c.get("/metrics", headers=A)
        check("admin can read /metrics", m.status_code == 200 and "latency_s" in m.json(), m.text[:200])
        check("non-admin cannot read /metrics", c.get("/metrics", headers=B).status_code == 403)
        r = c.post("/chat", json={"message": "What is the minimum password length?"}, headers=A)
        check("response reports token usage", (r.json().get("usage") or {}).get("total_tokens", 0) > 0, str(r.json().get("usage")))
        
        # ---- status and auth
        h = c.get("/health").json()
        check("health responds", h["status"] in ("ok", "degraded"), str(h))
        check("401 without key", c.post("/chat", json={"message": "hi"}).status_code == 401)
        check("401 with wrong key", c.post("/chat", json={"message": "hi"}, headers={"X-API-Key": "nope"}).status_code == 401)
        me = c.get("/me", headers=A).json()
        check("key maps to user (and admin flag)", me == {"user_id": "test_user_a", "is_admin": True}, str(me))
        check("non-admin flag", c.get("/me", headers=B).json()["is_admin"] is False)
        check("bad session id rejected", c.post("/chat", json={"message": "hi", "session_id": "bad id!"}, headers=A).status_code == 422)

        # ---- chat + history + isolation
        r = c.post("/chat", json={"message": "What is the status of order O5001?"}, headers=A)
        j = r.json()
        check("chat completes", r.status_code == 200 and j["status"] == "complete" and j["answer"], r.text[:200])
        check("data agent used get_order_by_id", j["agents"] == ["data"] and any(t["tool"] == "get_order_by_id" for t in j["tool_calls"]), str(j["agents"]))
        sid = j["session_id"]
        hist = c.get(f"/history/{sid}", headers=A).json()
        check("history has user + assistant message", [m["role"] for m in hist["messages"]] == ["user", "assistant"])
        check("other user cannot read the session", c.get(f"/history/{sid}", headers=B).status_code == 404)

        # ---- approval flow (always rejected here, so nothing is written)
        r = c.post("/chat", json={"message": "Create a ticket for C1004: monitor is flickering"}, headers=A)
        j = r.json()
        sid2 = j["session_id"]
        check("write needs approval", j["status"] == "approval_required" and j["pending_actions"]
              and j["pending_actions"][0]["tool"] == "create_ticket", str(j)[:200])
        check("409 while approval is pending",
              c.post("/chat", json={"message": "hello", "session_id": sid2}, headers=A).status_code == 409)
        check("other user cannot approve my session",
              c.post("/approve", json={"session_id": sid2, "approved": True}, headers=B).status_code in (404, 409))
        before = ticket_count()
        r = c.post("/approve", json={"session_id": sid2, "approved": False}, headers=A)
        j = r.json()
        check("rejection completes without writing", r.status_code == 200 and j["status"] == "complete"
              and ticket_count() == before, str(j)[:200])
        check("nothing left to approve", c.post("/approve", json={"session_id": sid2, "approved": True}, headers=A).status_code == 409)

        # ---- streaming
        with c.stream("POST", "/chat/stream", json={"message": "What is the minimum password length?"}, headers=A) as resp:
            events = parse_sse(list(resp.iter_lines()))
        names = [e for e, _ in events]
        check("stream emits route, agent, answer, done",
              all(n in names for n in ("start", "route", "agent", "answer")) and names[-1] == "done", str(names))
        done = events[-1][1]
        check("stream 'done' has the final answer", bool(done.get("answer")))

        # ---- long-term memory endpoints (own data only)
        r = c.post("/chat", json={"message": "I'm customer C1002 and I prefer short answers."}, headers=A)
        check("memory saved from chat", any("C1002" in m for m in r.json()["memories_saved"]), str(r.json()["memories_saved"]))
        check("GET /memory lists it", any("C1002" in m["text"] for m in c.get("/memory", headers=A).json()["memories"]))
        check("other user has no memories", c.get("/memory", headers=B).json()["memories"] == [])
        check("DELETE /memory erases", c.delete("/memory", headers=A).json()["deleted"] >= 1
              and c.get("/memory", headers=A).json()["memories"] == [])

        # ---- knowledge base (admin only), end to end
        doc = b"# Nimbus Pet Policy\n\nEmployees may bring one dog to the office on Fridays. Dogs must be vaccinated and leashed.\n"
        files = {"file": ("zz_test_pet_policy.md", doc, "text/markdown")}
        check("non-admin cannot ingest", c.post("/ingest", files=files, data={"doc_type": "general"}, headers=B).status_code == 403)
        r = c.post("/ingest", files=files, data={"doc_type": "general"}, headers=A)
        check("admin can ingest", r.status_code == 200 and r.json()["chunks"] >= 1, r.text[:200])
        r = c.post("/chat", json={"message": "Can I bring my dog to the office?"}, headers=A)
        check("new document is answerable", "friday" in (r.json().get("answer") or "").lower(), (r.json().get("answer") or "")[:200])
        r = c.delete("/documents/general/zz_test_pet_policy.md", headers=A)
        check("admin can delete the document", r.status_code == 200 and r.json()["deleted_chunks"] >= 1, r.text[:200])
finally:
    forget_user("test_user_a")
    forget_user("test_user_b")
    try:
        db = get_mongo_db().client[settings.checkpoint_db]
        for col in ("checkpoints", "checkpoint_writes"):
            db[col].delete_many({"thread_id": {"$regex": "^test_user_"}})
    except Exception:
        pass

print(f"\nAPI tests: {sum(results)}/{len(results)} passed")