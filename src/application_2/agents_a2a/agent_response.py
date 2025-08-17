# agent_response.py — OpenAI, siempre entrega una respuesta útil
from __future__ import annotations
import asyncio, json, traceback
from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard, AgentSkill
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI

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

class ResponseA2A(A2AServer):
    def __init__(self, host="127.0.0.1", port=8003):
        card = AgentCard(
            name="Agent Response",
            description="Redacta la respuesta final",
            url=f"http://{host}:{port}", version="1.0.0",
            skills=[AgentSkill(id="response", name="response", description="responder al usuario")],
            authentication=None
        )
        super().__init__(agent_card=card)
        self._memory = InMemorySaver()
        self._llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)

    async def _handle_async(self, message: Message) -> Message:
        try:
            try:
                parsed = json.loads(message.content.text or "{}")
            except Exception:
                parsed = {}

            query = (parsed.get("query") or "").strip()
            internet_text = (parsed.get("internet_text") or "").strip()

            prompt = f"""
Responde en español, breve y claro.

Pregunta: {query}

Contexto disponible (puede estar vacío):
{internet_text}

- Si el contexto alcanza, responde directo.
- Si no alcanza, da la mejor respuesta general y di qué faltaría para ser más preciso.
"""
            resp = await self._llm.ainvoke(prompt)
            final_answer = (resp.content or "").strip() or "No fue posible formular la respuesta."

            out = json.dumps({"final_answer": final_answer}, ensure_ascii=False)
            print(f"############## payload ##############\n{out}")
            return Message(
                content=TextContent(text=out),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id
            )
        except Exception as e:
            err = {"error": str(e), "trace": traceback.format_exc()}
            return Message(content=TextContent(text=json.dumps(err, ensure_ascii=False)), role=MessageRole.AGENT)

    def handle_message(self, message: Message) -> Message:
        return run_async(self._handle_async(message))

if __name__ == "__main__":
    run_server(ResponseA2A(), host="127.0.0.1", port=8003)
