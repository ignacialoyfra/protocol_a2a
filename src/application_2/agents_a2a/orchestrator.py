
from __future__ import annotations
import os, json, time, requests
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables.config import RunnableConfig

SEARCH_URL   = os.getenv("A2A_SEARCH_URL",   "http://127.0.0.1:8001")
ANALYSIS_URL = os.getenv("A2A_ANALYSIS_URL", "http://127.0.0.1:8002")
RESPONSE_URL = os.getenv("A2A_RESPONSE_URL", "http://127.0.0.1:8003")

A2A_TIMEOUT  = int(os.getenv("A2A_TIMEOUT_SEC", "120"))
MAX_ITERS    = int(os.getenv("SWARM_MAX_ITERS", "2"))

class State(TypedDict, total=False):
    query: str
    internet_text: str
    sufficient: bool
    final_answer: str
    iteration: int


def _post_a2a_envelope(url: str, user_text: str) -> dict | str:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    body = {"role": "user", "content": {"type": "text", "text": user_text}}
    r = requests.post(url, json=body, headers=headers, timeout=A2A_TIMEOUT)
    print(f"[HTTP] {url} -> {r.status_code}, len={len(r.content)}")
    brief_headers = {k: v for k, v in r.headers.items()
                     if k.lower() in ("content-type", "content-length", "transfer-encoding")}
    print("[HTTP] headers:", brief_headers)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        try:
            return json.loads(r.text)
        except Exception:
            return r.text

def _extract_agent_text(envelope: dict | str) -> str:
    """
    Extrae el texto 'útil' del envelope A2A.
    Soporta:
      - {"content":{"type":"text","text":"..."}}
      - {"parts":[{"text":"...","type":"text"}, ...], "role":"agent"}
      - string crudo
    """
    if isinstance(envelope, dict):
       
        content = envelope.get("content")
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            return content["text"]

      
        parts = envelope.get("parts")
        if isinstance(parts, list) and parts:
            first = parts[0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                return first["text"]

      
        return json.dumps(envelope, ensure_ascii=False)

  
    return str(envelope)


def _safe_json(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        return raw

def _extract_internet_text(agent_text: str) -> str:
    parsed = _safe_json(agent_text)
    if isinstance(parsed, dict) and "internet_text" in parsed:
        val = parsed["internet_text"]
        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    return str(parsed)

def _extract_sufficient(agent_text: str) -> bool:
    parsed = _safe_json(agent_text)
    if isinstance(parsed, dict):
        verdict = str(parsed.get("sufficient", "")).strip().lower()
    else:
        verdict = str(parsed).strip().lower()
    return verdict.startswith("si") or verdict.startswith("sí") or verdict == "true"

def _extract_final_answer(agent_text: str) -> str:
    parsed = _safe_json(agent_text)
    if isinstance(parsed, dict) and "final_answer" in parsed:
        val = parsed["final_answer"]
        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    return str(parsed) if parsed else "No fue posible formular la respuesta."


def node_search(state: State, *, config: RunnableConfig) -> State:
    q = state["query"]
    env = _post_a2a_envelope(SEARCH_URL, q)

    print("############## ENVELOPE search ##############")
    print(env)
    print("#############################################")

    agent_text = _extract_agent_text(env)
    internet_text = _extract_internet_text(agent_text).strip()

    print(f"[{time.strftime('%H:%M:%S')}] ▶ NODE: search  | internet_text: {internet_text[:160]}...")
    return {"internet_text": internet_text, "iteration": state.get("iteration", 0) + 1}

def node_analysis(state: State, *, config: RunnableConfig) -> State:
    payload = {"query": state["query"], "internet_text": state.get("internet_text", "")}
    env = _post_a2a_envelope(ANALYSIS_URL, json.dumps(payload, ensure_ascii=False))

    print("############## ENVELOPE analysis ############")
    print(env)
    print("#############################################")

    agent_text = _extract_agent_text(env)
    sufficient = _extract_sufficient(agent_text)

    print(f"[{time.strftime('%H:%M:%S')}] ▶ NODE: analysis | sufficient: {sufficient}")
    return {"sufficient": sufficient}

def node_response(state: State, *, config: RunnableConfig) -> State:
    payload = {"query": state["query"], "internet_text": state.get("internet_text", "")}
    env = _post_a2a_envelope(RESPONSE_URL, json.dumps(payload, ensure_ascii=False))

    print("############## ENVELOPE response ############")
    print(env)
    print("#############################################")

    agent_text = _extract_agent_text(env)
    final_answer = _extract_final_answer(agent_text)

    print(f"[{time.strftime('%H:%M:%S')}] ▶ NODE: response| final_answer: {final_answer[:240]}...")
    return {"final_answer": final_answer}

def _route_after_analysis(state: State) -> str:
    if state.get("sufficient"): return "response"
    if state.get("iteration", 0) >= MAX_ITERS: return "response"
    return "search"


def build_app():
    g = StateGraph(State)
    g.add_node("search", node_search)
    g.add_node("analysis", node_analysis)
    g.add_node("response", node_response)

    g.set_entry_point("search")
    g.add_edge("search", "analysis")
    g.add_conditional_edges("analysis", _route_after_analysis, {"search": "search", "response": "response"})
    g.add_edge("response", END)

    return g.compile(checkpointer=MemorySaver())

if __name__ == "__main__":
    app = build_app()
    config: RunnableConfig = {"configurable": {"thread_id": "thread-1"}}

    init: State = {
        "query": "¿Qué es la berberina y para que sirve?",
        "internet_text": "",
        "sufficient": False,
        "final_answer": "",
        "iteration": 0,
    }

    print("=== STREAM ===")
    for ev in app.stream(init, config=config):
        print(ev)
    print("=== FINAL ===")
    response = app.get_state(config=config).values
    print(app.get_state(config=config).values)
    print(f"\nRESPUESTA FINAL:{response.get('final_answer')}")
    
  
