import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.core.llm import get_llm
from app.graph.utils import message_text
from app.tools import TASK_TOOLS

log = logging.getLogger("task")
TOOLS_BY_NAME = {t.name: t for t in TASK_TOOLS}
MAX_ACTIONS = 3

PLAN_PROMPT = """You are the Task Execution Agent. You can ONLY do two things: create a support ticket and update a ticket's status.
A human will review your proposed tool call before it runs, so propose exactly what is needed.

Rules:
- Never describe or claim an action in text. Either CALL the tool, or reply with exactly 'MISSING: <what is missing>' or 'UNSUPPORTED: <short reason>'.
- Do exactly what the instruction says, nothing more.
- create_ticket needs a customer ID (like C1001). If the instruction has none, reply 'MISSING: customer ID'. Do not guess.
- If the request needs anything these two tools cannot do (for example deleting or editing customers or orders), reply 'UNSUPPORTED: <short reason>'. Never pretend.
- Write a clear subject (5+ characters) and a description (10+ characters) based on the instruction."""

NUDGE = ("You did not call a tool, so NOTHING has been done yet. Call create_ticket or update_ticket_status now. "
         "If information is missing reply 'MISSING: <what is missing>'; if the request is not possible with these "
         "tools reply 'UNSUPPORTED: <short reason>'.")


def _validate(calls) -> list[str]:
    problems = []
    for c in calls:
        tool = TOOLS_BY_NAME.get(c["name"])
        if tool is None:
            problems.append(f"unknown tool '{c['name']}'")
            continue
        try:
            tool.args_schema.model_validate(c["args"])
        except ValidationError as e:
            detail = "; ".join(f"{'.'.join(map(str, x['loc']))} {x['msg']}" for x in e.errors())
            problems.append(f"{c['name']}: {detail}")
    return problems


def _describe(a: dict) -> str:
    return f"{a['tool']}({json.dumps(a['args'])})"


def task_plan_node(state):
    """Propose write actions WITHOUT executing them."""
    attempts = dict(state["attempts"])
    attempts["task"] = attempts.get("task", 0) + 1

    llm = get_llm().bind_tools(TASK_TOOLS)
    messages = [SystemMessage(content=PLAN_PROMPT), HumanMessage(content=state["current_instruction"])]
    actions, missing, unsupported, error = [], "", "", ""
    try:
        for _ in range(3):
            resp = llm.invoke(messages)
            calls = resp.tool_calls[:MAX_ACTIONS]
            if not calls:
                text = message_text(resp)
                upper = text.upper()
                if upper.startswith("MISSING"):
                    missing = text.split(":", 1)[-1].strip() or "required information"
                    break
                if upper.startswith("UNSUPPORTED"):
                    unsupported = text.split(":", 1)[-1].strip() or "this request"
                    break
                error = "the model described an action instead of proposing one"
                messages.append(HumanMessage(content=NUDGE))
                continue
            problems = _validate(calls)
            if not problems:
                actions = [{"tool": c["name"], "args": c["args"]} for c in calls]
                break
            error = "; ".join(problems)
            messages.append(HumanMessage(
                content=f"Your proposed action was invalid: {error}. Propose it again with valid arguments."))
    except Exception as e:
        log.warning("task planning crashed: %s", str(e)[:200])
        error = type(e).__name__

    if actions:
        return {"attempts": attempts, "pending_actions": actions}

    errors = list(state["errors"])
    if unsupported:
        status = "success"                       
        summary = (f"NO ACTION WAS TAKEN. This is not supported: {unsupported}. "
                   "Supported actions: create a support ticket, change a ticket's status.")
    elif missing:
        status, summary = "success", f"NO ACTION WAS TAKEN. Missing information: {missing}"
    else:
        status = "failed"
        summary = f"NO ACTION WAS TAKEN. Could not prepare a valid action ({error or 'no action proposed'})."
        errors.append(f"task/plan: {summary}")
    reports = list(state["reports"]) + [
        {"agent": "task", "status": status, "summary": summary, "attempt": attempts["task"]}]
    return {"attempts": attempts, "pending_actions": [], "errors": errors, "reports": reports}


def task_execute_node(state):
    """Run the approved actions (or record that the user declined)."""
    actions = state["pending_actions"]
    approved = bool(state.get("approval", {}).get("approved"))
    tool_results, errors = list(state["tool_results"]), list(state["errors"])

    if not approved:
        status = "success"                         
        summary = ("The user DECLINED the action(s). NO changes were made. Declined: "
                   + "; ".join(_describe(a) for a in actions))
    else:
        lines, any_failed = [], False
        for a in actions:
            try:
                res = TOOLS_BY_NAME[a["tool"]].invoke(a["args"])
            except Exception as e:
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            tool_results.append({"agent": "task", "tool": a["tool"], "args": a["args"],
                                 "ok": res["ok"], "error": res.get("error")})
            if res["ok"]:
                lines.append(f"{a['tool']} succeeded: {json.dumps(res.get('data'), default=str)}")
            else:
                any_failed = True
                errors.append(f"task/{a['tool']}: {res.get('error')}")
                lines.append(f"{a['tool']} FAILED: {res.get('error')}")
        status = "partial" if any_failed else "success"  
        summary = "\n".join(lines)

    reports = list(state["reports"]) + [
        {"agent": "task", "status": status, "summary": summary, "attempt": state["attempts"].get("task", 1)}]
    return {"tool_results": tool_results, "errors": errors, "reports": reports,
            "pending_actions": [], "approval": {}}