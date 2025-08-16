# from langchain_community.tools import DuckDuckGoSearchRun
# from langgraph.prebuilt import create_react_agent
# from python_a2a import A2AServer,  Message, TextContent, MessageRole, run_server, AgentCard,AgentSkill
# from langgraph.checkpoint.memory import InMemorySaver
# from langchain_ollama import ChatOllama
# from langchain_core.tools import tool
# import traceback
# import json
# from typing import Dict, Any
# import asyncio
# from langchain_core.prompts import ChatPromptTemplate




# def run_async(coro):
#     """Ejecuta una coroutine desde contexto síncrono (compatible con varias versiones)."""
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
    
# MODEL_ID = "qwen2.5:7b"

# @tool
# def analisys_response(response_internet: str, query: str):
#     """Evalúa si el texto recibido basta para responder la consulta. Devuelve 'si' o 'no'."""
#     try:
#         model = ChatOllama(model=MODEL_ID, base_url="http://127.0.0.1:11434", temperature=0.0)
#         prompt = f"""
#         Tienes este texto de internet:
#         ---
#         {response_internet}
#         ---
#         Y esta consulta del usuario:
#         ---
#         {query}
#         ---
#         Responde exactamente 'si' o 'no' (minúsculas, sin explicaciones).
#         """
#         resp = model.invoke(prompt)
#         content = getattr(resp, "content", resp)
#         text = content.strip().lower() if isinstance(content, str) else str(content).strip().lower()
#         return text if text in ("si", "sí", "no") else "no"
#     except Exception as e:
#         traceback.print_exc()
#         return "no"
    
# class SearchA2A(A2AServer):
#     def __init__(self, host:str = "127.0.0.1", port: int = 8002):
#         skill = AgentSkill(
#             id='analisys_response',
#             name='analisys_response',
#             description='Use this skill to analyze information obtained from the Internet.'
#         )
#         card = AgentCard(
#             name='Agent Analisys',
#             description='Agent specialized in analyzing information obtained from the Internet',
#             url=f"http://{host}:{port}/",
#             version="1.0.0",
#             skills=[skill],
#             authentication=None
#         )
#         super().__init__(agent_card=card)

#         super().__init__(agent_card=card)
#         self._initialized = False
#         self._agent = None
#         self._model = None
#         self._memory = InMemorySaver()


#     @staticmethod
#     def _parse_message(message: Message) -> Dict[str, Any]:
#         """
#         Acepta texto plano o JSON con llaves: query, output, conversation_id.
#         Si viene texto plano, lo toma como 'query'.
#         """
#         text = message.content.text if (message.content and message.content.type == "text") else ""
#         try:
#             obj = json.loads(text) if text else {}
#             if isinstance(obj, dict) and (
#                 "query" in obj or "output" in obj or "conversation_id" in obj
#             ):
#                 return {
#                     "query": obj.get("query", ""),
#                     "output": obj.get("output", ""),
#                     "conversation_id": obj.get("conversation_id"),
#                 }
#         except Exception:
#             pass
#         return {"query": text or "", "output": "", "conversation_id": None}
    
#     async def _ensure_initialized_async(self):
#         if self._initialized:
#             return

#         self._model = ChatOllama(model=MODEL_ID, base_url="http://127.0.0.1:11434", temperature=0.0)
#         # Usa un prompt de sistema al crear el agente (NO vuelvas a usar 'system' en runtime)
#         system_prompt = ChatPromptTemplate.from_messages([
#             ("system",
#              "Eres un agente que decide si el texto obtenido de internet es suficiente para responder la consulta. "
#              "Solo usarás la herramienta 'analisys_response' y devolverás exactamente 'si' o 'no'.")
#         ])

#         self._agent = create_react_agent(
#             self._model,
#             tools=[analisys_response],
#             prompt=system_prompt,     # <--- AQUÍ va el system
#             name="AgentAnalysis",
#             checkpointer=self._memory
#         )
#         self._initialized = True

