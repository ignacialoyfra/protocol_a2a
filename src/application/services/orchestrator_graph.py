from typing import TypedDict, Dict, Any, List
import requests
from langgraph.graph import StateGraph, END

# Endpoints de tus agentes
A2A_BASES = ["http://localhost:8001", "http://localhost:8002"]

# ----- Estado del grafo
class GState(TypedDict, total=False):
    goal: str
    route: str
    cards: List[Dict[str, Any]]
    output: Dict[str, Any]

# ----- Nodo: Descubrir AgentCards
def discover(_: GState) -> Dict[str, Any]:
    cards = []
    for base in A2A_BASES:
        r = requests.get(f"{base}/.well-known/agent.json", timeout=5)
        r.raise_for_status()
        cards.append(r.json())
    return {"cards": cards}

# ----- Nodo: Router por skill (básico por keywords)
# Reemplaza el router anterior
import ollama

def router(state: GState) -> Dict[str, Any]:
    goal = state.get("goal") or ""
    # Pregunta al LLM: ¿summarize o diagnose_logs?
    resp = ollama.Client(host="http://127.0.0.1:11434").chat(
        model="llama3:8b",
        messages=[{"role":"user","content":f"Para el objetivo: '{goal}' responde SOLO 'summarize' o 'diagnose_logs'"}]
    )
    skill = resp["message"]["content"].strip().lower()
    if skill not in {"summarize","diagnose_logs"}:
        skill = "diagnose_logs"  # fallback

    for c in state["cards"]:
        if any(s.get("name") == skill for s in c.get("skills", [])):
            return {"route": f'{c["url"]}|{skill}'}
    c0 = state["cards"][0]
    return {"route": f'{c0["url"]}|{skill}'}


# ----- Función utilitaria para invocar A2A task.create
def call_a2a_task(agent_url: str, skill: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(f"{agent_url}/task.create", json={"skill": skill, "input": payload}, timeout=20)
    r.raise_for_status()
    return r.json()

# ----- Nodo: Ejecutar
def execute(state: GState) -> Dict[str, Any]:
    agent_url, skill = state["route"].split("|", 1)
    if skill == "summarize":
        payload = {"text": "Texto largo de ejemplo. " * 20}
    else:
        payload = {"logs": "INFO ok\nERROR timeout\nERROR permission denied\n"}

    res = call_a2a_task(agent_url, skill, payload)
    if not res.get("ok"):
        return {"output": {"error": res.get("error", "unknown error")}}
    return {"output": res.get("output", {})}

# ----- Nodo: Finalizar (formatear output)
def finalize(state: GState) -> Dict[str, Any]:
    out = state.get("output", {})
    if "summary" in out:
        text = f"✅ Resumen\n{out['summary']}"
    elif "diagnosis" in out:
        text = f"🩺 Diagnóstico\n{out['diagnosis']}"
    else:
        text = f"⚠️ Error\n{out.get('error','sin detalles')}"
    return {"output": {"text": text}}

# ----- Construcción del grafo
g = StateGraph(GState)
g.add_node("discover", discover)
g.add_node("router", router)
g.add_node("execute", execute)
g.add_node("finalize", finalize)

g.set_entry_point("discover")
g.add_edge("discover", "router")
g.add_edge("router", "execute")
g.add_edge("execute", "finalize")
g.add_edge("finalize", END)

app = g.compile()

if __name__ == "__main__":
    # Caso 1: debería ir a summarize
    print(app.invoke({"goal": "Quiero un resumen corto del cuento del patito feo"})["output"]["text"])
    # Caso 2: debería ir a diagnose_logs
    print(app.invoke({"goal": "Diagnosticar fallos en logs de despliegue cuando falla por falta de recursos"})["output"]["text"])
