from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]   
    user_id: str                  
    next_agent: str               
    current_instruction: str
    route_reason: str
    step_count: int
    attempts: dict
    reports: list
    retrieved_context: list
    tool_results: list
    errors: list
    route_log: list
    fallback_used: bool
    sources: list
    pending_actions: list
    approval: dict
    memories: list              
    memory_saved: list           