#     async def _handle_async(self, message: Message) -> Message:
#         await self._ensure_initialized_async()
#         try:
#             parsed = self._parse_message(message)
#             user_query = parsed["query"]
#             internet_text = parsed["output"]  # aquí, tu orquestador mete el texto en 'output'
#             conv_id = parsed["conversation_id"] or (message.conversation_id or "default")
#             cfg = {"configurable": {"thread_id": conv_id}}

#             # SOLO mensajes de usuario (nada 'system' aquí)
#             result = await self._agent.ainvoke(
#                 {
#                     "messages": [
#                         {"role": "user", "content": f"Consulta del usuario:\n{user_query}"},
#                         {"role": "user", "content": f"Texto de internet:\n{internet_text}"},
#                         {"role": "user", "content": "Evalúa con la herramienta y responde 'si' o 'no'."}
#                     ]
#                 },
#                 cfg
#             )

#             # ... resto igual que tenías para extraer answer_text ...
#             # (omito por brevedad; solo asegúrate de NO llamar a finalize_or_fallback si no lo tienes)
#             answer_text = None
#             if isinstance(result, dict) and "messages" in result:
#                 msgs = result["messages"]
#                 if msgs and hasattr(msgs[-1], "content"):
#                     answer_text = getattr(msgs[-1], "content", None)
#                 elif msgs and isinstance(msgs[-1], dict):
#                     answer_text = msgs[-1].get("content")
#             if not answer_text or not str(answer_text).strip():
#                 answer_text = "no"  # por defecto
#             out_text = json.dumps({"answer": answer_text}, ensure_ascii=False)
#             return Message(
#                 content=TextContent(text=out_text),
#                 role=MessageRole.AGENT,
#                 parent_message_id=message.message_id,
#                 conversation_id=message.conversation_id
#             )
#         except Exception as e:
#             err = {"error": str(e), "trace": traceback.format_exc()}
#             return Message(
#                 content=TextContent(text=json.dumps(err, ensure_ascii=False)),
#                 role=MessageRole.AGENT,
#                 parent_message_id=message.message_id,
#                 conversation_id=message.conversation_id
#             )
        
#     def handle_message(self, message: Message) -> Message:
#         return run_async(self._handle_async(message))


# if __name__ == "__main__":
#     host, port = "127.0.0.1", 8002
#     print(f"🚀 Agent A2A Analisys escuchando en http://{host}:{port}")
#     run_server(SearchA2A(host=host, port=port), host=host, port=port)


# agent_analysis.py
from __future__ import annotations
import asyncio, json, traceback
from typing import Dict, Any, Optional
import os
from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard, AgentSkill
from langgraph.checkpoint.memory import InMemorySaver
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage


MODEL_ID = "qwen2.5:7b"
OLLAMA_URL = "http://127.0.0.1:11434"
MAX_TOOL_STEPS = int(os.getenv("AGENT_MAX_TOOL_STEPS", "3"))
MODEL_CALL_TIMEOUT = int(os.getenv("AGENT_MODEL_TIMEOUT_SEC", "90"))          # evita loops

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

@tool
def analisys_response(response_internet: str, query: str) -> str:
    """Evalúa si el texto recibido basta para responder la consulta. Devuelve 'si' o 'no'."""
    try:
        # Heurística simple (puedes poner tu lógica real aquí)
        txt = (response_internet or "").strip().lower()
        q = (query or "").strip().lower()
        # Si hay texto y la consulta no está vacía, retornamos 'si' (ajusta a tu criterio)
        return "si" if (len(txt) > 10 and len(q) > 0) else "no"
    except Exception:
        return "no"

