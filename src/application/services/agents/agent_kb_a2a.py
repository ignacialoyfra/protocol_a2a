# agent_kb_a2a.py
# -*- coding: utf-8 -*-
import re
import json
import asyncio
from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard

KB = {
    # código → solución
    "E1001": "Reinicia el runner de CI y vuelve a ejecutar el job.",
    "ERR42": "Actualiza tus credenciales; el token expiró.",
    "E429":  "Se alcanzó el rate limit. Intenta en 60 segundos.",
}

def extract_code(s: str) -> str | None:
    m = re.search(r"\b([A-Z]{1,4}\d{2,5})\b", s)
    return m.group(1) if m else None

def lookup_solution(text: str, code_hint: str | None = None) -> dict:
    """
    Tool simple: busca una solución por código; si no hay código, intenta por keywords.
    """
    code = code_hint or extract_code(text or "")
    if code and code in KB:
        return {"found": True, "code": code, "solution": KB[code]}
    # keywords brutales para demo
    low = (text or "").lower()
    if "token" in low or "oauth" in low:
        return {"found": True, "code": None, "solution": "Verifica/rota el token de acceso."}
    if "rate limit" in low or "429" in low:
        return {"found": True, "code": None, "solution": "Espera y reintenta; añade backoff exponencial."}
    return {"found": False, "code": code, "solution": None}

class KBAgent(A2AServer):
    def __init__(self, host="127.0.0.1", port=8012):
        super().__init__(AgentCard(
            name="KB Lookup",
            description="Busca una solución en una base mínima",
            url=f"http://{host}:{port}/",
            version="1.0.0",
        ))

    def handle_message(self, message: Message) -> Message:
        text = message.content.text if message.content and message.content.type == "text" else ""
        try:
            obj = json.loads(text)
            query = obj.get("query", text)
            code  = obj.get("code")
        except Exception:
            query, code = text, None

        data = lookup_solution(query, code)
        out = json.dumps(data, ensure_ascii=False)
        return Message(
            content=TextContent(text=out),
            role=MessageRole.AGENT,
            parent_message_id=message.message_id,
            conversation_id=message.conversation_id
        )

if __name__ == "__main__":
    run_server(KBAgent(), host="127.0.0.1", port=8012)
