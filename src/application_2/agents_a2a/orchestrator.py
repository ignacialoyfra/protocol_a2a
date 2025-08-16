# orchestrator.py  — versión robusta con trazas, retries y timeouts
from __future__ import annotations
import json, time, uuid, os, math
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.runnables.config import RunnableConfig
import requests

# ==== CONFIG ====
SEARCH_URL   = os.getenv("A2A_SEARCH_URL",   "http://127.0.0.1:8001")
ANALYSIS_URL = os.getenv("A2A_ANALYSIS_URL", "http://127.0.0.1:8002")
RESPONSE_URL = os.getenv("A2A_RESPONSE_URL", "http://127.0.0.1:8003")

# timeout y reintentos para llamadas a agentes
A2A_TIMEOUT_SEC   = int(os.getenv("A2A_TIMEOUT_SEC", "300"))   # 300s para cubrir cold-start de Ollama
A2A_MAX_RETRIES   = int(os.getenv("A2A_MAX_RETRIES", "3"))
A2A_BACKOFF_START = float(os.getenv("A2A_BACKOFF_START", "1.5"))  # segundos

MAX_ITERS = int(os.getenv("SWARM_MAX_ITERS", "3"))  # evita loops

# ==== A2A CLIENT con retries/backoff ====
class A2AClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
    def ask(self, text: str) -> str:
        url = f"{self.base_url}/a2a"
        payload = {"role": "user", "content": {"type": "text", "text": text}}
        last_err = None
        for attempt in range(1, A2A_MAX_RETRIES + 1):
            try:
                r = requests.post(url, json=payload, timeout=A2A_TIMEOUT_SEC)
                r.raise_for_status()
                data = r.json()
                return data.get("content", {}).get("text", "") or json.dumps(data, ensure_ascii=False)
            except Exception as e:
                last_err = e
                # backoff exponencial suave
                time.sleep(A2A_BACKOFF_START * (2 ** (attempt - 1)))
        raise RuntimeError(f"Failed to communicate with agent at {url}. Last error: {last_err}")

# ==== ESTADO ====
class OrchestratorState(TypedDict, total=False):
    query: str
    internet_text: str
    sufficient: bool
    final_answer: str
    iteration: int
    conversation_id: str

# ==== HELPERS ====
def _try_extract_text(raw: str) -> str:
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "answer" in obj:
            return str(obj["answer"])
        if isinstance(obj, str):
            return obj
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(raw)

def _thread_id_from_config(config: Optional[RunnableConfig]) -> str:
    try:
        return config.get("configurable", {}).get("thread_id") or str(uuid.uuid4())
    except Exception:
        return str(uuid.uuid4())

def _clip(s: Optional[str], n=220) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")

def _ts():
    return time.strftime("%H:%M:%S")

# ==== NODOS ====
def node_search(state: OrchestratorState, *, config: RunnableConfig) -> OrchestratorState:
    thread_id = _thread_id_from_config(config)
    conv_id = state.get("conversation_id") or thread_id
    payload = {
        "query": state["query"],
        "output": "text",
        "conversation_id": conv_id,
    }
    client = A2AClient(SEARCH_URL)
    try:
        raw = client.ask(json.dumps(payload, ensure_ascii=False))
        text = _try_extract_text(raw)
        if not text.strip():
            text = "No se obtuvo texto desde el agente de búsqueda."
    except Exception as e:
        text = f"[search_error] {e}"
    print(f"[{_ts()}] ▶ NODE: search  | internet_text: {_clip(text)}")
    return {"internet_text": text, "iteration": state.get("iteration", 0) + 1}

def node_analysis(state: OrchestratorState, *, config: RunnableConfig) -> OrchestratorState:
    thread_id = _thread_id_from_config(config)
    conv_id = state.get("conversation_id") or thread_id
    payload = {
        "query": state["query"],
        "output": state.get("internet_text", ""),
        "conversation_id": conv_id,
    }
    client = A2AClient(ANALYSIS_URL)
    try:
        raw = client.ask(json.dumps(payload, ensure_ascii=False))
        verdict_text = _try_extract_text(raw).strip().lower()
        sufficient = verdict_text.startswith("si") or verdict_text.startswith("sí") or ("\"si\"" in verdict_text)
    except Exception as e:
        sufficient = False
        verdict_text = f"[analysis_error] {e}"
    print(f"[{_ts()}] ▶ NODE: analysis  | sufficient: {sufficient}  | verdict_text: {_clip(verdict_text)}")
    return {"sufficient": sufficient}

def node_response(state: OrchestratorState, *, config: RunnableConfig) -> OrchestratorState:
    thread_id = _thread_id_from_config(config)
    conv_id = state.get("conversation_id") or thread_id
    payload = {
        "query": state["query"],
        "output": state.get("internet_text", ""),
        "conversation_id": conv_id,
    }
    client = A2AClient(RESPONSE_URL)
    try:
        raw = client.ask(json.dumps(payload, ensure_ascii=False))
        final_text = _try_extract_text(raw)
        if not final_text.strip():
            final_text = "No fue posible obtener una respuesta del agente Response."
    except Exception as e:
        final_text = f"[response_error] {e}\n\nRespuesta breve con lo disponible:\n{_clip(state.get('internet_text',''), 600)}"
    print(f"[{_ts()}] ▶ NODE: response | final_answer: {_clip(final_text, 600)}")
    return {"final_answer": final_text}

# ==== ROUTER ====
def route_from_analysis(state: OrchestratorState) -> str:
    if state.get("sufficient"):
        return "response"
    if state.get("iteration", 0) >= MAX_ITERS:
        # corte de seguridad: aunque falte info, intentamos response con lo que haya
        return "response"
    return "search"

# ==== BUILD ====
def build_app():
    builder = StateGraph(OrchestratorState)
    builder.add_node("search", node_search)
    builder.add_node("analysis", node_analysis)
    builder.add_node("response", node_response)
    builder.set_entry_point("search")
    builder.add_edge("search", "analysis")
    builder.add_conditional_edges("analysis", route_from_analysis,
                                  {"response": "response", "search": "search"})
    builder.add_edge("response", END)
    return builder.compile(checkpointer=InMemorySaver())

# ==== MAIN ====
if __name__ == "__main__":
    app = build_app()
    config: RunnableConfig = {"configurable": {"thread_id": "demo-1"}}
    init_state: OrchestratorState = {"query": "¿Cuántos vasos de agua se deben beber al día?"}

    print("\n=== STREAM DEL GRAFO EN TIEMPO REAL ===\n")
    for event in app.stream(init_state, config):
        for node, payload in event.items():
            if node == "__end__":
                print(f"[{_ts()}] ✔ GRAPH: terminado.\n")

    final_state = app.get_state(config).values
    print("=== ESTADO FINAL ===")
    print(json.dumps(final_state, ensure_ascii=False, indent=2))
