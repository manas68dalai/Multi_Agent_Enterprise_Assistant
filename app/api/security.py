import re
import secrets

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import settings

USER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _key_map() -> dict[str, str]:
    mapping = {}
    for pair in settings.api_keys.split(","):
        if ":" not in pair:
            continue
        key, user = (p.strip() for p in pair.split(":", 1))
        if key and USER_RE.match(user):
            mapping[key] = user
    return mapping


def admin_users() -> set[str]:
    return {u.strip() for u in settings.admin_users.split(",") if u.strip()}


def get_current_user(api_key: str | None = Security(_api_key_header)) -> str:
    """The user_id comes from the API key on the server, never from anything the client sends."""
    keys = _key_map()
    if not keys:
        raise HTTPException(503, "Server is not configured: set API_KEYS in .env")
    if api_key:
        for key, user in keys.items():
            if secrets.compare_digest(key.encode(), api_key.encode()):
                return user
    raise HTTPException(401, "Invalid or missing API key")


def require_admin(user: str = Depends(get_current_user)) -> str:
    if user not in admin_users():
        raise HTTPException(403, "Admin access required")
    return user