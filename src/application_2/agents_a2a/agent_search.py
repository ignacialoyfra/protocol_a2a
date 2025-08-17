from __future__ import annotations
import asyncio, json, traceback, os, logging, re
from datetime import datetime, timedelta
from typing import Optional

from python_a2a import (
    A2AServer, Message, TextContent, MessageRole,
    run_server, AgentCard, AgentSkill
)
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("AgentSearchReAct")


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




_sympy = None
def _get_sympy():
    global _sympy
    if _sympy is None:
        try:
            import sympy as sp
            _sympy = sp
        except Exception as e:
            _sympy = e  
    return _sympy

_ALLOWED_EXPR = re.compile(r"^[0-9\.\+\-\*\/\^\(\)\s xX=]*$")

@tool
def math_solve(expression: str) -> str:
    """
    Resuelve una expresión/ecuación simple en 'x'. Soporta +,-,*,/,^, paréntesis,
    '=' para ecuaciones y funciones básicas de sympy (si están presentes).
    Devuelve resultado exacto/aprox o 'error: ...' si no puede.
    """
    log.info(f"[TOOL] Invocada con math_solve: {expression}")
    expr = (expression or "").strip()
    if not expr:
        return "error: expresión vacía"

    if not _ALLOWED_EXPR.match(expr.replace("^","**")) and not any(k in expr for k in ("sin","cos","tan","pi","exp","log")):
        return "error: caracteres no permitidos"

    sp = _get_sympy()
    if isinstance(sp, Exception):
        return f"error: sympy no está disponible ({sp})"

    try:
        expr_norm = expr.replace("^", "**")
        x = sp.symbols('x')
        if "=" in expr_norm:
            lhs, rhs = expr_norm.split("=", 1)
            sol = sp.solve(sp.Eq(sp.sympify(lhs), sp.sympify(rhs)), x)
            return f"solución: {sol}"
        val = sp.sympify(expr_norm)
        exacto = sp.simplify(val)
        aprox = exacto.evalf()
        return f"resultado: {exacto} ; aproximado: {aprox}"
    except Exception as e:
        return f"error: no se pudo interpretar la expresión ({e})"

_PHILO = {
    "platón": "Platón (427–347 a. C.) defendió el mundo de las Formas: realidades inmutables que fundamentan lo sensible.",
    "aristóteles": "Aristóteles (384–322 a. C.) propuso una metafísica de sustancias, causa final y ética de la virtud.",
    "kant": "Immanuel Kant (1724–1804) distingue fenómeno y noúmeno, y fundamenta la moral en el imperativo categórico.",
    "nietzsche": "Friedrich Nietzsche (1844–1900) critica la moral tradicional y proclama la transvaloración de todos los valores."
}

@tool
def philosophy_snippet(topic: str) -> str:
    """
    Devuelve una explicación breve (2–4 líneas) sobre un filósofo/tema canónico.
    Si no hay entrada exacta, sugiere cómo precisar la consulta.
    """
    log.info(f"[TOOL] Invocada con philosophy_snippet: {topic}")
    key = (topic or "").strip().lower()
    for k, v in _PHILO.items():
        if k in key:
            return v
    return "No tengo un snippet curado para ese tema. Di el nombre del filósofo (p. ej., 'Kant') o el concepto central."


_FACTORS = {
    ("km","m"): 1000.0, ("m","km"): 1/1000.0,
    ("mi","km"): 1.60934, ("km","mi"): 1/1.60934,
    ("lb","kg"): 0.453592, ("kg","lb"): 1/0.453592,
}
def _celsius_to_f(v): return (v - 32) * 5/9
def _f_to_c(v): return v * 9/5 + 32

@tool
def unit_convert(value: float, from_unit: str, to_unit: str) -> str:
    """
    Convierte entre unidades comunes: km<->m, km<->mi, kg<->lb, °C<->°F.
    Ej: unit_convert(10, "km", "mi")
    """
    log.info(f"[TOOL] Invocada con unit_convert: {value}{from_unit}{to_unit}")
    fu, tu = (from_unit or "").strip().lower(), (to_unit or "").strip().lower()
    try:
        if (fu, tu) in _FACTORS:
            return f"{value * _FACTORS[(fu, tu)]:.6g} {tu}"
        if fu in ("c","°c","celsius") and tu in ("f","°f","fahrenheit"):
            return f"{_f_to_c(value):.6g} °F"
        if fu in ("f","°f","fahrenheit") and tu in ("c","°c","celsius"):
            return f"{_celsius_to_f(value):.6g} °C"
        return "error: conversión no soportada"
    except Exception as e:
        return f"error: {e}"


_DATE_RX = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*([+\-])\s*(\d+)\s*d(ías|ias)?\s*$", re.I)

@tool
def date_arith(expression: str) -> str:
    """
    Suma/resta días: 'YYYY-MM-DD + 10 d' o '2025-08-17 - 3 dias'.
    """
    log.info(f"[TOOL] Invocada con date_arith: {expression}")
    s = (expression or "").strip()
    m = _DATE_RX.match(s)
    if not m:
        return "error: formato esperado 'YYYY-MM-DD +/- N d'"
    ds, sign, n, _ = m.groups()
    try:
        base = datetime.strptime(ds, "%Y-%m-%d")
        delta = timedelta(days=int(n))
        res = base + (delta if sign == "+" else -delta)
        return f"{res.strftime('%Y-%m-%d')}"
    except Exception as e:
        return f"error: {e}"


