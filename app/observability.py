import contextvars
import json
import logging
import os
import time
from collections import Counter, deque
from datetime import datetime, timezone
from threading import Lock

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from app.core.config import settings

try:
    from langchain_core.callbacks import UsageMetadataCallbackHandler
except ImportError:                             
    UsageMetadataCallbackHandler = None

log = logging.getLogger("observability")
request_id_var = contextvars.ContextVar("request_id", default="-")

_NOISY = ("httpx", "httpx2", "httpcore", "sentence_transformers", "huggingface_hub", "urllib3")


class _RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


class _TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s", "%H:%M:%S")

    def format(self, record):
        base = super().format(record)
        fields = getattr(record, "fields", None)
        return base + (" | " + " ".join(f"{k}={v}" for k, v in fields.items()) if fields else "")


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                   "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
                   "request_id": getattr(record, "request_id", "-")}
        payload.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging():
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(_JsonFormatter() if settings.log_format.lower() == "json" else _TextFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_tracing() -> bool:
    """Enable LangSmith tracing. Must run before the first LLM call (the library reads env vars early).
    The key is checked once; if LangSmith rejects it, tracing is switched off with one clear warning
    instead of a flood of 403 errors."""
    if not settings.langsmith_tracing:
        return False
    key = settings.langsmith_api_key.strip().strip('"').strip("'")
    if not key:
        log.warning("LANGSMITH_TRACING is on but LANGSMITH_API_KEY is empty: tracing disabled")
        return False

    env = {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": key, "LANGSMITH_PROJECT": settings.langsmith_project,
           "LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": key, "LANGCHAIN_PROJECT": settings.langsmith_project}
    if settings.langsmith_endpoint:
        env["LANGSMITH_ENDPOINT"] = env["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    if settings.langsmith_workspace_id:
        env["LANGSMITH_WORKSPACE_ID"] = settings.langsmith_workspace_id
    if settings.langsmith_hide_io:
        env.update({"LANGCHAIN_HIDE_INPUTS": "true", "LANGCHAIN_HIDE_OUTPUTS": "true",
                    "LANGSMITH_HIDE_INPUTS": "true", "LANGSMITH_HIDE_OUTPUTS": "true"})
    os.environ.update(env)

    try:
        from langsmith import Client
        next(iter(Client().list_projects(limit=1)), None)        
    except Exception as e:
        msg = str(e)
        if any(token in msg for token in ("401", "403", "Forbidden", "Unauthorized")):
            log.warning("LangSmith rejected the API key (%s). Tracing is DISABLED. Check the key, the region "
                        "(LANGSMITH_ENDPOINT) and the workspace (LANGSMITH_WORKSPACE_ID).", msg[:100])
            os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"
            return False
        log.warning("Could not verify the LangSmith key (%s); leaving tracing on", msg[:100])
    return True

def make_run_config(thread_id: str, user_id: str, session_id: str | None = None, kind: str = "chat",
                    extra_tags=(), usage=None):
    """Graph config with trace metadata and a token counter. Returns (config, usage_handler)."""
    from app.core.llm import active_model_name
    if usage is None and UsageMetadataCallbackHandler is not None:
        usage = UsageMetadataCallbackHandler()
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 40,
        "run_name": f"assistant.{kind}",
        "tags": [f"env:{settings.environment}", f"provider:{settings.llm_provider}", kind, *extra_tags],
        "metadata": {"user_id": user_id, "session_id": session_id or thread_id, "thread_id": thread_id,
                     "model": active_model_name(), "environment": settings.environment},
        "callbacks": [usage] if usage is not None else [],
    }
    return config, usage


def token_totals(usage) -> dict:
    inp = out = 0
    for u in (getattr(usage, "usage_metadata", None) or {}).values():
        inp += u.get("input_tokens", 0) or 0
        out += u.get("output_tokens", 0) or 0
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}


class Metrics:
    def __init__(self):
        self._lock = Lock()
        self.started = time.time()
        self.calls = 0
        self.turns = Counter()
        self.errors = 0
        self.fallbacks = 0
        self.agent_runs = Counter()
        self.tool_calls = 0
        self.tool_errors = 0
        self.tool_by_name = Counter()
        self.approvals = Counter()
        self.tokens_in = 0
        self.tokens_out = 0
        self.latencies = deque(maxlen=500)

    def record_turn(self, summary: dict):
        with self._lock:
            self.calls += 1
            self.turns[summary["status"]] += 1
            self.latencies.append(summary["latency_s"])
            usage = summary.get("usage") or {}
            self.tokens_in += usage.get("input_tokens", 0)
            self.tokens_out += usage.get("output_tokens", 0)
            if summary["status"] == "approval_required":
                self.approvals["requested"] += 1
                return                      
            if summary.get("fallback_used"):
                self.fallbacks += 1
            for a in summary.get("agents", []):
                self.agent_runs[a] += 1
            for t in summary.get("tool_calls", []):
                self.tool_calls += 1
                self.tool_by_name[t["tool"]] += 1
                if not t["ok"]:
                    self.tool_errors += 1

    def record_decision(self, approved: bool):
        with self._lock:
            self.approvals["approved" if approved else "rejected"] += 1

    def record_error(self):
        with self._lock:
            self.errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            lat, n = sorted(self.latencies), len(self.latencies)
            done = self.turns["complete"]
            pick = lambda q: round(lat[int(q * (n - 1))], 2) if n else None
            return {
                "uptime_s": round(time.time() - self.started),
                "requests": {"complete": done, "approval_required": self.turns["approval_required"],
                             "errors": self.errors},
                "latency_s": {"avg": round(sum(lat) / n, 2) if n else None, "p50": pick(0.5),
                              "p95": pick(0.95), "window": n},
                "fallback_rate": round(self.fallbacks / done, 3) if done else None,
                "agent_runs": dict(self.agent_runs),
                "tools": {"calls": self.tool_calls,
                          "error_rate": round(self.tool_errors / self.tool_calls, 3) if self.tool_calls else None,
                          "by_name": dict(self.tool_by_name)},
                "approvals": dict(self.approvals),
                "tokens": {"input": self.tokens_in, "output": self.tokens_out,
                           "avg_per_request": round((self.tokens_in + self.tokens_out) / self.calls) if self.calls else None},
            }


METRICS = Metrics()


def log_turn(kind: str, user_id: str, session_id: str, summary: dict):
    """One structured line per request: metadata only (never message text)."""
    log.info("turn", extra={"fields": {
        "kind": kind, "user_id": user_id, "session_id": session_id, "status": summary["status"],
        "latency_s": summary["latency_s"], "agents": summary["agents"],
        "tools": [t["tool"] for t in summary["tool_calls"]],
        "tool_errors": sum(1 for t in summary["tool_calls"] if not t["ok"]),
        "fallback": summary["fallback_used"], "tokens": summary.get("usage", {}).get("total_tokens", 0)}})