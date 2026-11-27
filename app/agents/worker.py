import json
import logging
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.core.llm import get_llm
from app.graph.utils import message_text

log = logging.getLogger("agents")
MAX_TOOL_ROUNDS = 4

RETRY_HINT = ("Your last tool call could not be processed (malformed or invalid arguments). "
              "Call the tool again with valid JSON arguments, or answer in plain text if no tool is needed.")


def _is_tool_format_error(e: Exception) -> bool:
    text = str(e)
    return "tool_use_failed" in text or "Failed to parse tool call" in text or "tool call validation failed" in text


class LoopState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    rounds: int


def build_agent_loop(tools, system_prompt: str):
    """llm <-> tools loop with a hard cap on tool rounds."""
    llm = get_llm().bind_tools(tools)
    tool_node = ToolNode(tools, handle_tool_errors=True)   

    def call_model(state: LoopState):
        msgs = [SystemMessage(content=system_prompt)] + state["messages"]
        try:
            resp = llm.invoke(msgs)
        except Exception as e:
            if not _is_tool_format_error(e):
                raise
            log.warning("provider rejected a tool call; retrying once: %s", str(e)[:160])
            resp = llm.invoke(msgs + [HumanMessage(content=RETRY_HINT)])
        return {"messages": [resp], "rounds": state["rounds"] + (1 if resp.tool_calls else 0)}

    def route(state: LoopState):
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None) and state["rounds"] <= MAX_TOOL_ROUNDS:
            return "tools"
        return END

    g = StateGraph(LoopState)
    g.add_node("llm", call_model)
    g.add_node("tools", tool_node)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", route, {"tools": "tools", END: END})
    g.add_edge("tools", "llm")
    return g.compile()


def _parse_tool_message(m: ToolMessage) -> dict:
    try:
        data = json.loads(m.content) if isinstance(m.content, str) else m.content
    except (json.JSONDecodeError, TypeError):
        data = None
    if isinstance(data, dict) and "ok" in data:
        return {"ok": bool(data["ok"]), "error": data.get("error"),
                "retryable": bool(data.get("retryable")), "data": data.get("data")}
    is_err = getattr(m, "status", None) == "error"    
    return {"ok": not is_err, "error": str(m.content)[:300] if is_err else None,
            "retryable": False, "data": None}


def make_agent_node(name: str, tools, system_prompt: str):
    loop = build_agent_loop(tools, system_prompt)

    def node(state):
        attempts = dict(state["attempts"])
        attempts[name] = attempts.get(name, 0) + 1
        tool_results = list(state["tool_results"])
        errors = list(state["errors"])
        context = list(state["retrieved_context"])
        reports = list(state["reports"])

        status, summary = "failed", ""
        try:
            out = loop.invoke(
                {"messages": [HumanMessage(content=state["current_instruction"])], "rounds": 0},
                config={"recursion_limit": 30})
            msgs = out["messages"]
            calls = {tc["id"]: tc["args"] for m in msgs if isinstance(m, AIMessage) for tc in m.tool_calls}

            parsed = []
            for m in msgs:
                if not isinstance(m, ToolMessage):
                    continue
                p = _parse_tool_message(m)
                parsed.append(p)
                tool_results.append({"agent": name, "tool": m.name, "args": calls.get(m.tool_call_id, {}),
                                     "ok": p["ok"], "error": p["error"]})
                if not p["ok"]:
                    errors.append(f"{name}/{m.name}: {p['error']}")
                if m.name == "search_knowledge_base" and p["ok"] and p["data"]:
                    context.extend(p["data"])

            last = msgs[-1]
            if isinstance(last, AIMessage) and not last.tool_calls and message_text(last):
                summary = message_text(last)
                hard = [p for p in parsed if not p["ok"] and p["retryable"]]
                if parsed and len(hard) == len(parsed):
                    status = "failed"          
                elif hard:
                    status = "partial"
                else:
                    status = "success"       
            else:
                summary = "The agent could not finish within the tool-call limit."
                errors.append(f"{name}: tool-call limit reached")
        except Exception as e:
            log.warning("%s agent crashed: %s", name, str(e)[:200])
            summary = f"The {name} agent crashed: {type(e).__name__}"
            errors.append(f"{name}: {summary} - {str(e)[:160]}")

        reports.append({"agent": name, "status": status, "summary": summary, "attempt": attempts[name]})
        return {"attempts": attempts, "tool_results": tool_results, "errors": errors,
                "retrieved_context": context, "reports": reports}

    return node