# orchestrator_swarm_three_agents.py
# -*- coding: utf-8 -*-
import json
import asyncio
from typing import TypedDict, List, Dict, Any, Tuple

from langgraph.graph import StateGraph
from langgraph_swarm import add_active_agent_router
import httpx

# === Config de agentes A2A ===
AGENTS = {
    "LogAgent":  "http://127.0.0.1:8011",
    "KBAgent":   "http://127.0.0.1:8012",
    "Responder": "http://127.0.0.1:8013",
}
CONV_ID = "swarm-1"

# === HTTP A2A helpers ===
ENDPOINTS: List[Tuple[str, str]] = [
    ("POST", "/messages"),  # python-a2a común
    ("POST", "/"),          # fallback
]

def _unwrap_text_from_envelope(obj: Any) -> str | None:
    """Intenta extraer texto desde distintas formas de sobres A2A."""
    if not isinstance(obj, dict):
        return None
    # 1) estándar: content.text
    if isinstance(obj.get("content"), dict):
        c = obj["content"]
        if c.get("type") == "text" and isinstance(c.get("text"), str):
            return c["text"]
    # 2) modo "parts" (varias libs devuelven esto)
    parts = obj.get("parts")
    if isinstance(parts, list) and parts:
        p0 = parts[0]
        if isinstance(p0, dict) and p0.get("type") == "text" and isinstance(p0.get("text"), str):
            return p0["text"]
    return None

async def a2a_send(base_url: str, payload_text: str, conversation_id: str) -> str:
    """
    Envía un mensaje al agente A2A y devuelve SIEMPRE el TEXTO útil.
    Si el server responde con un sobre, se abre y se retorna su 'text' interior.
    """
    payloads = [
        {"role": "user", "content": {"type": "text", "text": payload_text}, "conversation_id": conversation_id},
        {"text": payload_text, "conversation_id": conversation_id},
    ]
    async with httpx.AsyncClient(timeout=15) as client:
        last_err = ""
        for method, path in ENDPOINTS:
            url = f"{base_url}{path}"
            for p in payloads:
                try:
                    r = await client.post(url, json=p)
                    if 200 <= r.status_code < 300:
                        # 1) intenta parsear JSON y extraer el texto
                        try:
                            j = r.json()
                            inner = _unwrap_text_from_envelope(j)
                            if isinstance(inner, str):
                                return inner
                            # si no hubo sobre reconocible, devuelve el JSON como string
                            return json.dumps(j, ensure_ascii=False)
                        except Exception:
                            # 2) si no es JSON, devuelve texto plano
                            return r.text
                    else:
                        last_err = f"{method} {path} -> {r.status_code} {r.text[:200]}"
                except Exception as e:
                    last_err = f"{method} {path} -> EXC {e}"
        raise RuntimeError(f"A2A send failed to {base_url}. Last: {last_err}")

# === Estado del enjambre (incluye 'active_agent') ===
class SwarmState(TypedDict, total=False):
    messages: List[Dict[str, Any]]       # historial display
    conversation_id: str
    active_agent: str
    data: Dict[str, Any]                 # datos “cableados” entre nodos

# -------- helpers de robustez de parseo --------
def safe_json_loads(s: str) -> Dict[str, Any]:
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
        return {"raw": obj}
    except Exception:
        return {"raw": s}