class AnalysisA2A(A2AServer):
    def __init__(self, host: str = "127.0.0.1", port: int = 8002):
        skill = AgentSkill(
            id="analisys_response",
            name="analisys_response",
            description="Usa esta habilidad para decidir si el texto de internet es suficiente ('si'/'no').",
        )
        card = AgentCard(
            name="Agent Analysis",
            description="Decide si la información es suficiente para responder.",
            url=f"http://{host}:{port}/",
            version="1.0.0",
            skills=[skill],
            authentication=None,
        )
        super().__init__(agent_card=card)

        self._initialized = False
        self._model = None
        self._memory = InMemorySaver()

    async def _ensure_initialized_async(self):
        if self._initialized:
            return
        # LLM con soporte de tools
        self._model = ChatOllama(
            model=MODEL_ID,
            base_url=OLLAMA_URL,
            temperature=0.0,
        ).bind_tools([analisys_response])
        self._initialized = True

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
        await self._ensure_initialized_async()
        try:
            parsed = self._parse_message(message)
            query = parsed["query"]
            internet_text = parsed["output"]
            conv_id = parsed["conversation_id"] or (message.conversation_id or "default")

            # Construimos historial inicial (system + user)
            messages = [
                SystemMessage(content="Eres un agente que decide si el texto obtenido de internet es suficiente. Responde 'si' o 'no'."),
                HumanMessage(content=f"Consulta del usuario:\n{query}"),
                HumanMessage(content=f"Texto de internet:\n{internet_text}"),
                HumanMessage(content="Usa la herramienta si es necesario y responde exactamente 'si' o 'no'."),
            ]

            # Bucle de tool-calling manual
            steps = 0
            while steps < MAX_TOOL_STEPS:
                try:
                    ai = await asyncio.wait_for(self._model.ainvoke(messages), timeout=MODEL_CALL_TIMEOUT)
                except asyncio.TimeoutError:
                    # responder algo y cortar
                    final_text = "Lo siento, la generación tomó demasiado tiempo."
                    out_text = json.dumps({"answer": final_text}, ensure_ascii=False)
                    return Message(content=TextContent(text=out_text), role=MessageRole.AGENT,
                                parent_message_id=message.message_id, conversation_id=message.conversation_id)
                # ai = await self._model.ainvoke(messages)  # AIMessage (puede traer tool_calls)
                # if isinstance(ai, AIMessage) and ai.tool_calls:
                #     # Ejecutamos cada tool_call y devolvemos ToolMessage correspondiente
                #     for call in ai.tool_calls:
                #         name = call.get("name")
                #         args = call.get("args", {}) or {}
                #         call_id = call.get("id")

                #         if name == "analisys_response":
                #             result = analisys_response.invoke(**args)
                #         else:
                #             result = f"Tool '{name}' no encontrada."

                #         messages.append(ai)  # agregamos la respuesta que pide tool
                #         messages.append(ToolMessage(content=str(result), tool_call_id=call_id))
                #     steps += 1
                #     continue  # vuelve a preguntar al modelo con el ToolMessage agregado

                # # Si no hay más tool_calls, tomamos el contenido final del modelo
                # final_text = (ai.content or "").strip() if isinstance(ai, AIMessage) else str(ai).strip()
                # if final_text.lower() not in ("si", "sí", "no"):
                #     final_text = "no"
                # out_text = json.dumps({"answer": final_text}, ensure_ascii=False)
                # return Message(
                #     content=TextContent(text=out_text),
                #     role=MessageRole.AGENT,
                #     parent_message_id=message.message_id,
                #     conversation_id=message.conversation_id,
                # )

            # Corte de seguridad: si se exceden pasos, devolvemos 'no'
            # out_text = json.dumps({"answer": "no"}, ensure_ascii=False)
            # return Message(
            #     content=TextContent(text=out_text),
            #     role=MessageRole.AGENT,
            #     parent_message_id=message.message_id,
            #     conversation_id=message.conversation_id,
            # )

        except Exception as e:
            err = {"error": str(e), "trace": traceback.format_exc()}
            return Message(
                content=TextContent(text=json.dumps(err, ensure_ascii=False)),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id,
            )

    def handle_message(self, message: Message) -> Message:
        return run_async(self._handle_async(message))

if __name__ == "__main__":
    host, port = "127.0.0.1", 8002
    print(f"🚀 Agent A2A Analysis escuchando en http://{host}:{port}")
    run_server(AnalysisA2A(host=host, port=port), host=host, port=port)
