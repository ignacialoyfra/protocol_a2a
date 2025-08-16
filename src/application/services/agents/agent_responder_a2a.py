# agent_responder_a2a.py
# -*- coding: utf-8 -*-
import json
import asyncio
from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard

FALLBACK = "No se pudo obtener una respuesta coherente en este momento."

def finalize(answer: str | None, context: dict | None = None) -> dict:
    """
    Tool simple: si answer está vacío o poco útil, devuelve fallback.
    """
    txt = (answer or "").strip()
    if len(txt) < 5:
        return {"final": FALLBACK, "fallback": True, "context": context or {}}
    low = txt.lower()
    if any(k in low for k in ["error", "exception", "unknown", "no se", "no sé", "???"]):
        return {"final": FALLBACK, "fallback": True, "context": context or {}}
    return {"final": txt, "fallback": False, "context": context or {}}

class ResponderAgent(A2AServer):
    def __init__(self, host="127.0.0.1", port=8013):
        super().__init__(AgentCard(
            name="Responder",
            description="Formatea la respuesta final con fallback estándar",
            url=f"http://{host}:{port}/",
            version="1.0.0",
        ))

    def handle_message(self, message: Message) -> Message:
        text = message.content.text if message.content and message.content.type == "text" else ""
        try:
            obj = json.loads(text) if text else {}
        except Exception:
            obj = {}
        answer  = obj.get("answer") or obj.get("solution")
        context = obj.get("context", {})
        data = finalize(answer, context)
        out = json.dumps(data, ensure_ascii=False)
        return Message(
            content=TextContent(text=out),
            role=MessageRole.AGENT,
            parent_message_id=message.message_id,
            conversation_id=message.conversation_id
        )

if __name__ == "__main__":
    run_server(ResponderAgent(), host="127.0.0.1", port=8013)
