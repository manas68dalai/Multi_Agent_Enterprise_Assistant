import re
from langchain_core.messages import AIMessage, HumanMessage

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def message_text(msg) -> str:
    c = msg.content
    if isinstance(c, list):
        c = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return strip_think(c)


def last_user_text(state) -> str:
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            return message_text(m)
    return ""


def recent_chat(state, n: int = 6) -> str:
    lines = []
    for m in state["messages"][-n:]:
        if isinstance(m, HumanMessage):
            lines.append(f"User: {message_text(m)}")
        elif isinstance(m, AIMessage) and message_text(m):
            lines.append(f"Assistant: {message_text(m)}")
    return "\n".join(lines)