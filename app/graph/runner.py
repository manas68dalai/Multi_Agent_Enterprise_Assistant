from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.observability import make_run_config


def _simple_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def run_turn(graph, question: str, thread_id: str, approve=lambda payload: False,
             user_id: str = "anonymous", max_resumes: int = 3, tags=(), usage=None):
    """Run one user turn. Approval interrupts are answered by approve(payload) -> bool.
    Default is REJECT, so nothing is written unless a caller explicitly approves.
    `tags` / `usage` add trace tags and a token counter (used by the evals)."""
    config, _ = make_run_config(thread_id, user_id, session_id=thread_id, kind="run_turn",
                                extra_tags=tags, usage=usage)
    out = graph.invoke({"messages": [HumanMessage(content=question)], "user_id": user_id}, config)
    approvals = []
    while out.get("__interrupt__") and len(approvals) < max_resumes:
        payload = out["__interrupt__"][0].value
        decision = bool(approve(payload))
        approvals.append({"payload": payload, "approved": decision})
        out = graph.invoke(Command(resume={"approved": decision}), config)
    return out, approvals


def get_pending(graph, thread_id: str):
    """Pending write actions if this thread is paused for approval, else None."""
    snap = graph.get_state(_simple_config(thread_id))
    if snap and snap.next and "approval" in snap.next:
        return snap.values.get("pending_actions", [])
    return None


def resume_turn(graph, thread_id: str, approved: bool):
    return graph.invoke(Command(resume={"approved": bool(approved)}), _simple_config(thread_id))