# -*- coding: utf-8 -*-
import os
import json
import asyncio
import logging
import traceback
from typing import Optional, Dict, Any

# ---- A2A (usar forma mínima para compat) ----
from python_a2a import A2AServer, Message, TextContent, MessageRole, run_server, AgentCard

# ---- LLM + LangGraph ----
from langchain_aws.chat_models import ChatBedrock
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

# ---- MCP ----
from langchain_mcp_adapters.client import MultiServerMCPClient

# ---- Tool personalizada (LangChain) ----
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gitlab-a2a")

PROMPT = (
    "Eres un agente de GitLab. "
    "Usa EXCLUSIVAMENTE las herramientas MCP disponibles. "
    "Nunca pidas credenciales al usuario. "
    "Si no existe una tool para algo, dilo explícitamente. "
    "Al finalizar tu respuesta, utiliza la tool 'finalize_or_fallback' pasándole tu respuesta propuesta."
)

# -------- tool personalizada ----------
@tool("finalize_or_fallback", return_direct=False)
def finalize_or_fallback(answer: str) -> str:
    """
    Revisa la respuesta propuesta. Si es vacía, genérica o poco útil,
    devuelve el mensaje estándar de fallback: 
    'No se pudo obtener una respuesta coherente en este momento.'.
    Si es razonable, devuelve la misma respuesta.
    """
    if not answer:
        return "No se pudo obtener una respuesta coherente en este momento."
    t = answer.strip()
    if len(t) < 5:
        return "No se pudo obtener una respuesta coherente en este momento."

    low = t.lower()
    red_flags = [
        "no sé", "no se", "no tengo información", "no puedo acceder",
        "error", "exception", "traceback", "unknown", "???"
    ]
    if any(k in low for k in red_flags):
        return "No se pudo obtener una respuesta coherente en este momento."
    return t

# -------- util: correr async desde handler sync --------
def run_async(coro):
    """Ejecuta una coroutine desde contexto síncrono (compatible con varias versiones)."""
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

class GitLabA2A(A2AServer):
    """
    Servidor A2A que envuelve tu agente LangGraph + MCP.
    Soporta:
      - Texto plano
      - JSON: {"query": "...", "conversation_id": "...", "output": "json"|"text"}
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8003):
        card = AgentCard(
            name="GitLab MCP Agent",
            description="Consultas a GitLab vía MCP; incluye fallback estandarizado.",
            url=f"http://{host}:{port}/",
            version="1.0.0",
        )
        super().__init__(agent_card=card)

        self._initialized = False
        self._agent = None
        self._model = None
        self._memory = InMemorySaver()
        self._tools = None

    # ---- init real (async) ----
    async def _ensure_initialized_async(self):
        if self._initialized:
            return

        # mismas conexiones MCP que tu script “que funciona”
        client = MultiServerMCPClient({
            "gitlab_extra_py": {
                "command": "python",
                "args": ["gitlab_sidecar.py"],
                "transport": "stdio",
                "env": {
                    "GITLAB_API_URL": "https://gitlab.com/api/v4",
                    "GITLAB_PERSONAL_ACCESS_TOKEN": os.environ["GITLAB_PERSONAL_ACCESS_TOKEN"],
                },
            },
            "gitlab_mcp": {
                "command": "docker",
                "args": [
                    "run", "--rm", "-i",
                    "-e", "GITLAB_API_URL=https://gitlab.com/api/v4",
                    "-e", f"GITLAB_PERSONAL_ACCESS_TOKEN={os.environ['GITLAB_PERSONAL_ACCESS_TOKEN']}",
                    "mcp/gitlab"
                ],
                "transport": "stdio"
            }
        })

        tools = await client.get_tools()           # <- igual que tu main()
        log.info("Herramientas MCP: %s", tools)

        self._model = ChatBedrock(
            model="anthropic.claude-3-haiku-20240307-v1:0",
            region="us-east-1"
        )

        # añadimos la tool personalizada además de las MCP
        all_tools = [finalize_or_fallback]
        self._agent = create_react_agent(
            self._model,
            tools=all_tools,
            prompt=PROMPT,
            name="GitLabReAct",
            checkpointer=self._memory
        )
        self._initialized = True

    # ---- helper: parsea entrada del mensaje A2A ----
    @staticmethod
    def _parse_message(message: Message) -> Dict[str, Any]:
        text = message.content.text if (message.content and message.content.type == "text") else ""
        # permite JSON o texto plano
        try:
            obj = json.loads(text) if text else {}
            if isinstance(obj, dict) and ("query" in obj or "output" in obj or "conversation_id" in obj):
                return {
                    "query": obj.get("query", ""),
                    "conversation_id": obj.get("conversation_id"),
                    "output": obj.get("output", "text"),
                }
        except Exception:
            pass
        return {"query": text or "", "conversation_id": None, "output": "text"}

    # ---- ejecución real (async) ----
    async def _handle_async(self, message: Message) -> Message:
        await self._ensure_initialized_async()

        try:
            parsed = self._parse_message(message)
            user_query = parsed["query"]
            out_mode   = parsed["output"]
            conv_id    = parsed["conversation_id"] or (message.conversation_id or "default")

            cfg = {"configurable": {"thread_id": conv_id}}

            # invocar agente (igual que tu main, pero aquí devolvemos el texto)
            result = await self._agent.ainvoke(
                {"messages": [{"role": "user", "content": user_query}]},
                cfg
            )

            # tratar de recuperar el último contenido de asistente
            answer_text: Optional[str] = None

            # 1) de result (según versión)
            if isinstance(result, dict) and "messages" in result:
                msgs = result["messages"]
                if msgs and hasattr(msgs[-1], "content"):
                    answer_text = getattr(msgs[-1], "content", None)
                elif msgs and isinstance(msgs[-1], dict):
                    answer_text = msgs[-1].get("content")

            # 2) de memoria
            if not answer_text:
                last = self._memory.load(conv_id).get("messages", [])
                if last and last[-1][0] == "assistant":
                    answer_text = last[-1][1]

            # 3) fallback si nada
            if not answer_text or not str(answer_text).strip():
                answer_text = "No se pudo obtener una respuesta coherente en este momento."

            # salvaguarda: aplica el mismo criterio del finalize_or_fallback server-side
            answer_text = finalize_or_fallback.invoke({"answer": answer_text}) if hasattr(finalize_or_fallback, "invoke") else finalize_or_fallback(answer_text)  # type: ignore

            out_text = json.dumps({"answer": answer_text}, ensure_ascii=False) if out_mode == "json" else answer_text

            return Message(
                content=TextContent(text=out_text),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id
            )

        except Exception as e:
            tb = traceback.format_exc()
            log.error("Fallo en handle: %s\n%s", e, tb)
            err = {"error": str(e), "trace": tb}
            return Message(
                content=TextContent(text=json.dumps(err, ensure_ascii=False)),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id
            )

    # ---- handler síncrono requerido por algunas versiones de python-a2a ----
    def handle_message(self, message: Message) -> Message:
        return run_async(self._handle_async(message))

if __name__ == "__main__":
    # Requiere: GITLAB_PERSONAL_ACCESS_TOKEN y Docker si usas mcp/gitlab
    if "GITLAB_PERSONAL_ACCESS_TOKEN" not in os.environ:
        raise RuntimeError("Falta GITLAB_PERSONAL_ACCESS_TOKEN")
    host, port = "127.0.0.1", 8003
    print(f"🚀 A2A GitLab MCP escuchando en http://{host}:{port}")
    run_server(GitLabA2A(host=host, port=port), host=host, port=port)
