from app.rag.retriever import get_retriever

TESTS = [
    ("How many days of annual leave do I get?", "leave_policy.md"),
    ("How long is parental leave for a secondary caregiver?", "leave_policy.md"),
    ("What is the maximum hotel cost per night?", "expense_policy.md"),
    ("When do I need director approval for an expense?", "expense_policy.md"),
    ("How fast must a lost laptop be reported?", "security_policy.md"),
    ("What is the minimum password length?", "security_policy.md"),
    ("How many days can I work from abroad?", "remote_work_policy.txt"),
    ("What is the home office stipend?", "remote_work_policy.txt"),
]

retriever = get_retriever(k=3)
hits = 0
for question, expected in TESTS:
    docs = retriever.invoke(question)
    sources = [d.metadata["source"] for d in docs]
    ok = expected in sources
    hits += ok
    print(f"{'PASS' if ok else 'FAIL'} | {question}")
    print(f"       top: {sources[0]} -> {docs[0].page_content[:90]!r}")

print(f"\nHit@3: {hits}/{len(TESTS)} = {hits / len(TESTS):.0%}")

fin = get_retriever(k=3, doc_type="finance").invoke("travel limits")
print("Filtered to finance:", {d.metadata["doc_type"] for d in fin})