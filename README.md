# 🧩 A2A + LangGraph: Laboratorio Multiagente Escalable

Este proyecto es un **laboratorio experimental** donde se implementa un orquestador multiagente usando **LangGraph** y el **protocolo A2A**, con el objetivo de demostrar cómo distintos agentes especializados pueden coordinarse de forma escalable.

## 🚀 Descripción

El sistema está compuesto por tres agentes principales:

1. **Agente Search (ReAct)**  
   - Encargado de resolver la consulta inicial del usuario.  
   - Contiene **cinco herramientas internas (tools)** que se invocan según el contexto de la consulta:  
     - `math_solve`: operaciones matemáticas.  
     - `philosophy_snippet`: consultas relacionadas con filosofía.  
     - `unit_convert`: conversiones de unidades (ej. metros ↔ kilómetros).  
     - `date_arith`: operaciones con fechas.  
     - `general_search_summary`: búsqueda/resumen general cuando ninguna de las anteriores aplica.  

2. **Agente Analysis**  
   - Evalúa si la información obtenida por el agente buscador es **suficiente**.  
   - Responde únicamente **sí** o **no**.  
   - Si no es suficiente, se repite el ciclo de búsqueda.  

3. **Agente Response**  
   - Formula la **respuesta final** que recibe el usuario.  
   - No utiliza tools, sino que invoca directamente un modelo de OpenAI (simplificación para laboratorio).  

Toda la coordinación está definida en un **grafo de LangGraph**, el cual marca el flujo entre agentes y asegura la lógica de iteraciones.

---

## 📊 Diagramas

### 🔹 Interacción entre Tools
![Interacción entre Tools](/images/interaccion%20entre%20tools.png)

### 🔹 Interacción entre Agentes
![Interacción entre Agentes](/images/interaccion%20entre%20agentes.png)

### 🔹 Diagrama del Protocolo A2A
![Diagrama A2A](/images/diagrama%20protocolo%20a2a.png)

---

## ⚙️ Flujo de trabajo

1. El **usuario** realiza una consulta.  
2. El **Agente Search** procesa la consulta y selecciona la tool adecuada.  
3. Los resultados se envían al **Agente Analysis**, que decide si son suficientes.  
   - Si **no** lo son, el flujo vuelve al Agente Search (otra iteración).  
   - Si **sí** lo son, el flujo avanza al Agente Response.  
4. El **Agente Response** entrega la respuesta final al usuario.  

---

## 🔧 Mejoras Futuras

- Hacer el flujo **completamente asíncrono** para soportar ejecución paralela de agentes.  
- Permitir que los agentes A2A puedan acceder a herramientas expuestas por un **MCP específico**.  
- Reemplazar el orquestador por un modelo de enjambre (**Swarm**) para mayor escalabilidad.  

---

## 📂 Código fuente

Puedes acceder al repositorio completo aquí:  
👉 [protocol_a2a](https://github.com/ignacialoyfra/protocol_a2a)

---

✍️ **Autor:** María Ignacia Loyola Fraile  
