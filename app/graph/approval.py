from langgraph.types import interrupt


def approval_node(state):
    decision = interrupt({
        "type": "approval_request",
        "message": "The assistant wants to perform the following action(s). Approve?",
        "actions": state["pending_actions"],
    })
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    return {"approval": {"approved": approved}}