# Arquitectura

## Flujo de una consulta

1. El trabajador inicia sesión (en la demo, se elige en la barra lateral). La sesión fija su `worker_id`.
2. Streamlit llama a `harness.runtime.ejecutar(worker_id, pregunta)`.
3. El harness construye el agente con `create_agent(model, tools, system_prompt)`. Las tools se crean **para esa sesión** (`crear_herramientas(worker_id, ...)`): el id queda en una closure.
4. El agente decide qué tools llamar. Un caso típico ("explícame mi liquidación"):
   1. `obtener_liquidacion` → datos de la liquidación y perfil del contrato.
   2. `calcular_descuentos_esperados` → recalcula AFP, salud, seguro de cesantía, impuesto y gratificación, y los compara con lo pagado.
   3. `buscar_en_documentos` → recupera de Chroma las cláusulas y políticas relevantes (con filtro por trabajador).
5. El agente responde con un JSON. El harness lo valida contra `agent/output.schema.json`; si falla, intenta repararlo una vez.
6. El harness hace el *grounding check*: las fuentes citadas deben haber sido recuperadas en esta ejecución.
7. Streamlit muestra la respuesta, los hallazgos, las fuentes y la traza.

## Componentes

| Módulo | Responsabilidad |
|---|---|
| `harness/calculos.py` | Aritmética de remuneraciones (Decimal, redondeo a peso). Compara esperado vs pagado y clasifica cada línea: `ok`, `diferencia` o `derivada`. |
| `harness/ingest.py` | Carga Markdown → trocea por cláusula → metadata → Chroma persistente con huella de reindexado. |
| `harness/retriever.py` | `buscar()` con filtro `worker_id ∈ {sesión, ALL}`. |
| `harness/tools.py` | Cuatro tools por sesión. |
| `harness/schemas.py` | Contrato de salida (Pydantic) y extracción tolerante de JSON. |
| `harness/runtime.py` | Construcción del agente, ejecución, traza, validación, reparación, grounding. |
| `harness/llm_factory.py` | `ollama` / `unab` / `mock` para LLM; `ollama` / `mock` para embeddings. |
| `harness/fakes.py` | Embeddings por hashing y un agente guionado para trabajar sin red. |

## Qué decide cada pieza

| Pregunta del trabajador | Quién la resuelve |
|---|---|
| ¿Cuánto me descontaron de AFP y por qué ese monto? | Tool `calcular_descuentos_esperados` (cálculo) + `obtener_liquidacion` (datos) |
| ¿Por qué mi bono es cero? | **RAG**: anexo del contrato + política de bonos; el dato de atenciones viene de la liquidación |
| ¿Por qué no me descuentan seguro de cesantía? | **RAG**: cláusula de plazo fijo + guía de remuneraciones |
| ¿Cuánto vale el tope imponible? | Tool `consultar_parametros` (valor vigente) + RAG (qué es) |
| ¿Cuánto gana mi colega? | Nadie: guardrail (`fuera_de_alcance`) |

## Registro de decisiones

| Decisión | Motivo | Alternativa descartada |
|---|---|---|
| Tools por sesión con `worker_id` en closure | El LLM no puede cruzar datos entre personas | `worker_id` como argumento + validación en el prompt |
| Filtro de metadata en Chroma | El control de acceso no depende de la obediencia del modelo | Confiar en el prompt |
| Parámetros legales en JSON versionado con fuente | Cambian cada mes/año; el vector store envejece | Indexarlos como documento |
| `create_agent` (LangChain 1.x) | Es el patrón vigente en la documentación | `AgentExecutor` / `RetrievalQA` (legado) |
| Salida JSON validada + reintento | Contrato verificable por la UI y por los tests | Texto libre |
| Grounding check | Detecta citas inventadas | Confiar en las citas |
| Un chunk por cláusula | La estructura legal ya es la unidad semántica | Ventana fija de N caracteres |
| Mock determinista | Clase y tests sin depender de red ni de Ollama | Solo modelos reales |
| Chroma embebido (`PersistentClient`) | Un contenedor menos | Chroma cliente-servidor |

## Lecciones heredadas de las semanas 8 y 9

El modelo `mock` decide el siguiente paso mirando **solo los mensajes del turno actual** (los posteriores al último `HumanMessage`), nunca todo el historial. Y la traza que se muestra solo recorre el turno actual.
