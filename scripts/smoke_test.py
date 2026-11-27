"""Run against a live deployment:  docker compose exec api python -m scripts.smoke_test"""
import os
import sys

import requests

from app.core.config import settings

base = os.getenv("BASE_URL", "http://localhost:8000")
key = settings.api_keys.split(",")[0].split(":")[0].strip() if settings.api_keys else ""
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + ("" if ok else f"   [{detail}]"))


h = requests.get(f"{base}/health", timeout=20).json()
check("health: MongoDB", h["checks"].get("mongodb") == "ok", h)
check("health: Qdrant", h["checks"].get("qdrant") == "ok", h)

r = requests.post(f"{base}/chat", json={"message": "What is the status of order O5001?"},
                  headers={"X-API-Key": key}, timeout=180)
j = r.json() if r.ok else {}
check("chat answers a database question", r.ok and j.get("status") == "complete" and j.get("agents") == ["data"], r.text[:200])

r = requests.post(f"{base}/chat", json={"message": "What is the minimum password length?"},
                  headers={"X-API-Key": key}, timeout=180)
j = r.json() if r.ok else {}
check("chat answers a policy question from the knowledge base", r.ok and "14" in (j.get("answer") or ""), r.text[:200])

print(f"\nSmoke test: {sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)