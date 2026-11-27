import json
import os
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="Enterprise Assistant", layout="wide")

DEFAULT_URL = os.getenv("API_URL", "http://localhost:8000")
DEFAULT_KEY = os.getenv("API_KEY", "")


def new_session_id() -> str:
    return datetime.now().strftime("chat-%Y%m%d-%H%M%S")


ss = st.session_state
ss.setdefault("session_id", new_session_id())
ss.setdefault("loaded_session", ss["session_id"])
ss.setdefault("messages", [])
ss.setdefault("pending", None)

# ------------------------------------------------------------------ connection
with st.sidebar:
    st.title("Enterprise Assistant")
    api_url = st.text_input("API URL", DEFAULT_URL).rstrip("/")
    api_key = st.text_input("API key", DEFAULT_KEY, type="password")


def call(method: str, path: str, **kw):
    try:
        return requests.request(method, api_url + path, headers={"X-API-Key": api_key},
                                timeout=kw.pop("timeout", 30), **kw)
    except requests.RequestException as e:
        st.error(f"Cannot reach the API at {api_url}: {e}")
        st.stop()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_json(url: str, key: str, path: str):
    r = requests.get(url + path, headers={"X-API-Key": key}, timeout=10)
    return r.status_code, (r.json() if "json" in r.headers.get("content-type", "") else {})


try:
    code, me = fetch_json(api_url, api_key, "/me")
except requests.RequestException as e:
    st.error(f"Cannot reach the API at {api_url}: {e}")
    st.stop()
if code != 200:
    st.error("Enter a valid API key in the sidebar." if code == 401 else f"API error {code}: {me}")
    st.stop()

try:
    _, health = fetch_json(api_url, api_key, "/health")
except requests.RequestException:
    health = {}
with st.sidebar:
    st.success(f"Signed in as **{me['user_id']}**" + (" (admin)" if me.get("is_admin") else ""))
    if health:
        st.caption(f"Model: {health.get('llm')} | status: {health.get('status')}")


# ------------------------------------------------------------------ SSE helpers
def sse_events(resp):
    event, data = "message", []
    for line in resp.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())


def describe(event: str, d: dict):
    if event == "memory_recalled" and d.get("memories"):
        return f"Recalled {len(d['memories'])} thing(s) I know about you"
    if event == "route":
        if d["next"] == "FINISH":
            return f"Supervisor: finish. {d.get('reason') or ''}"
        return f"Supervisor chose **{d['next']}**: {d.get('reason') or ''}"
    if event == "agent":
        text = f"**{d['agent']}** agent ({d.get('status')}): {(d.get('summary') or '')[:220]}"
        for t in d.get("tool_calls", []):
            res = "ok" if t["ok"] else f"ERROR: {t.get('error')}"
            text += f"  \n&nbsp;&nbsp;`{t['tool']}({json.dumps(t['args'])})` -> {res}"
        return text
    if event == "proposal":
        return "Proposed a change that needs your approval"
    if event == "memory_saved" and d.get("memories"):
        return "Remembered: " + "; ".join(d["memories"])
    return None


def _detail(resp):
    try:
        return resp.json().get("detail")
    except ValueError:
        return resp.text[:300]


def run_stream(path: str, payload: dict):
    """POST to a streaming endpoint, show progress live, and return the final 'done' payload."""
    steps, final = [], None
    with st.status("Working on it...", expanded=True) as box:
        try:
            with requests.post(api_url + path, json=payload, headers={"X-API-Key": api_key},
                               stream=True, timeout=(10, 300)) as resp:
                if resp.status_code != 200:
                    detail = _detail(resp)
                    if isinstance(detail, dict) and detail.get("error") == "approval_pending":
                        ss.pending = detail["pending_actions"]
                        box.update(label="Approval needed", state="error")
                    else:
                        box.update(label="Request failed", state="error")
                        st.error(f"{resp.status_code}: {detail}")
                    return None
                resp.encoding = "utf-8"
                for event, data in sse_events(resp):
                    line = describe(event, data)
                    if line:
                        steps.append(line)
                        st.markdown(line)
                    if event == "error":
                        box.update(label="Failed", state="error")
                        st.error(data.get("message", "Error"))
                        return None
                    if event == "done":
                        final = data
        except requests.RequestException as e:
            box.update(label="Connection lost", state="error")
            st.error(str(e))
            return None
        box.update(label="Done", state="complete", expanded=False)
    if final:
        final["steps"] = steps
    return final


