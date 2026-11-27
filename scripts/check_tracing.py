from langsmith import Client

from app.core.config import settings
from app.observability import setup_tracing

key = settings.langsmith_api_key
print("tracing requested :", settings.langsmith_tracing, "| project:", settings.langsmith_project)
print("endpoint          :", settings.langsmith_endpoint or "(default, US region)")
print("workspace id      :", settings.langsmith_workspace_id or "(none)")
print("key               :", (key[:8] + "..." + key[-4:]) if len(key) > 14 else "EMPTY OR TOO SHORT")
print("setup_tracing()   ->", setup_tracing())
try:
    print("OK. Projects visible to this key:", [p.name for p in Client().list_projects(limit=3)])
except Exception as e:
    print("FAILED:", str(e)[:300])