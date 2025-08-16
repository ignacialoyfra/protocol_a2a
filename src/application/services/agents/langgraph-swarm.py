# orchestrator_single_gitlab.py
# -*- coding: utf-8 -*-
import json
import asyncio
import inspect
from typing import TypedDict, List, Dict, Any, Tuple

from langgraph.graph import StateGraph
from langgraph_swarm import add_active_agent_router

# Cliente A2A (puede ser sync o async según tu build)
from python_a2a import A2AClient
import httpx  # para fallback HTTP

# ====== CONFIG ======
A2A_URL = "http://127.0.0.1:8003"   # sin barra final; debe apuntar a tu servidor A2A que ya levantaste
CONV_ID = "swarm-1"

# endpoints comunes en distintas builds python-a2a (por si usamos fallback HTTP)
ENDPOINT_CANDIDATES: List[Tuple[str, str]] = [
    ("POST", "/messages"),
    ("POST", "/message"),
    ("POST", "/a2a/messages"),
    ("POST", "/a2a/message"),
    ("POST", "/api/messages"),
    ("POST", "/"),           # algunos servers aceptan POST /
    ("PUT",  "/messages"),   # algunos usan PUT
]

# ====== helpers ======
async def await_if_needed(x):
    """Si x es awaitable (coroutine/promise), espera y devuelve el resultado."""
    if inspect.isawaitable(x):
        return await x
    return x

def normalize_response_text(resp: Any) -> str:
    """Convierte la respuesta del agente a string, soportando JSONs típicos."""
    if isinstance(resp, str):
        return resp
    try:
        # intenta reconocer estructuras comunes
        if isinstance(resp, dict):
            if "content" in resp and isinstance(resp["content"], dict):
                c = resp["content"]
                if c.get("type") == "text" and "text" in c:
                    return str(c["text"])
            if "answer" in resp and isinstance(resp["answer"], str):
                return resp["answer"]
            if "text" in resp and isinstance(resp["text"], str):
                return resp["text"]
        return json.dumps(resp, ensure_ascii=False)
    except Exception:
        return str(resp)

async def a2a_send_resilient_http(base_url: str, text_or_json: str, conversation_id: str) -> str:
    """
    Fallback HTTP: prueba múltiples endpoints/verbos y dos payloads.
    Devuelve SIEMPRE string o lanza RuntimeError si nada funcionó.
    """
    payloads = [
        # A2A "estándar"
        {"role": "user", "content": {"type": "text", "text": text_or_json}, "conversation_id": conversation_id},
        # Minimalistas que algunos servers aceptan
        {"text": text_or_json, "conversation_id": conversation_id},
    ]
    errors: List[str] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for method, path in ENDPOINT_CANDIDATES:
            url = f"{base_url}{path}"
            for p in payloads:
                try:
                    if method == "POST":
                        r = await client.post(url, json=p)
                    elif method == "PUT":
                        r = await client.put(url, json=p)
                    else:
                        continue
                    if 200 <= r.status_code < 300:
                        try:
                            data = r.json()
                            return normalize_response_text(data)
                        except Exception:
                            return r.text
                    else:
                        errors.append(f"{method} {path} -> {r.status_code} {r.text[:160]}")
                except Exception as e:
                    errors.append(f"{method} {path} -> EXC {e}")
    raise RuntimeError(
        "No pude comunicar con el agente A2A por HTTP directo.\n"
        f"Base: {base_url}\n"
        "Últimos intentos:\n" + "\n".join(errors[-6:])
    )

# ====== estado del enjambre (¡incluye active_agent!) ======
class SwarmState(TypedDict, total=False):
    messages: List[Dict[str, Any]]   # [{"role":"user"|"agent","content": str}]
    conversation_id: str
    active_agent: str

# ====== inicializa cliente A2A ======
a2a_client = A2AClient(A2A_URL)

# ====== nodo: invoca el agente GitLab A2A ======
async def call_gitlab(state: SwarmState) -> SwarmState:
    user_msg = (state["messages"] or [])[-1]["content"]

    # cuerpo que tu agente espera por dentro (lo parsea como JSON en el 'text')
    body_for_agent = json.dumps({
        "query": user_msg,
        "output": "json",   # o "text"
        "conversation_id": state.get("conversation_id", CONV_ID),
    }, ensure_ascii=False)

    # 1) Intento con A2AClient (maneja él el endpoint real)
    try:
        resp = await await_if_needed(a2a_client.ask(body_for_agent))
        resp_text = normalize_response_text(resp)
    except Exception as e:
        # 2) Fallback HTTP resiliente
        resp_text = await a2a_send_resilient_http(
            A2A_URL, body_for_agent, state.get("conversation_id", CONV_ID)
        )

    # (Opcional) si el servidor devolvió JSON con error/trace, formatea bonito
    try:
        parsed = json.loads(resp_text)
        if isinstance(parsed, dict) and "error" in parsed:
            brief = parsed["error"]
            trace_head = "\n".join((parsed.get("trace", "").splitlines())[:6])
            resp_text = f"[A2A ERROR] {brief}\n{trace_head}\n..."
    except Exception:
        pass

    return {
        **state,
        "messages": state["messages"] + [{"role": "agent", "content": resp_text}],
        "active_agent": state.get("active_agent", "GitLabAgent"),
    }

# ====== construir grafo + router ======
builder = StateGraph(SwarmState)
builder = builder.add_node("GitLabAgent", call_gitlab, destinations=("GitLabAgent",))

builder = add_active_agent_router(
    builder=builder,
    route_to=["GitLabAgent"],
    default_active_agent="GitLabAgent",
)

app = builder.compile()

# ====== main ======
async def main():
    init_state: SwarmState = {
        "messages": [{"role": "user", "content": "¿Cuántos proyectos tengo en GitLab?"}],
        "conversation_id": CONV_ID,
        "active_agent": "GitLabAgent",
    }
    out = await app.ainvoke(init_state)
    print("Respuesta del agente GitLab:\n", out["messages"][-1]["content"])

if __name__ == "__main__":
    asyncio.run(main())
