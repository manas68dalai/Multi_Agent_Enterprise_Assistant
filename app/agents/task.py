import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import get_llm
from app.tools import TASK_TOOLS

log = logging.getLogger("task")

TASK_PROMPT = """You are the Task Agent. Prepare support-ticket actions requested by the user.

Rules:
- Use only the provided tools and only when the user explicitly requested an action.
- Create tickets with the customer ID, subject, description, and priority from the request.
- Update a ticket only when the user clearly requested a status change.
- Never invent IDs or missing details.
- Do not claim an action was completed; actions require human approval first."""

_TOOLS_BY_NAME = {tool.name: tool for tool in TASK_TOOLS}


def _record(state, attempts, status, summary, errors=None, tool_results=None):
    reports = list(state["reports"])
    reports.append({
        "agent": "task",
        "status": status,
        "summary": summary,
        "attempt": attempts["task"],
    })
    return {
        "attempts": attempts,
        "reports": reports,
        "errors": list(state["errors"]) + (errors or []),
        "tool_results": list(state["tool_results"]) + (tool_results or []),
    }


def task_plan_node(state):
    attempts = dict(state["attempts"])
    attempts["task"] = attempts.get("task", 0) + 1

    try:
        response = get_llm().bind_tools(TASK_TOOLS).invoke([
            SystemMessage(content=TASK_PROMPT),
            HumanMessage(content=state["current_instruction"]),
        ])
    except Exception as exc:
        log.exception("Task planning failed")
        return {
            **_record(
                state,
                attempts,
                "failed",
                f"Could not prepare the requested action: {type(exc).__name__}.",
                errors=[f"task planning failed: {type(exc).__name__}"],
            ),
            "pending_actions": [],
        }

    actions = []
    for call in getattr(response, "tool_calls", []):
        name, args = call.get("name"), call.get("args")
        if name not in _TOOLS_BY_NAME or not isinstance(args, dict):
            message = "The model returned an invalid task action."
            log.error("%s Tool name: %r", message, name)
            return {
                **_record(state, attempts, "failed", message, errors=[message]),
                "pending_actions": [],
            }
        actions.append({"tool": name, "args": args})

    if not actions:
        message = "No valid action could be prepared for this request."
        return {
            **_record(state, attempts, "failed", message, errors=[message]),
            "pending_actions": [],
        }

    return {"attempts": attempts, "pending_actions": actions}


def task_execute_node(state):
    attempts = dict(state["attempts"])
    actions = state["pending_actions"]

    if not state["approval"].get("approved"):
        return {
            **_record(
                state,
                attempts,
                "success",
                "The user declined the requested action(s); no changes were made.",
            ),
            "pending_actions": [],
            "approval": {},
        }

    results = []
    errors = []
    retryable_failures = []
    for action in actions:
        name, args = action["tool"], action["args"]
        tool = _TOOLS_BY_NAME.get(name)
        if tool is None:
            result = {"ok": False, "error": f"Unknown task tool: {name}"}
        else:
            try:
                result = tool.invoke(args)
            except Exception as exc:
                log.exception("Task tool %s failed", name)
                result = {
                    "ok": False,
                    "error": f"Tool execution failed: {type(exc).__name__}",
                    "retryable": True,
                }

        if not isinstance(result, dict):
            result = {"ok": False, "error": "Tool returned an invalid result."}
        ok = bool(result.get("ok"))
        error = result.get("error")
        if not ok:
            errors.append(f"task/{name}: {error or 'Action failed.'}")
            retryable_failures.append(bool(result.get("retryable")))
        results.append({
            "agent": "task",
            "tool": name,
            "args": args,
            "ok": ok,
            "error": error,
        })

    succeeded = [result for result in results if result["ok"]]
    if len(succeeded) == len(results):
        status = "success"
    elif succeeded:
        status = "partial"
    elif all(retryable_failures):
        status = "failed"
    else:
        status = "success"

    descriptions = []
    for action, result in zip(actions, results):
        if result["ok"]:
            descriptions.append(
                f"{action['tool']} succeeded: "
                f"{json.dumps(result.get('data', {}), default=str)}"
            )
        else:
            descriptions.append(f"{action['tool']} failed: {result['error']}")
    summary = " ".join(descriptions)

    return {
        **_record(state, attempts, status, summary, errors, results),
        "pending_actions": [],
        "approval": {},
    }
