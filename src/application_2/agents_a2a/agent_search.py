
from __future__ import annotations
import asyncio, json, traceback, os, logging


from python_a2a import (
    A2AServer, Message, TextContent, MessageRole,
    run_server, AgentCard, AgentSkill
)
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("AgentSearch")


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
        t = threading.Thread(target=_runner, daemon=True); t.start(); t.join()
        return box.get("res")


class SearchA2A(A2AServer):
    def __init__(self, host: str = "127.0.0.1", port: int = 8001):
        skill = AgentSkill(
            id="search",
            name="search",
            description="Genera un breve resumen tipo 'resultado de búsqueda' con OpenAI"
        )
        card = AgentCard(
            name="Agent Search",
            description="Agente de búsqueda (simulada) vía OpenAI; salida normalizada",
            url=f"http://{host}:{port}",    
            version="1.0.0",
            skills=[skill],
            authentication=None
        )
        super().__init__(agent_card=card)
        self._memory = InMemorySaver()

     
        model_id = "gpt-4o-mini"
        if not os.getenv("OPENAI_API_KEY"):
            log.warning("OPENAI_API_KEY no está definida en este proceso. El agente podría fallar.")
        self._llm = ChatOpenAI(model=model_id, temperature=0.1)

   
    @staticmethod
    def _pick_query(text: str) -> str:
        try:
            obj = json.loads(text or "")
            if isinstance(obj, dict) and obj.get("query"):
                return str(obj["query"])
        except Exception:
            pass
        return text or ""

    async def _handle_async(self, message: Message) -> Message:
        try:
            raw_in = message.content.text or ""
            query = self._pick_query(raw_in).strip()
            log.info(f"[search] query='{query}' len={len(query)}")

            if not query:
                out = {"internet_text": "[search_error] la consulta llegó vacía al agente search."}
                return Message(
                    content=TextContent(text=json.dumps(out, ensure_ascii=False)),
                    role=MessageRole.AGENT,
                    parent_message_id=message.message_id,
                    conversation_id=message.conversation_id
                )

            
            system = (
                "Eres un asistente que redacta un resumen estilo 'resultado de búsqueda'. "
                "Sé conciso (3–6 líneas), neutral y útil. No inventes enlaces ni datos dudosos. "
                "Si la información puede variar, acláralo brevemente."
            )
            user = (
                "Tema/Pregunta del usuario:\n"
                f"{query}\n\n"
                "Escribe un breve resumen informativo y práctico (3–6 líneas)."
            )

         
            try:
                resp = await asyncio.wait_for(
                    self._llm.ainvoke([{"role": "system", "content": system},
                                       {"role": "user", "content": user}]),
                    timeout=120
                )
                text = (resp.content or "").strip()
                if not text:
                    text = "[search_error] el modelo devolvió contenido vacío."
            except asyncio.TimeoutError:
                text = "[search_error] timeout consultando al modelo OpenAI."
            except Exception as e:
                log.exception("Fallo OpenAI en Search")
                text = f"[search_error] fallo OpenAI: {e}"

            payload = json.dumps({"internet_text": text}, ensure_ascii=False)
            print(f"############## payload ##############\n{payload}")
            return Message(
                content=TextContent(text=payload),
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
    print(f"🚀 Agent A2A Search (OpenAI) escuchando en http://{host}:{port}")
    run_server(SearchA2A(host=host, port=port), host=host, port=port)
