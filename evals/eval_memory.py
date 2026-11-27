import uuid
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import build_graph
from app.graph.runner import run_turn
from app.memory.qdrant_memory import forget_user

run = uuid.uuid4().hex[:6]
USER_A, USER_B = f"eval-mem-a-{run}", f"eval-mem-b-{run}"
graph = build_graph(checkpointer=InMemorySaver(), enable_memory=True)


def tickets_cid(out):
    return [str(t["args"].get("customer_id", "")).upper() for t in out["tool_results"] if t["tool"] == "search_tickets"]


results = []

# 1) Long-term: a fact stated in one thread is used in a NEW thread
out1, _ = run_turn(graph, "I'm customer C1002 and I prefer short bullet-point answers.", f"t1-{run}", user_id=USER_A)
stored = any("C1002" in s for s in out1["memory_saved"])
out2, _ = run_turn(graph, "Show my open tickets.", f"t2-{run}", user_id=USER_A)
results.append(("long-term recall across threads", stored and "C1002" in tickets_cid(out2)))

# 2) Isolation: another user must NOT inherit that ID
out3, _ = run_turn(graph, "Show my open tickets.", f"t3-{run}", user_id=USER_B)
results.append(("user isolation", "C1002" not in tickets_cid(out3) and not out3["memories"]))

# 3) Short-term: a follow-up inside the same thread resolves "that customer"
run_turn(graph, "Look up customer C1001", f"t4-{run}", user_id=USER_B)
out5, _ = run_turn(graph, "Show open tickets for that customer.", f"t4-{run}", user_id=USER_B)
results.append(("short-term follow-up in same thread", "C1001" in tickets_cid(out5)))

forget_user(USER_A)
forget_user(USER_B)
for name, ok in results:
    print(f"{'PASS' if ok else 'FAIL'} | {name}")
print(f"\nMemory eval: {sum(ok for _, ok in results)}/{len(results)}")