# agent_search.py — versión simple sin LLM, invoca DuckDuckGo directamente
from __future__ import annotations
import asyncio, json, traceback
from typing import Dict, Any, Optional

from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard, AgentSkill
from langgraph.checkpoint.memory import InMemorySaver
from langchain_community.tools import DuckDuckGoSearchRun

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
        t.start()
        t.join()
        return box.get("res")

class SearchA2A(A2AServer):
    def __init__(self, host: str = "127.0.0.1", port: int = 8001):
        skill = AgentSkill(
            id='get_search',
            name='get_search',
            description='Usa esta habilidad para buscar información en Internet'
        )
        card = AgentCard(
            name='Agent Search',
            description='Agente especializado en búsquedas en Internet',
            url=f"http://{host}:{port}",  # <-- SIN /a2a al final
            version="1.0.0",
            skills=[skill],
            authentication=None
        )
        super().__init__(agent_card=card)
        self._memory = InMemorySaver()
        self._search = DuckDuckGoSearchRun()

    @staticmethod
    def _parse_message(message: Message) -> Dict[str, Any]:
        text = message.content.text if (message.content and message.content.type == "text") else ""
        try:
            obj = json.loads(text) if text else {}
            if isinstance(obj, dict) and ("query" in obj or "output" in obj or "conversation_id" in obj):
                return {
                    "query": obj.get("query", ""),
                    "output": obj.get("output", ""),
                    "conversation_id": obj.get("conversation_id"),
                }
        except Exception:
            pass
        return {"query": text or "", "output": "", "conversation_id": None}

    async def _handle_async(self, message: Message) -> Message:
        try:
            parsed = self._parse_message(message)
            user_query = parsed["query"] or parsed["output"] or ""
            # Llama directo a DuckDuckGo (sin LLM)
            try:
                result = self._search.invoke(user_query)
                # Devuelve como string plano (el orquestador ya soporta texto plano o {"answer": ...})
                out_text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            except Exception as e:
                out_text = json.dumps({"answer": f"[search_error] {e}"}, ensure_ascii=False)

            return Message(
                content=TextContent(text=out_text),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id
            )
        except Exception as e:
            err = {"error": str(e), "trace": traceback.format_exc()}
            return Message(
                content=TextContent(text=json.dumps(err, ensure_ascii=False)),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id
            )

    def handle_message(self, message: Message) -> Message:
        return run_async(self._handle_async(message))

if __name__ == "__main__":
    host, port = "127.0.0.1", 8001
    print(f"🚀 Agent A2A Search escuchando en http://{host}:{port}")
    run_server(SearchA2A(host=host, port=port), host=host, port=port)
