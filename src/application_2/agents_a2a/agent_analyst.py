
# from __future__ import annotations
# import asyncio, json, traceback
# from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard, AgentSkill
# from langgraph.checkpoint.memory import InMemorySaver
# from langchain_openai import ChatOpenAI

# def run_async(coro):
#     try:
#         loop = asyncio.get_running_loop()
#     except RuntimeError:
#         return asyncio.run(coro)
#     else:
#         import threading
#         box = {}
#         def _runner():
#             nl = asyncio.new_event_loop()
#             asyncio.set_event_loop(nl)
#             try:
#                 box["res"] = nl.run_until_complete(coro)
#             finally:
#                 nl.close()
#         t = threading.Thread(target=_runner, daemon=True)
#         t.start()
#         t.join()
#         return box.get("res")

# class AnalysisA2A(A2AServer):
#     def __init__(self, host="127.0.0.1", port=8002):
#         card = AgentCard(
#             name="Agent Analysis",
#             description="Decide si el texto basta para responder",
#             url=f"http://{host}:{port}", version="1.0.0",
#             skills=[AgentSkill(id="analysis", name="analysis", description="suficiencia si/no")],
#             authentication=None
#         )
#         super().__init__(agent_card=card)
#         self._memory = InMemorySaver()
#         self._llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

#     async def _handle_async(self, message: Message) -> Message:
#         try:
#             try:
#                 parsed = json.loads(message.content.text or "{}")
#             except Exception:
#                 parsed = {"query": message.content.text or ""}

#             query = (parsed.get("query") or "").strip()
#             internet_text = (parsed.get("internet_text") or "").strip()

#             prompt = f"""
# Pregunta: {query}

# Texto disponible:
# {internet_text}

# ¿Es suficiente para responder con claridad?
# Responde exactamente "si" o "no", en minúsculas, sin explicación.
# """
#             resp = await self._llm.ainvoke(prompt)
#             verdict = (resp.content or "").strip().lower()
#             if verdict not in ("si", "sí", "no"):
#                 verdict = "no"

#             out = json.dumps({"sufficient": verdict}, ensure_ascii=False)
#             print(f"############## payload ##############\n{out}")
#             return Message(
#                 content=TextContent(text=out),
#                 role=MessageRole.AGENT,
#                 parent_message_id=message.message_id,
#                 conversation_id=message.conversation_id
#             )
#         except Exception as e:
#             err = {"error": str(e), "trace": traceback.format_exc()}
#             return Message(content=TextContent(text=json.dumps(err, ensure_ascii=False)), role=MessageRole.AGENT)

#     def handle_message(self, message: Message) -> Message:
#         return run_async(self._handle_async(message))

# if __name__ == "__main__":
#     run_server(AnalysisA2A(), host="127.0.0.1", port=8002)
# agent_analysis.py — ReAct Agent con tool 'check_sufficiency' (OpenAI)
from __future__ import annotations
import asyncio, json, traceback, os
from python_a2a import (
    A2AServer, Message, TextContent, MessageRole,
    run_server, AgentCard, AgentSkill
)
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# ------------------ util async bridge ------------------
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

# ------------------ TOOL: check_sufficiency ------------------
@tool
def check_sufficiency(response_internet: str, query: str) -> str:
    """
    Evalúa si 'response_internet' es suficiente para responder 'query'.
    Devuelve EXACTAMENTE 'si' o 'no' (minúsculas).
    Regla rápida + verificación LLM para robustez.
    """
    # 1) Reglas rápidas (baratas, determinísticas)
    txt = (response_internet or "").strip()
    q   = (query or "").strip()
    if not q or not txt:
        return "no"
    # muy corto suele ser insuficiente
    if len(txt) < 40:
        return "no"
    # contiene señales útiles (heurística mínima)
    signals = sum(s in txt.lower() for s in ["por", "porque", "definición", "consiste", "fue", "es", "incluye"])
    if signals >= 1 and len(txt) >= 80:
        # tentativa de 'si', pero validamos con un LLM muy barato sin creatividad
        pass
    else:
        # si se ve flojo, devolvemos no sin gastar tokens
        return "no"

    # 2) Confirmación con LLM (sin creatividad)
    try:
        model_id = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        llm = ChatOpenAI(model=model_id, temperature=0)
        prompt = f"""
Pregunta: {q}

Texto disponible:
{txt}

¿El texto es suficiente para responder con claridad?
Responde exactamente "si" o "no", en minúsculas, sin explicación.
"""
        resp = llm.invoke(prompt)
        verdict = (resp.content or "").strip().lower()
        if verdict in ("si", "sí"):
            return "si"
        return "no"
    except Exception:
        # Si falló el verificador, conservador: "no"
        return "no"