def finish_turn(final):
    if not final:
        return
    ss.session_id = ss.loaded_session = final["session_id"]
    if final["status"] == "approval_required":
        ss.pending = final["pending_actions"]
    else:
        ss.pending = None
        ss.messages.append({"role": "assistant", "content": final.get("answer") or "(no answer)", "meta": final})


def render_meta(meta: dict):
    agents = " -> ".join(meta.get("agents") or []) or "no agent needed"
    tokens = (meta.get("usage") or {}).get("total_tokens")
    st.caption(f"Handled by: {agents}  |  {meta.get('latency_s', '?')}s" + (f"  |  {tokens} tokens" if tokens else ""))
    if meta.get("fallback_used"):
        st.warning("A retry or step limit was hit, so this answer may be incomplete.")
    with st.expander("How this was answered"):
        for s in meta.get("steps", []):
            st.markdown(s)
        tools = meta.get("tool_calls") or []
        if tools:
            st.markdown("**Tool calls**")
            for t in tools:
                res = "ok" if t["ok"] else f"ERROR: {t.get('error')}"
                st.code(f"[{t['agent']}] {t['tool']}({json.dumps(t['args'])}) -> {res}", language="text")
        if meta.get("sources"):
            st.markdown("**Sources:** " + ", ".join(meta["sources"]))
        if meta.get("memories_used"):
            st.markdown("**Memories used:** " + "; ".join(meta["memories_used"]))
        if meta.get("memories_saved"):
            st.markdown("**Remembered:** " + "; ".join(meta["memories_saved"]))


# ------------------------------------------------------------------ sidebar: conversations, memory, admin
with st.sidebar:
    st.divider()
    if st.button("New chat", use_container_width=True):
        ss.session_id = new_session_id()
        ss.messages, ss.pending = [], None
        ss.loaded_session = ss.session_id
        st.rerun()

    r = call("GET", "/sessions")
    past = r.json().get("sessions", []) if r.status_code == 200 else []
    options = [ss.session_id] + [s for s in past if s != ss.session_id]
    chosen = st.selectbox("Conversation", options, index=0)
    if chosen != ss.session_id:
        ss.session_id = chosen
        st.rerun()

    with st.expander("My memory"):
        if st.button("Show what you remember about me"):
            items = call("GET", "/memory").json().get("memories", [])
            if not items:
                st.caption("Nothing stored yet.")
            for m in items:
                st.markdown(f"- {m['text']}  \n  _{m.get('kind', '')}_")
        sure = st.checkbox("I want to delete all my memories")
        if st.button("Forget me", disabled=not sure):
            st.success(f"Deleted {call('DELETE', '/memory').json().get('deleted', 0)} memories")

    if me.get("is_admin"):
        with st.expander("Knowledge base (admin)"):
            up = st.file_uploader("Upload PDF / MD / TXT", type=["pdf", "md", "txt"])
            doc_type = st.selectbox("Category", ["hr", "it", "finance", "general"])
            if up and st.button("Ingest document"):
                r = call("POST", "/ingest", timeout=300, data={"doc_type": doc_type},
                         files={"file": (up.name, up.getvalue(), up.type or "application/octet-stream")})
                if r.status_code == 200:
                    st.success(f"Ingested {r.json()['chunks']} chunks from {up.name}")
                else:
                    st.error(f"{r.status_code}: {_detail(r)}")

# ------------------------------------------------------------------ load a past conversation
if ss.session_id != ss.loaded_session:
    r = call("GET", f"/history/{ss.session_id}")
    if r.status_code == 200:
        h = r.json()
        ss.messages = [{"role": m["role"], "content": m["content"]} for m in h["messages"]]
        ss.pending = h["pending_actions"] or None
    else:
        ss.messages, ss.pending = [], None
    ss.loaded_session = ss.session_id

# ------------------------------------------------------------------ main chat area
st.subheader("Ask about policies, customers, orders and tickets")
for m in ss.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("meta"):
            render_meta(m["meta"])

if ss.pending:
    with st.chat_message("assistant"):
        st.warning("This needs your approval before anything is changed.")
        for a in ss.pending:
            st.markdown(f"**{a['tool']}**")
            st.json(a["args"])
        c1, c2, _ = st.columns([1, 1, 4])
        approve_clicked = c1.button("Approve", type="primary")
        reject_clicked = c2.button("Reject")
    if approve_clicked or reject_clicked:
        ss.pending = None
        finish_turn(run_stream("/approve/stream", {"session_id": ss.session_id, "approved": bool(approve_clicked)}))
        st.rerun()

prompt = st.chat_input("Type your question...", disabled=bool(ss.pending))
if prompt:
    ss.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    finish_turn(run_stream("/chat/stream", {"message": prompt, "session_id": ss.session_id}))
    st.rerun()