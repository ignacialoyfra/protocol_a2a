from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

app = FastAPI()

AGENT_CARD = {
    "name": "nlp-summarizer",
    "version": "1.0.0",
    "description": "Resume textos cortos en español",
    "url": "http://localhost:8001",
    "skills": [
        {"name": "summarize",
         "input_schema": {"text": "string"},
         "output_schema": {"summary": "string"}}
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
    if req.skill != "summarize":
        return {"ok": False, "error": f"skill '{req.skill}' not supported"}

    text = req.input.get("text", "")
    summary = (text[:200] + "…") if len(text) > 200 else text
    return {"ok": True, "output": {"summary": summary}}
