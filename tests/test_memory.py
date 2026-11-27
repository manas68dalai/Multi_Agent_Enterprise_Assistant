from app.memory.qdrant_memory import (forget_user, get_core_memories, list_memories,
                                      save_memories, search_memories)

A, B = "test-user-a", "test-user-b"
forget_user(A)
forget_user(B)

save_memories(A, [{"text": "Prefers answers as short bullet points.", "kind": "preference"},
                  {"text": "The user's customer ID is C1002.", "kind": "profile"},
                  {"text": "On 2026-11-16, ticket T9001 was set to closed.", "kind": "action"}])
save_memories(B, [{"text": "Prefers long detailed explanations.", "kind": "preference"}])

hits = search_memories(A, "How should answers be formatted for me?", k=3, min_score=0.0)
print("A recalls:", [(h["text"], h["score"]) for h in hits])
assert hits and "bullet" in hits[0]["text"].lower(), "relevant memory should rank first"

others = search_memories(A, "long detailed explanations", k=5, min_score=0.0)
assert all("long detailed" not in h["text"] for h in others), "user B's memory leaked to user A!"
print("PASS isolation: A never sees B's memories")

# 'Show my open tickets' is NOT semantically close to 'customer ID is C1002'; core recall fixes that
core = [m["text"] for m in get_core_memories(A)]
print("A core memories:", core)
assert any("C1002" in t for t in core) and any("bullet" in t for t in core), "profile + preference must be in core"
assert not any("T9001" in t for t in core), "action facts are not core"
assert all("long detailed" not in t for t in [m["text"] for m in get_core_memories(A)]), "core leaked across users"
print("PASS core recall")

n = len(list_memories(A))
save_memories(A, [{"text": "Prefers answers as short bullet points", "kind": "preference"}])
assert len(list_memories(A)) == n, "near-duplicate should not be stored twice"
print("PASS dedup")

relevant = search_memories(A, "What is my customer ID?", k=1, min_score=0.0)[0]["score"]
unrelated = search_memories(A, "best pizza recipe with mushrooms", k=1, min_score=0.0)[0]["score"]
print(f"Score check: relevant={relevant}, unrelated={unrelated}  (MEMORY_MIN_SCORE=0.55 should sit between)")

assert forget_user(A) == n and list_memories(A) == []
forget_user(B)
print("PASS forget")