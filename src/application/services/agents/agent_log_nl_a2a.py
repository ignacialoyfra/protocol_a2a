# agent_log_nl_a2a.py
# -*- coding: utf-8 -*-
import re
import json
import asyncio
from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard

def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        import threading
        box = {}
        def _runner():
            nl = asyncio.new_event_loop()
            asyncio.set_event_loop(nl)
            try:
                box["res"] = nl.run_until_complete(coro)
            finally:
                nl.close()
        t = threading.Thread(target=_runner, daemon=True)
        t.start(); t.join()
        return box.get("res")

def interpret_log(text: str) -> dict:
    """
    Tool simple: interpreta un log.
    Extrae level, code (p.ej. E1234, ERR42), y mensaje.
    """
    t = (text or "").strip()
    level = "INFO"
    if re.search(r"\bERROR\b|\bERR\b|\bFATAL\b", t, re.I): level = "ERROR"
    elif re.search(r"\bWARN(ING)?\b", t, re.I):            level = "WARN"

    m_code = re.search(r"\b([A-Z]{1,4}\d{2,5})\b", t)  # E1234 / ERR42 / ABCD999
    code = m_code.group(1) if m_code else None

    # Mensaje “limpio”
    msg = re.sub(r"\s+", " ", t)
    return {
        "ok": True,
        "level": level,
        "code": code,
        "message": msg,
        "natural": f"Nivel {level}. Código {code or 'desconocido'}. Mensaje: {msg}"
    }

class LogAgent(A2AServer):
    def __init__(self, host="127.0.0.1", port=8011):
        super().__init__(AgentCard(
            name="Log Interpreter",
            description="Interpreta logs a lenguaje natural",
            url=f"http://{host}:{port}/",
            version="1.0.0",
        ))

    def handle_message(self, message: Message) -> Message:
        text = message.content.text if message.content and message.content.type == "text" else ""
        try:
            obj = json.loads(text)
            query = obj.get("query", text)
        except Exception:
            query = text

        data = interpret_log(query)
        out = json.dumps(data, ensure_ascii=False)
        return Message(
            content=TextContent(text=out),
            role=MessageRole.AGENT,
            parent_message_id=message.message_id,
            conversation_id=message.conversation_id
        )

if __name__ == "__main__":
    run_server(LogAgent(), host="127.0.0.1", port=8011)
