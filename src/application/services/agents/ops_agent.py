from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

app = FastAPI()

AGENT_CARD = {
    "name": "ops-diagnoser",
    "version": "1.0.0",
    "description": "Diagnostica logs de despliegue",
    "url": "http://localhost:8002",
    "skills": [
        {"name": "diagnose_logs",
         "input_schema": {"logs": "string"},
         "output_schema": {"diagnosis": "string"}}
    ],
    "auth": {"scheme": "none"}
}

@app.get("/.well-known/agent.json")
def agent_card():
    return AGENT_CARD

class TaskCreate(BaseModel):
    skill: str
    input: Dict[str, Any] = {}

@app.post("/task.create")
def task_create(req: TaskCreate):
    if req.skill != "diagnose_logs":
        return {"ok": False, "error": f"skill '{req.skill}' not supported"}

    logs = req.input.get("logs", "")
    diag = "TIMEOUT y PERMISSION_DENIED" if "ERROR" in logs.upper() else "OK"
    return {"ok": True, "output": {"diagnosis": diag}}
