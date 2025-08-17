# agent_analysis.py — OpenAI, responde "si"/"no" sí o sí
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

class AnalysisA2A(A2AServer):
    def __init__(self, host="127.0.0.1", port=8002):
        card = AgentCard(
            name="Agent Analysis",
            description="Decide si el texto basta para responder",
            url=f"http://{host}:{port}", version="1.0.0",
            skills=[AgentSkill(id="analysis", name="analysis", description="suficiencia si/no")],
            authentication=None
        )
        super().__init__(agent_card=card)
        self._memory = InMemorySaver()
        self._llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    async def _handle_async(self, message: Message) -> Message:
        try:
            try:
                parsed = json.loads(message.content.text or "{}")
            except Exception:
                parsed = {"query": message.content.text or ""}

            query = (parsed.get("query") or "").strip()
            internet_text = (parsed.get("internet_text") or "").strip()

            prompt = f"""
Pregunta: {query}

Texto disponible:
{internet_text}

¿Es suficiente para responder con claridad?
Responde exactamente "si" o "no", en minúsculas, sin explicación.
"""
            resp = await self._llm.ainvoke(prompt)
            verdict = (resp.content or "").strip().lower()
            if verdict not in ("si", "sí", "no"):
                verdict = "no"

            out = json.dumps({"sufficient": verdict}, ensure_ascii=False)
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
    run_server(AnalysisA2A(), host="127.0.0.1", port=8002)