def pick_pretty_snippet(d: Dict[str, Any], *keys: str) -> str:
    """Devuelve el primer valor string presente en d[keys], o serializa d."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    if "content" in d and isinstance(d["content"], dict) and isinstance(d["content"].get("text"), str):
        return d["content"]["text"]
    if "parts" in d and isinstance(d["parts"], list) and d["parts"]:
        p0 = d["parts"][0]
        if isinstance(p0, dict) and isinstance(p0.get("text"), str):
            return p0["text"]
    return json.dumps(d, ensure_ascii=False)

# === Nodos ===
async def call_log_agent(state: SwarmState) -> SwarmState:
    user_msg = state["messages"][-1]["content"]
    body = json.dumps({"query": user_msg}, ensure_ascii=False)

    # 'raw_inner' ya debería ser el TEXTO interior gracias a a2a_send
    raw_inner = await a2a_send(AGENTS["LogAgent"], body, state.get("conversation_id", CONV_ID))
    parsed_inner = safe_json_loads(raw_inner)  # debería ser el dict con ok/level/code/natural...

    next_data = {**state.get("data", {}), "log": parsed_inner}
    pretty = pick_pretty_snippet(parsed_inner, "natural", "message", "error", "raw")
    msg = f"[LogAgent] {pretty}"
    return {
        **state,
        "messages": state["messages"] + [{"role": "agent", "content": msg}],
        "data": next_data,
        "active_agent": "KBAgent",
    }

async def call_kb_agent(state: SwarmState) -> SwarmState:
    log_parsed = state.get("data", {}).get("log", {})
    code_hint  = log_parsed.get("code")
    query      = log_parsed.get("message") or pick_pretty_snippet(log_parsed, "natural", "raw")

    body = json.dumps({"query": query, "code": code_hint}, ensure_ascii=False)
    raw_inner = await a2a_send(AGENTS["KBAgent"], body, state.get("conversation_id", CONV_ID))
    parsed = safe_json_loads(raw_inner)

    next_data = {**state.get("data", {}), "kb": parsed}
    flag = "✅ encontrada" if parsed.get("found") else "❌ no encontrada"
    msg = f"[KBAgent] solución {flag} (code={parsed.get('code')})"
    return {
        **state,
        "messages": state["messages"] + [{"role": "agent", "content": msg}],
        "data": next_data,
        "active_agent": "DecideNode",
    }

async def decide_node(state: SwarmState) -> SwarmState:
    kb  = state.get("data", {}).get("kb", {})
    logp= state.get("data", {}).get("log", {})

    if kb.get("found"):
        context = {"code": kb.get("code"), "level": logp.get("level")}
        payload = {"answer": kb.get("solution"), "context": context}
    else:
        context = {"reason": "no-solution", "code": kb.get("code"), "level": logp.get("level")}
        payload = {"answer": "", "context": context}  # Responder hará fallback

    body = json.dumps(payload, ensure_ascii=False)
    raw_inner = await a2a_send(AGENTS["Responder"], body, state.get("conversation_id", CONV_ID))
    parsed = safe_json_loads(raw_inner)

    msg = f"[Responder] {pick_pretty_snippet(parsed, 'final', 'raw')}"
    next_data = {**state.get("data", {}), "final": parsed}
    return {
        **state,
        "messages": state["messages"] + [{"role": "agent", "content": msg}],
        "data": next_data,
        "active_agent": "Responder",
    }

# === Construcción del grafo ===
builder = StateGraph(SwarmState)
builder = builder.add_node("LogAgent",  call_log_agent, destinations=("KBAgent",))
builder = builder.add_node("KBAgent",   call_kb_agent,  destinations=("DecideNode",))
builder = builder.add_node("DecideNode",decide_node,    destinations=("Responder",))
builder = builder.add_node("Responder", decide_node,    destinations=("Responder",))  # idempotente

builder = add_active_agent_router(
    builder=builder,
    route_to=["LogAgent", "KBAgent", "DecideNode", "Responder"],
    default_active_agent="LogAgent",
)

app = builder.compile()

# === Demo ===
async def main():
    init: SwarmState = {
        "messages": [{"role": "user", "content": "2025-08-16 12:00:01 ERROR E1001: pipeline failed on job build-step"}],
        "conversation_id": CONV_ID,
        "active_agent": "LogAgent",
        "data": {},
    }
    out = await app.ainvoke(init)
    print("=== Conversación ===")
    for m in out["messages"]:
        role = m["role"]
        print(f"{role:>6}: {m['content']}")

if __name__ == "__main__":
    asyncio.run(main())
