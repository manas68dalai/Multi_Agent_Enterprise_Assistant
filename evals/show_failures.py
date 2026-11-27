import json
import sys
from pathlib import Path

RESULTS = Path("evals/results")


def main():
    suite = sys.argv[1] if len(sys.argv) > 1 else "safety"
    last_n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    files = sorted(RESULTS.glob(f"{suite}_*.json"))[-last_n:]
    if not files:
        sys.exit(f"No results found for suite '{suite}'")
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        print("=" * 78 + f"\n{f.name} | {data['meta'].get('model')}")
        for rep, run in enumerate(data["runs"], 1):
            for r in run:
                if r["passed"]:
                    continue
                bad = [k for k, v in r["checks"].items() if not v]
                print(f"\n[run {rep}] {r['group']} | {r['q'][:72]}")
                print(f"   failed checks : {bad}")
                print(f"   agents        : {r['agents']} | error: {r['error']}")
                for line in r.get("route_log", []):
                    print(f"   route         : {line[:150]}")
                for t in r.get("tool_calls", []):
                    print(f"   tool          : {t[0]} {t[1]} ok={t[2]}")
                for e in r.get("errors", [])[:3]:
                    print(f"   error         : {str(e)[:220]}")
                print(f"   answer        : {r['final_answer'][:300]!r}")


main()