@tool
def general_search_summary(query: str) -> str:
    """
    Genera un resumen breve (3–6 líneas) informativo sobre la consulta.
    Usa OpenAI internamente. Úsalo como fallback cuando no aplique otra tool.
    """
    log.info(f"[TOOL] Invocada con general_search_summary: {query}")
    model_id = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(model=model_id, temperature=0.1)
    system = ("Eres un asistente que redacta un resumen estilo 'resultado de búsqueda'. "
              "Sé conciso (3–6 líneas), neutral y útil. No inventes enlaces ni datos dudosos.")
    user = f"Tema/Pregunta:\n{query}\n\nEscribe un resumen breve y práctico (3–6 líneas)."
    try:
        resp = llm.invoke([{"role":"system","content":system},{"role":"user","content":user}])
        return (resp.content or "").strip() or "No se encontraron elementos claros para resumir."
    except Exception as e:
        return f"[search_error] fallo en OpenAI: {e}"


class SearchA2A(A2AServer):
    def __init__(self, host: str = "127.0.0.1", port: int = 8001):
        card = AgentCard(
            name="Agent Search (ReAct)",
            description=(
                "Agente de búsqueda/resumen con tools temáticas: matemática, filosofía, unidades, fechas; "
                "y fallback de resumen general con OpenAI. Devuelve internet_text."
            ),
            url=f"http://{host}:{port}",
            version="2.0.0",
            skills=[
                AgentSkill(id="general_search_summary", name="general_search_summary",
                           description="Genera un 'internet_text' breve y útil (3–6 líneas)"),
                AgentSkill(id="math_solve", name="math_solve",
                           description="Resolver expresiones/ecuaciones simples"),
                AgentSkill(id="philosophy_snippet", name="philosophy_snippet",
                           description="Snippet filosófico curado (2–4 líneas)"),
                AgentSkill(id="unit_convert", name="unit_convert",
                           description="Conversión básica de unidades"),
                AgentSkill(id="date_arith", name="date_arith",
                           description="Suma/resta de días en fechas"),
            ],
            authentication=None
        )
        super().__init__(agent_card=card)

        model_id = "gpt-4o-mini"
        if not os.getenv("OPENAI_API_KEY"):
            log.warning("OPENAI_API_KEY no está definida; el agente podría fallar.")
        self._llm = ChatOpenAI(model=model_id, temperature=0)


        self._memory = InMemorySaver()

        self._agent = create_react_agent(
            self._llm,
            tools=[math_solve, philosophy_snippet, unit_convert, date_arith, general_search_summary],
            name="AgentSearchReAct",
            checkpointer=self._memory
        )

        self._system = (
            "Eres un buscador inteligente. Debes producir un único 'internet_text' breve (3–6 líneas), en español, "
            "con la mejor información práctica. Decide si usar una herramienta temática:\n"
            "- Matemática: usa `math_solve(expression)` cuando la consulta sea un cálculo/ecuación.\n"
            "- Filosofía: usa `philosophy_snippet(topic)` para filósofos/ideas canónicas.\n"
            "- Unidades: usa `unit_convert(value, from_unit, to_unit)` si piden convertir.\n"
            "- Fechas: usa `date_arith('YYYY-MM-DD +/- N d')` para sumar/restar días.\n"
            "Si ninguna aplica, usa `general_search_summary(query)` como fallback.\n"
            "Tu ÚLTIMO mensaje debe ser SOLO el texto final del 'internet_text' (sin prefijos ni JSON)."
        )

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
            if not query:
                out = {"internet_text": "[search_error] la consulta llegó vacía al agente search."}
                return Message(
                    content=TextContent(text=json.dumps(out, ensure_ascii=False)),
                    role=MessageRole.AGENT,
                    parent_message_id=message.message_id,
                    conversation_id=message.conversation_id
                )

            user_msg = (
                "Genera un 'internet_text' breve (3–6 líneas) que responda o resuma con utilidad:\n"
                f"{query}\n\n"
                "Elige herramienta temática si corresponde; si no, usa el fallback de resumen general."
            )

            
            conv_id = message.conversation_id or "search-default"
            cfg = {"configurable": {"thread_id": conv_id}}

            result = await asyncio.wait_for(
                self._agent.ainvoke(
                    {"messages": [
                        {"role": "system", "content": self._system},
                        {"role": "user", "content": user_msg},
                    ]},
                    cfg
                ),
                timeout=120
            )

            final_text: Optional[str] = None
            if isinstance(result, dict) and "messages" in result and result["messages"]:
                last = result["messages"][-1]
                final_text = getattr(last, "content", None) if hasattr(last, "content") else last.get("content")
            if not final_text:
                final_text = "No se encontraron resultados útiles."

            payload = json.dumps({"internet_text": final_text.strip()}, ensure_ascii=False)
            print(f"############## payload ##############\n{payload}")
            return Message(
                content=TextContent(text=payload),
                role=MessageRole.AGENT,
                parent_message_id=message.message_id,
                conversation_id=message.conversation_id
            )

        except asyncio.TimeoutError:
            out = {"internet_text": "[search_error] timeout consultando al modelo OpenAI/ReAct."}
            return Message(content=TextContent(text=json.dumps(out, ensure_ascii=False)), role=MessageRole.AGENT,
                           parent_message_id=message.message_id, conversation_id=message.conversation_id)
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
    print(f"🚀 Agent A2A Search (ReAct, multi-tools) escuchando en http://{host}:{port}")
    run_server(SearchA2A(host=host, port=port), host=host, port=port)
