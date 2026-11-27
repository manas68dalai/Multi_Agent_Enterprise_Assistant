import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_session(v):
    if v is not None and not SESSION_RE.match(v):
        raise ValueError("session_id must be 1-64 characters: letters, digits, '_' or '-'")
    return v


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, description="Omit to start a new session")

    @field_validator("session_id")
    @classmethod
    def _valid_session(cls, v):
        return _check_session(v)


class ApproveRequest(BaseModel):
    session_id: str
    approved: bool

    @field_validator("session_id")
    @classmethod
    def _valid_session(cls, v):
        return _check_session(v)


class ToolCall(BaseModel):
    agent: str
    tool: str
    args: dict
    ok: bool
    error: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    status: Literal["complete", "approval_required"]
    answer: Optional[str] = None
    agents: list[str]
    route: list[str]
    tool_calls: list[ToolCall]
    sources: list[str]
    memories_used: list[str]
    memories_saved: list[str]
    fallback_used: bool
    pending_actions: list[dict]
    latency_s: float
    usage: dict = Field(default_factory=dict)      

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
    pending_actions: list[dict]