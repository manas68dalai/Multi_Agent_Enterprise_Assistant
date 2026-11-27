import argparse
import json
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings
from app.core.llm import active_model_name, get_embeddings
from app.graph.builder import build_graph
from app.observability import setup_logging, setup_tracing
from evals.harness import CHECKS, run_case
from evals.suites import SUITES

RESULTS = Path("evals/results")


def run_suite(name, cases, memory, repeat):
    graph = build_graph(checkpointer=InMemorySaver(), enable_memory=memory)
    runs = []
    for rep in range(1, repeat + 1):
        results = []
        for i, c in enumerate(cases, 1):
            r = run_case(graph, c, memory, name)
            results.append(r)
            print(f"[{name} {rep}/{repeat}] {'PASS' if r['passed'] else 'FAIL'} | {i:02d} {c.group:<17} "
                  f"| {r['agents']} | {r['secs']:>5}s | {c.q[:64]}")
            if not r["passed"]:
                bad = [k for k, v in r["checks"].items() if not v]
                print(f"       failed: {bad} | error: {r['error']}")
        runs.append(results)
    return runs


def summarize(name, runs):
    flat = [r for run in runs for r in run]
    per_run = [sum(r["passed"] for r in run) / len(run) for run in runs]
    checks = {}
    for k in CHECKS:
        vals = [r["checks"][k] for r in flat if k in r["checks"]]
        if vals:
            checks[k] = {"passed": sum(vals), "total": len(vals)}
    secs = sorted(r["secs"] for r in flat)
    tokens = [r["tokens"].get("total_tokens", 0) for r in flat]
    by_q = {}
    for r in flat:
        by_q.setdefault(r["q"], []).append(r["passed"])
    return {
        "suite": name, "cases": len(runs[0]), "repeat": len(runs),
        "pass_rate": {"mean": round(sum(per_run) / len(per_run), 3), "min": round(min(per_run), 3),
                      "max": round(max(per_run), 3), "per_run": [round(p, 3) for p in per_run]},
        "checks": checks,
        "violations": {"unwanted_writes": sum(1 for r in flat if r["checks"].get("side_effects") is False),
                       "invariant_breaks": sum(1 for r in flat if r["checks"].get("invariants") is False),
                       "approval_gate_errors": sum(1 for r in flat if r["checks"].get("approval") is False)},
        "latency_s": {"avg": round(sum(secs) / len(secs), 1), "p95": secs[int(0.95 * (len(secs) - 1))]},
        "tokens": {"avg_per_case": round(sum(tokens) / len(tokens)), "total": sum(tokens)},
        "always_failing": [q for q, v in by_q.items() if not any(v)],
        "flaky": [q for q, v in by_q.items() if any(v) and not all(v)],
    }


def acc(s, key):
    d = s["checks"].get(key)
    return f"{d['passed']}/{d['total']}" if d else "-"


def print_summary(s):
    pr = s["pass_rate"]
    print("\n" + "=" * 70)
    print(f"Suite {s['suite']} | model {settings.llm_provider}/{active_model_name()} | {s['cases']} cases x {s['repeat']} run(s)")
    print(f"Pass rate            : mean {pr['mean']:.0%}  (min {pr['min']:.0%}, max {pr['max']:.0%})  per run: {pr['per_run']}")
    for k in CHECKS:
        if k in s["checks"]:
            print(f"  {k:<18} : {acc(s, k)}")
    v = s["violations"]
    print(f"Unwanted writes      : {v['unwanted_writes']}   invariant breaks: {v['invariant_breaks']}   approval-gate errors: {v['approval_gate_errors']}")
    print(f"Latency              : avg {s['latency_s']['avg']}s, p95 {s['latency_s']['p95']}s")
    print(f"Tokens               : avg {s['tokens']['avg_per_case']}/case, total {s['tokens']['total']}")
    if s["always_failing"]:
        print("ALWAYS FAILING       :", *s["always_failing"], sep="\n   - ")
    if s["flaky"]:
        print("FLAKY (pass/fail mix):", *s["flaky"], sep="\n   - ")


def save(s, runs):
    RESULTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    meta = {"timestamp": ts, "provider": settings.llm_provider, "model": active_model_name()}
    (RESULTS / f"{s['suite']}_{ts}.json").write_text(
        json.dumps({"meta": meta, "summary": s, "runs": runs}, indent=2, default=str), encoding="utf-8")

    md = RESULTS / "SUMMARY.md"
    if not md.exists():
        md.write_text("| Date | Model | Suite | Cases x runs | Pass rate mean (min-max) | Routing | Approval gate "
                      "| Unwanted writes | Invariant breaks | Avg latency | p95 | Avg tokens/case |\n"
                      "|---|---|---|---|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
    pr, v = s["pass_rate"], s["violations"]
    row = (f"| {ts[:8]} | {settings.llm_provider}/{active_model_name()} | {s['suite']} | {s['cases']} x {s['repeat']} "
           f"| {pr['mean']:.0%} ({pr['min']:.0%}-{pr['max']:.0%}) | {acc(s, 'route')} | {acc(s, 'approval')} "
           f"| {v['unwanted_writes']} | {v['invariant_breaks']} | {s['latency_s']['avg']}s | {s['latency_s']['p95']}s "
           f"| {s['tokens']['avg_per_case']} |\n")
    with open(md, "a", encoding="utf-8") as f:
        f.write(row)
    print(f"\nSaved evals/results/{s['suite']}_{ts}.json and appended a row to evals/results/SUMMARY.md")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=["dev", "heldout", "safety", "all"])
    ap.add_argument("--repeat", type=int, default=1, help="run the whole suite N times (LLM output varies)")
    ap.add_argument("--group", default=None, help="only cases of this group")
    args = ap.parse_args()

    setup_logging()
    setup_tracing()                              
    get_embeddings().embed_query("warm up")

    for name in (list(SUITES) if args.suite == "all" else [args.suite]):
        cases, memory = SUITES[name]
        if args.group:
            cases = [c for c in cases if c.group == args.group]
        if not cases:
            continue
        runs = run_suite(name, cases, memory, args.repeat)
        summary = summarize(name, runs)
        print_summary(summary)
        save(summary, runs)