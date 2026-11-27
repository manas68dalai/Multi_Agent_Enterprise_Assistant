import functools
import logging
import requests
from pymongo.errors import PyMongoError

log = logging.getLogger("tools")


def ok(data) -> dict:
    return {"ok": True, "data": data}


def fail(message: str, retryable: bool = False) -> dict:
    out = {"ok": False, "error": message}
    if retryable:
        out["retryable"] = True     
    return out


def safe(fn):
    """Turn any exception into a structured error the agent can read and react to."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except requests.RequestException as e:      
            log.warning("External API error in %s: %s", fn.__name__, e)
            return fail("External service is unavailable right now.", retryable=True)
        except ValueError as e:
            return fail(f"Invalid input: {e}")
        except PyMongoError as e:
            log.warning("MongoDB error in %s: %s", fn.__name__, e)
            return fail("Database error.", retryable=True)
        except Exception as e:
            log.exception("Unexpected error in %s", fn.__name__)  
            return fail(f"Unexpected error: {type(e).__name__}", retryable=True)
    return wrapper