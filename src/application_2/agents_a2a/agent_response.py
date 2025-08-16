# from langchain_community.tools import DuckDuckGoSearchRun
# from langgraph.prebuilt import create_react_agent
# from python_a2a import A2AServer,  Message, TextContent, MessageRole, run_server, AgentCard,AgentSkill
# from langgraph.checkpoint.memory import InMemorySaver
# from langchain_ollama import ChatOllama
# from langchain_core.tools import tool
# import traceback
# import json
# from typing import Optional, Dict, Any
# from langchain_core.prompts import PromptTemplate
# import asyncio

# MODEL_ID = "qwen2.5:7b"

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


# from langchain_core.prompts import ChatPromptTemplate

# @tool
# def formulate_response(response_internet: str, query: str):
#     """Formula una respuesta final en español basada en el texto e internet y la consulta."""
#     try:
#         model = ChatOllama(model=MODEL_ID, base_url="http://127.0.0.1:11434", temperature=0.2)
#         prompt = f"""
#         Tienes el siguiente material de apoyo (texto obtenido de internet):
#         ---
#         {response_internet}
#         ---
#         Y esta solicitud del usuario:
#         ---
#         {query}
#         ---
#         Redacta una respuesta final clara y precisa, SOLO en español.
#         """
#         resp = model.invoke(prompt)  # <--- sync
#         content = getattr(resp, "content", resp)
#         return content.strip() if isinstance(content, str) else str(content).strip()
#     except Exception:
#         traceback.print_exc()
#         return "No fue posible formular la respuesta."
    
# class SearchA2A(A2AServer):
#     def __init__(self, host:str = "127.0.0.1", port: int = 8003):
#         skill = AgentSkill(
#             id='formulate_response',
#             name='formulate_response',
#             description='Use this skill to analyze information obtained from the Internet.'
#         )
#         card = AgentCard(
#             name='Agent Response',
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

#         self._model = ChatOllama(model=MODEL_ID, base_url="http://127.0.0.1:11434", temperature=0.2)

#         system_prompt = ChatPromptTemplate.from_messages([
#             ("system",
#              "Eres un agente que formula la respuesta final en español, usando únicamente la tool 'formulate_response'.")
#         ])

#         self._agent = create_react_agent(
#             self._model,
#             tools=[formulate_response],
#             prompt=system_prompt,     # <--- AQUÍ va el system
#             name="AgentResponse",
#             checkpointer=self._memory
#         )
#         self._initialized = True

#     async def _handle_async(self, message: Message) -> Message:
#         await self._ensure_initialized_async()
#         try:
#             parsed = self._parse_message(message)
#             user_query = parsed["query"]
#             internet_text = parsed["output"]
#             conv_id = parsed["conversation_id"] or (message.conversation_id or "default")
#             cfg = {"configurable": {"thread_id": conv_id}}

#             # SOLO mensajes de usuario
#             result = await self._agent.ainvoke(
#                 {
#                     "messages": [
#                         {"role": "user", "content": f"Consulta del usuario:\n{user_query}"},
#                         {"role": "user", "content": f"Texto de internet:\n{internet_text}"},
#                         {"role": "user", "content": "Usa la herramienta para redactar la respuesta final en español."}
#                     ]
#                 },
#                 cfg
#             )

#             answer_text = None
#             if isinstance(result, dict) and "messages" in result:
#                 msgs = result["messages"]
#                 if msgs and hasattr(msgs[-1], "content"):
#                     answer_text = getattr(msgs[-1], "content", None)
#                 elif msgs and isinstance(msgs[-1], dict):
#                     answer_text = msgs[-1].get("content")
#             if not answer_text or not str(answer_text).strip():
#                 answer_text = "No fue posible formular la respuesta."

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
#     host, port = "127.0.0.1", 8003
#     print(f"🚀 Agent A2A Response escuchando en http://{host}:{port}")
#     run_server(SearchA2A(host=host, port=port), host=host, port=port)

# agent_response.py
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
MODEL_CALL_TIMEOUT = int(os.getenv("AGENT_MODEL_TIMEOUT_SEC", "90"))

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
def formulate_response(response_internet: str, query: str) -> str:
    """Redacta una respuesta final en español, clara y precisa, usando el texto de internet."""
    try:
        # Aquí podrías usar otro modelo, plantillas, etc. Para el ejemplo, concatenamos:
        base = (response_internet or "").strip()
        q = (query or "").strip()
        if not base:
            return "No fue posible formular la respuesta."
        return f"{base}\n\nRespuesta a la consulta: {q}\n\nEn resumen: {base}"
    except Exception:
        return "No fue posible formular la respuesta."

class ResponseA2A(A2AServer):
    def __init__(self, host: str = "127.0.0.1", port: int = 8003):
        skill = AgentSkill(
            id="formulate_response",
            name="formulate_response",
            description="Formula la respuesta final en español con el material de internet.",
        )
        card = AgentCard(
            name="Agent Response",
            description="Agente que redacta la respuesta final basada en el texto de internet.",
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
        self._model = ChatOllama(
            model=MODEL_ID,
            base_url=OLLAMA_URL,
            temperature=0.2,
        ).bind_tools([formulate_response])
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

            messages = [
                SystemMessage(content="Eres un agente que formula la respuesta final SOLO en español, clara y precisa. "
                                      "Usa la herramienta 'formulate_response' si lo consideras útil."),
                HumanMessage(content=f"Consulta del usuario:\n{query}"),
                HumanMessage(content=f"Texto de internet:\n{internet_text}"),
            ]

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
        #         ai = await self._model.ainvoke(messages)
        #         if isinstance(ai, AIMessage) and ai.tool_calls:
        #             for call in ai.tool_calls:
        #                 name = call.get("name"); args = call.get("args", {}) or {}; call_id = call.get("id")
        #                 result = formulate_response.invoke(**args) if name=="formulate_response" else f"Tool '{name}' no encontrada."
        #                 messages.append(ai)
        #                 messages.append(ToolMessage(content=str(result), tool_call_id=call_id))
        #             continue

        #         final_text = (ai.content or "").strip() if isinstance(ai, AIMessage) else str(ai).strip()
        #         if not final_text:
        #             final_text = "No fue posible formular la respuesta."
        #         out_text = json.dumps({"answer": final_text}, ensure_ascii=False)
        #         return Message(
        #             content=TextContent(text=out_text),
        #             role=MessageRole.AGENT,
        #             parent_message_id=message.message_id,
        #             conversation_id=message.conversation_id,
        #         )

        #     # Corte de seguridad
        #     out_text = json.dumps({"answer": "No fue posible formular la respuesta."}, ensure_ascii=False)
        #     return Message(
        #         content=TextContent(text=out_text),
        #         role=MessageRole.AGENT,
        #         parent_message_id=message.message_id,
        #         conversation_id=message.conversation_id,
        #     )

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
    host, port = "127.0.0.1", 8003
    print(f"🚀 Agent A2A Response escuchando en http://{host}:{port}")
    run_server(ResponseA2A(host=host, port=port), host=host, port=port)