# ------------------ AGENTE A2A (ReAct) ------------------
class AnalysisA2A(A2AServer):
    def __init__(self, host="127.0.0.1", port=8002):
        card = AgentCard(
            name="Agent Analysis (ReAct)",
            description=(
                "Agente ReAct que decide si el texto basta para responder. "
                "Usa la herramienta 'check_sufficiency(response_internet, query)' y devuelve 'si' o 'no'."
            ),
            url=f"http://{host}:{port}",
            version="1.1.0",
            skills=[
                AgentSkill(
                    id="analysis",
                    name="analysis",
                    description="Evaluación de suficiencia (si/no) llamando a una tool"
                )
            ],
            authentication=None
        )
        super().__init__(agent_card=card)

        self._memory = InMemorySaver()

        # LLM del agente (razona y decide CUÁNDO llamar la tool)
        model_id = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._llm = ChatOpenAI(model=model_id, temperature=0)

        # ReAct agent con la tool registrada
        self._agent = create_react_agent(
            self._llm,
            tools=[check_sufficiency],
            name="AgentAnalysisReAct",
            checkpointer=self._memory,
        )
        

        # Instrucciones para forzar el uso de la tool y formato final
        self._system = (
            "Eres un analista que DEBE usar la herramienta "
            "`check_sufficiency(response_internet, query)` para decidir si el texto basta. "
            "Tu salida final (último mensaje) debe ser EXACTAMENTE 'si' o 'no' en minúsculas, sin explicación."
        )

    @staticmethod
    def _parse_incoming(message: Message) -> tuple[str, str]:
        """Soporta entrada JSON {'query','internet_text'} o texto plano."""
        try:
            parsed = json.loads(message.content.text or "{}")
            query = (parsed.get("query") or "").strip()
            internet_text = (parsed.get("internet_text") or "").strip()
            if not query and isinstance(parsed, str):  # si pasó un string JSON
                query = parsed
        except Exception:
            # fallback: todo el texto como 'query'
            query = (message.content.text or "").strip()
            internet_text = ""
        return query, internet_text

    async def _handle_async(self, message: Message) -> Message:
        try:
            query, internet_text = self._parse_incoming(message)

            # Diálogo para el agente ReAct. Le dejamos claro que LLAME la tool.
            user_msg = (
                "Evalúa si el texto disponible alcanza para responder con claridad la pregunta dada. "
                "Debes llamar a la herramienta `check_sufficiency(response_internet, query)` y, "
                "como ÚLTIMO mensaje, responder exactamente 'si' o 'no' (minúsculas).\n\n"
                f"Pregunta: {query}\n\nTexto disponible:\n{internet_text}"
            )

            result = await self._agent.ainvoke(
                {
                    "messages": [
                        {"role": "system", "content": self._system},
                        {"role": "user", "content": user_msg},
                    ]
                },
                {"configurable": {"thread_id": message.conversation_id or "analysis-default"}},
            )

            # Distintas formas de salida según versión de langgraph/langchain
            verdict = None
            if isinstance(result, dict) and "messages" in result:
                msgs = result["messages"]
                if msgs:
                    last = msgs[-1]
                    content = getattr(last, "content", None) if hasattr(last, "content") else last.get("content")
                    verdict = (content or "").strip().lower()
            if not verdict:
                # último recurso: string directo
                verdict = (str(result) or "").strip().lower()

            # Normalización estricta
            verdict = "si" if verdict in ("si", "sí") else "no"

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
            return Message(
                content=TextContent(text=json.dumps(err, ensure_ascii=False)),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id
            )

    def handle_message(self, message: Message) -> Message:
        return run_async(self._handle_async(message))

# ------------------ main ------------------
if __name__ == "__main__":
    host, port = "127.0.0.1", 8002
    print(f"🚀 Agent A2A Analysis (ReAct) escuchando en http://{host}:{port}")
    run_server(AnalysisA2A(host=host, port=port), host=host, port=port)
