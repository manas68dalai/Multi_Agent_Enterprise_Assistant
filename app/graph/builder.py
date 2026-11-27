import inspect
import os
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents.data import data_node
from app.agents.memory import memory_write_node, recall_node
from app.agents.research import research_node
from app.agents.supervisor import supervisor_node
from app.agents.synthesizer import synthesizer_node
from app.agents.task import task_execute_node, task_plan_node
from app.core.config import settings
from app.graph.approval import approval_node
from app.graph.state import AgentState
from app.memory.checkpointer import get_checkpointer


def _timed(name, fn):
    """Print per-node timings when GRAPH_TIMING is set. Never wrap the approval node."""
    if not os.getenv("GRAPH_TIMING"):
        return fn

    if "config" in inspect.signature(fn).parameters:
        def wrapper(state, config: RunnableConfig):
            t0 = time.time()
            out = fn(state, config)
            print(f"   [timing] {name}: {time.time() - t0:.0f}s")
            return out
    else:
        def wrapper(state):
            t0 = time.time()
            out = fn(state)
            print(f"   [timing] {name}: {time.time() - t0:.0f}s")
            return out
    return wrapper


def init_node(state: AgentState):
    """Reset per-turn fields. messages (short-term) and user_id are kept."""
    return {"next_agent": "", "current_instruction": "", "route_reason": "", "step_count": 0,
            "attempts": {}, "reports": [], "retrieved_context": [], "tool_results": [],
            "errors": [], "route_log": [], "fallback_used": False, "sources": [],
            "pending_actions": [], "approval": {}, "memories": [], "memory_saved": []}


def build_graph(checkpointer=None, enable_memory: bool | None = None):
    checkpointer = checkpointer if checkpointer is not None else get_checkpointer()
    memory_on = settings.memory_enabled if enable_memory is None else enable_memory

    g = StateGraph(AgentState)
    g.add_node("init", init_node)
    g.add_node("supervisor", _timed("supervisor", supervisor_node))
    g.add_node("research", _timed("research", research_node))
    g.add_node("data", _timed("data", data_node))
    g.add_node("task_plan", _timed("task_plan", task_plan_node))
    g.add_node("approval", approval_node)
    g.add_node("task_execute", _timed("task_execute", task_execute_node))
    g.add_node("synthesizer", _timed("synthesizer", synthesizer_node))

    g.add_edge(START, "init")
    if memory_on:
        g.add_node("recall", _timed("recall", recall_node))
        g.add_node("memory_write", _timed("memory_write", memory_write_node))
        g.add_edge("init", "recall")
        g.add_edge("recall", "supervisor")
        g.add_edge("synthesizer", "memory_write")
        g.add_edge("memory_write", END)
    else:
        g.add_edge("init", "supervisor")
        g.add_edge("synthesizer", END)

    g.add_conditional_edges(
        "supervisor", lambda s: s["next_agent"],
        {"research": "research", "data": "data", "task": "task_plan", "FINISH": "synthesizer"})
    for agent in ("research", "data"):
        g.add_edge(agent, "supervisor")
    g.add_conditional_edges(
        "task_plan", lambda s: "approval" if s["pending_actions"] else "supervisor",
        {"approval": "approval", "supervisor": "supervisor"})
    g.add_edge("approval", "task_execute")
    g.add_edge("task_execute", "supervisor")
    return g.compile(checkpointer=checkpointer)