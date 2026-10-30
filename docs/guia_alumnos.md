# De Alicia a un agente: RAG con Chroma y LangChain para revisar liquidaciones de sueldo

*Guía paso a paso · CINF110 Agentes de IA · tiempo estimado: 2 horas*

Camila es kinesióloga en la Clínica Traumatología Cóndor (ficticia). Es lunes, abre el PDF de su liquidación de septiembre y tiene tres dudas: por qué su bono de productividad aparece en cero, por qué su descuento de AFP le parece distinto al del mes pasado y cuánto gana su colega Tomás. No quiere esperar hasta el jueves para que Recursos Humanos le responda.

En esta guía construyes el asistente que le responde. Parte de lo que ya sabes (cargar texto, trocearlo, guardarlo en Chroma, preguntarle a un LLM con contexto, como hicimos con *Alicia en el país de las maravillas*) y lo lleva un paso más allá: **de una cadena de RAG a un agente que decide qué consultar**.

> **Datos 100% sintéticos.** Las remuneraciones son información sensible: en clase solo usamos personas y contratos inventados. El agente *explica y marca diferencias*; no certifica que una liquidación cumpla la ley.

## Qué vas a construir

```
Trabajador ──► Streamlit ──► Harness ──► Agente (LLM con tools)
 (sesión)                    valida JSON     ├─ obtener_liquidacion ────────► datos de la liquidación
                             + grounding     ├─ calcular_descuentos_esperados ► reglas de cálculo
                                             ├─ consultar_parametros ────────► UF, topes, comisiones
                                             └─ buscar_en_documentos ────────► Chroma (RAG)
```

Al terminar tendrás: un índice de Chroma con filtro por trabajador, una tool de RAG, un agente con cuatro tools, una salida validada contra un contrato, un chequeo de que no se inventan fuentes y una interfaz web.

## RAG en un minuto (y por qué un agente)

RAG tiene dos fases, igual que en el artículo de referencia:

1. **Preparación de datos:** reunir documentos → extraer texto → trocear (*chunking*) → calcular embeddings → guardar en la base vectorial.
2. **Consulta:** embeber la pregunta → buscar trozos parecidos → dárselos al LLM como contexto → respuesta.

Eso es lo que hiciste con Alicia. Pero una cadena siempre hace lo mismo: recupera, pega el contexto y responde. Un **agente** decide: ¿necesito los datos de la liquidación? ¿necesito calcular? ¿necesito buscar en el contrato? ¿o esta pregunta no me corresponde? Por eso la recuperación pasa a ser **una tool más**.

## Paso 0 · Entorno

Necesitas Python 3.12 o superior, y Ollama con dos modelos: uno de chat que soporte *tool calling* y uno de embeddings.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
ollama pull llama3.1:8b
ollama pull nomic-embed-text-v2-moe
pytest tests/test_paso_00_arranque.py                  # debe quedar en verde
```

> **Sin Ollama o sin internet:** en `.env` pon `LLM_PROVIDER=mock` y `EMBEDDINGS_PROVIDER=mock`. El modo `mock` es un agente simulado: sirve de red de seguridad y es lo que usan los tests.

El archivo `harness/config.py` lee las variables de entorno. Las dos que más vas a tocar son `LLM_PROVIDER` (`ollama`, `unab` o `mock`) y `LLM_MODEL`.

## Paso 1 · Alicia, y dónde falla

Así quedó nuestra cadena en la clase pasada, simplificada:

```python
qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=retriever)
qa.invoke({"query": "¿Por qué me descontaron tanto de AFP?"})
```

Haz la prueba con tu propio `RAG-DEMO` cargando los documentos de este caso. Vas a ver cuatro límites:

| Límite | Qué pasa |
|---|---|
| No sabe **quién** pregunta | Responde con un texto genérico sobre AFP, sin la liquidación de Camila |
| No puede **calcular** | Si inventa un monto, nadie lo detecta |
| **Siempre** recupera | Aunque la pregunta no necesite documentos, o no corresponda responderla |
| No distingue **de quién** es cada documento | Podría traer el contrato de otra persona |

Los cuatro límites tienen solución en esta guía: tools para saber y calcular, un agente que decide, y filtros de metadata.

> 💡 La documentación oficial de LangChain trata `RetrievalQA` como legado. El patrón vigente es un agente (`create_agent`) con el retriever como tool.

## Paso 2 · Los datos del caso

Explora la carpeta `data/`:

```
data/
  parametros_2026.json        UF, UTM, topes, comisiones de AFP, tabla de impuesto (con fuente y fecha)
  trabajadores.json           4 trabajadores: cargo, tipo de contrato, AFP...
  liquidaciones.json          liquidaciones de agosto y septiembre de cada uno
  documentos/                 el corpus para RAG
    contratos/contrato_W001.md ... contrato_W004.md
    reglamento_interno.md
    politica_bonos.md
    normativa_remuneraciones.md
```

Una liquidación tiene esta forma (resumida):

```json
{
  "worker_id": "W001", "periodo": "2026-09",
  "haberes_imponibles": [{"concepto": "Sueldo base", "monto": 1000000}, "..."],
  "descuentos_legales": [
    {"codigo": "afp", "concepto": "AFP ...", "base": 1219115, "tasa": 0.1145, "monto": 139589}, "..."
  ],
  "datos_variables": {"atenciones_mes": 112}
}
```

Los **documentos** son texto largo y distinto para cada persona: eso es lo que recuperaremos con RAG. Los **números** (parámetros y cálculos) no se recuperan: se calculan.

> ⚠️ Mira `parametros_2026.json`: cada valor trae su `fuente` y la fecha de verificación. **UF, topes y comisiones cambian**; si los metieras en un documento indexado, quedarían viejos sin que nadie lo note. Por eso viven en una tool.

## Paso 3 · Las reglas de cálculo (ya están hechas)

El LLM **no hace aritmética**. `harness/calculos.py` calcula con `Decimal` y redondea a peso, igual que una liquidación:

```python
# harness/calculos.py
def impuesto_unico(params: dict, base_tributable: int | Decimal) -> int:
    """Impuesto unico de segunda categoria: base x factor - rebaja (tabla SII)."""
    base = _d(base_tributable)
    if base <= 0:
        return 0
    for tramo in params["impuesto_unico"]["tramos"]:
        if tramo["hasta"] is None or base <= _d(tramo["hasta"]):
            monto = base * _d(tramo["factor"]) - _d(tramo["rebaja"])
            return max(redondear(monto), 0)
    return 0
```

La función clave es `comparar_con_liquidacion`: recalcula lo que *debería* haberse descontado y lo compara con lo pagado. Clasifica cada línea como `ok`, `diferencia` o `derivada` (cuando un descuento está bien calculado pero sobre una base distinta porque otro estaba mal). No necesitas modificarla; sí necesitas entender qué devuelve:

```python
# resultado de calcular_descuentos_esperados (una línea)
{"codigo": "afp", "esperado": 137394, "pagado": 139589, "diferencia": 2195,
 "estado": "diferencia", "causa_probable": "..."}
```

## Paso 4 · El contrato de salida

Un agente que responde texto libre no se puede integrar en una aplicación. Definimos qué debe devolver con un modelo de Pydantic (`harness/schemas.py`):

```python
# harness/schemas.py
class Hallazgo(BaseModel):
    severidad: Literal["info", "revisar", "critico"]
    descripcion: str
    monto_diferencia: int | None = Field(
        default=None, description="Pagado menos esperado, en pesos (positivo = se descuento de mas).")
    recomendacion: str = ""
```

El informe completo (`InformeLiquidacion`) tiene `respuesta`, `descuentos`, `hallazgos`, `fuentes`, `requiere_revision_rrhh` y `fuera_de_alcance`. De ese modelo sale `agent/output.schema.json`, el contrato que el harness valida.

## Paso 5 · Cargar los documentos

**Tu primera tarea.** Abre `harness/ingest.py` y completa `cargar_documentos`: lee todos los `.md` (incluida la subcarpeta `contratos/`) y crea un `Document` por archivo con su metadata. La metadata es lo importante: dice *de dónde* viene el texto y *a quién* pertenece.

```python
# harness/ingest.py
def cargar_documentos(docs_dir: Path | None = None) -> list[Document]:
    docs_dir = docs_dir or DOCS_DIR
    documentos = []
    for ruta in sorted(docs_dir.rglob("*.md")):
        documentos.append(Document(page_content=ruta.read_text(encoding="utf-8"),
                                   metadata=_metadata_de_archivo(ruta)))
    return documentos
```

`_metadata_de_archivo` ya está hecha: asigna `source`, `doc_type` y `worker_id`. Los contratos pertenecen a una persona (`W001`...); el reglamento, la política y la normativa son de todos (`ALL`).

```bash
pytest tests/test_paso_05_cargar.py
```

## Paso 6 · Chunking por cláusula

El artículo de referencia dice algo clave: *la calidad de los chunks es esencial, y lo primero que hay que mirar es la estructura de tus documentos*. Un contrato ya viene dividido en cláusulas, y cada cláusula es una unidad de sentido. Cortar cada 300 caracteres partiría frases a la mitad; cortar por cláusula respeta el significado.

Hay un segundo problema: una cláusula suelta ("el trabajador recibirá una asignación de colación...") **no dice de qué contrato es**. Si la buscamos sola, no sabremos a quién pertenece. La solución es anteponer a cada chunk su título y su sección.

Completa `trocear`:

```python
# harness/ingest.py
def trocear(documentos: list[Document], chunk_size: int = 700, chunk_overlap: int = 100) -> list[Document]:
    por_encabezado = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "titulo"), ("##", "seccion")], strip_headers=True)
    partidor = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chunks: list[Document] = []
    for doc in documentos:
        n = 0
        for parte in por_encabezado.split_text(doc.page_content):
            if "seccion" not in parte.metadata:  # introduccion/aviso sin seccion: se descarta
                continue
            for texto in partidor.split_text(parte.page_content):
                n += 1
                meta = {**doc.metadata, "titulo": parte.metadata.get("titulo", ""),
                        "seccion": parte.metadata["seccion"], "chunk_id": f"{doc.metadata['source']}#{n:02d}"}
                contexto = f"{meta['titulo']} · {meta['seccion']}"
                chunks.append(Document(page_content=f"{contexto}\n{texto}", metadata=meta))
    return chunks
```

Dos pasos de partición: primero por encabezados (una cláusula = un chunk) y solo si una sección es muy larga, el `RecursiveCharacterTextSplitter` la parte con solape. Cada chunk recibe un `chunk_id` único (`contrato_W001.md#06`): lo usaremos para **citar fuentes**.

```bash
pytest tests/test_paso_06_chunking.py
```

> 💡 Prueba esto: imprime `trocear(cargar_documentos())[5]`. ¿Qué metadata tiene? ¿Qué pasaría si no antepusiéramos el título al texto?

## Paso 7 · El índice en Chroma

Ahora convertimos los chunks en vectores y los guardamos. Como en Alicia, usamos un modelo de embeddings de Ollama, pero con tres mejoras:

- **Persistente:** el índice se guarda en disco (`PersistentClient`) y se reutiliza.
- **Con huella (`firma`):** si cambian los documentos o el modelo de embeddings, el índice viejo deja de servir y se reconstruye solo. Mezclar vectores de dos modelos distintos es un error silencioso.
- **Distancia coseno**, para que la relevancia sea `1 - distancia`.

```python
# harness/ingest.py
def construir_indice(embeddings: Embeddings, settings: Settings, docs_dir: Path | None = None) -> Chroma:
    docs_dir = docs_dir or DOCS_DIR
    chunks = trocear(cargar_documentos(docs_dir))
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    try:
        client.delete_collection(settings.collection)
    except Exception:  # la coleccion no existia
        pass
    return Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        ids=[c.metadata["chunk_id"] for c in chunks],
        client=client,
        collection_name=settings.collection,
        collection_metadata={"hnsw:space": "cosine", "firma": _firma(settings, docs_dir)},
    )
```

> ⚠️ **Dos detalles de los modelos `nomic`.** Funcionan mejor si antepones `search_document: ` a los textos que indexas y `search_query: ` a las preguntas. LangChain no lo hace solo; `harness/llm_factory.py` lo resuelve con un envoltorio (`PrefixedEmbeddings`). Y recuerda: **el modelo que usas para consultar debe ser el mismo con que indexaste.**

```bash
pytest tests/test_paso_07_chroma.py
python -m harness.ingest        # construye el índice real con tus embeddings
```

## Paso 8 · Recuperar solo lo que el trabajador puede ver

Este es el paso más importante del caso. Si Tomás pregunta "bono de productividad", el buscador podría traer el anexo de Camila, porque es el texto más parecido. **Un prompt que diga "no muestres datos de otros" no es control de acceso.** El control de acceso tiene que estar en el código.

Chroma permite filtrar por metadata. Un trabajador ve *sus* documentos **o** los compartidos:

```python
# harness/retriever.py
def filtro_para(worker_id: str) -> dict:
    """Un trabajador ve SUS documentos y los compartidos (reglamento, politicas, normativa)."""
    return {"$or": [{"worker_id": worker_id}, {"worker_id": TODOS_LOS_TRABAJADORES}]}


def buscar(indice: Chroma, consulta: str, worker_id: str, k: int = 4) -> list[tuple[Document, float]]:
    """Devuelve (documento, relevancia) ordenados; relevancia = 1 - distancia coseno."""
    return indice.similarity_search_with_relevance_scores(
        consulta, k=k, filter=filtro_para(worker_id))
```

```bash
pytest tests/test_paso_08_retriever.py
```

**Comprueba que el filtro hace falta.** Haz esta prueba en una consola y compara:

```python
q = "bono de productividad meta de atenciones"
indice.similarity_search_with_relevance_scores(q, k=6)              # sin filtro
buscar(indice, q, "W002", k=6)                                       # con filtro, como Tomás
```

Sin filtro suele aparecer el anexo de Camila (`contrato_W001.md#11`). Con el filtro de Tomás, desaparece.

> 💡 El score de relevancia depende del modelo de embeddings. El artículo de referencia usa un umbral de 0,7 "arbitrario". Con tu modelo, ¿qué score tienen los resultados buenos y los malos? Imprímelos antes de fijar un umbral.

## Paso 9 · Las tools del agente

Un agente usa herramientas. Aquí van cuatro:

| Tool | Para qué |
|---|---|
| `obtener_liquidacion` | Datos de la liquidación y perfil del contrato *(dada)* |
| `calcular_descuentos_esperados` | Recalcula y compara con lo pagado *(dada)* |
| `consultar_parametros` | UF, topes, comisiones con su fuente *(dada)* |
| `buscar_en_documentos` | **RAG: tu tool** |

Fíjate en cómo se crean (`harness/tools.py`): **dentro de una función que recibe el `worker_id`**.

```python
# harness/tools.py
def crear_herramientas(worker_id: str, indice: Chroma, settings: Settings,
                       params: dict | None = None) -> list[BaseTool]:
    params = params or cargar_parametros()
    trabajador = datos.obtener_trabajador(worker_id)
    ...
```

Ninguna tool recibe el id como parámetro. Si lo recibieran, un prompt como "consulta al trabajador W002" podría cruzar datos. Aquí el id viene de la sesión y el modelo no puede cambiarlo. Hay un test que lo verifica.

Ahora tu tool de RAG:

```python
# harness/tools.py
    @tool(response_format="content_and_artifact")
    def buscar_en_documentos(consulta: str) -> tuple[str, list[str]]:
        """Busca en los documentos del trabajador autenticado (su contrato y anexos) y en los
        documentos compartidos (reglamento interno, política de bonos, guía de remuneraciones).
        Úsala para saber qué dice el contrato, cómo se miden los bonos, qué reglas aplican o qué
        procedimiento seguir. Devuelve trozos con su id de fuente [fuente: ...]; cita siempre ese id."""
        resultados = buscar(indice, consulta, worker_id, k=settings.k)
        if not resultados:
            return "No se encontraron documentos relevantes.", []
        bloques, ids = [], []
        for doc, score in resultados:
            cid = doc.metadata["chunk_id"]
            ids.append(cid)
            bloques.append(f"[fuente: {cid}]\n{doc.page_content}\n(relevancia {score:.2f})")
        return "\n---\n".join(bloques), ids
```

Tres cosas para notar:

1. **El docstring es el prompt de la tool.** El LLM lo lee para decidir *cuándo* usarla. Si lo escribes mal, el agente no la usará, o la usará para todo.
2. **`content_and_artifact`:** la tool devuelve dos cosas: el texto que ve el LLM y una lista de `chunk_id` que **no** ve el LLM pero sí el harness. Con eso, más adelante, comprobamos que las citas no sean inventadas.
3. **Formato `[fuente: id]`:** le damos al modelo el id para que pueda citarlo.

```bash
pytest tests/test_paso_09_tools.py
```

## Paso 10 · El agente

Todo está listo para armarlo. Las instrucciones del agente viven en `agent/agent.md`, un archivo declarativo, igual que en las semanas anteriores. Léelo: tiene siete reglas y el formato de salida. Algunas claves:

- *"Nunca calcules montos tú mismo."* → usa `calcular_descuentos_esperados`.
- *"Si te preguntan por otra persona, no llames a ninguna herramienta."* → guardrail.
- *"No afirmes nada del contrato que no hayas recuperado."* → grounding.

Completa `construir_agente` en `harness/runtime.py`:

```python
# harness/runtime.py
def construir_agente(worker_id: str, settings: Settings, *, llm: BaseChatModel | None = None,
                     indice: Chroma | None = None, embeddings: Embeddings | None = None):
    llm = llm or crear_llm(settings)
    if indice is None:
        indice = asegurar_indice(embeddings or crear_embeddings(settings), settings)
    herramientas = crear_herramientas(worker_id, indice, settings)
    return create_agent(model=llm, tools=herramientas, system_prompt=prompt_de_sistema(worker_id))
```

`prompt_de_sistema` agrega al final de `agent.md` quién es el trabajador autenticado. Eso es todo el agente: un LLM, cuatro tools y un prompt.

```bash
pytest tests/test_paso_10_agente.py
python scripts/demo_cli.py --mock --worker W001 "Explícame mi liquidación"
python scripts/demo_cli.py --worker W001 "Explícame mi liquidación"      # con tu modelo real
```

Mira la **traza**: ¿en qué orden llamó las tools? ¿Recuperó el anexo del bono cuando preguntaste por el bono?

## Paso 11 · Validar, reparar y verificar las fuentes

Un LLM puede devolver JSON roto, o citar un documento que nunca recuperó. El harness (`ejecutar`) hace tres cosas después de que el agente responde:

1. **Valida** la salida contra el contrato (`parsear_informe`).
2. Si falla, **repara una vez**: le devuelve al modelo su propio texto y el error.
3. **Grounding check:** toda fuente citada tiene que haberse recuperado en *esta* ejecución. Esta es tu segunda tarea:

```python
# harness/runtime.py
def _revisar_fuentes(informe: InformeLiquidacion, ids: set[str], tools: set[str]) -> list[str]:
    """Grounding: toda fuente citada debe haber sido recuperada/usada en ESTA ejecucion."""
    avisos = []
    for f in informe.fuentes:
        if f.tipo == "documento" and f.referencia not in ids:
            avisos.append(f"Fuente documental no recuperada en esta consulta: {f.referencia}")
        if f.tipo == "herramienta" and f.referencia not in tools:
            avisos.append(f"Herramienta citada pero no usada: {f.referencia}")
    return avisos
```

`ids` son los `chunk_id` que salieron del *artefacto* de tu tool (paso 9); `tools` son las tools realmente llamadas. Si el modelo cita `contrato_W001.md#99` y ese chunk no se recuperó, hay una advertencia.

```bash
pytest tests/test_paso_11_grounding.py
```

## Paso 12 · Evaluación: ¿cómo sabes que funciona?

El artículo de referencia termina con una pregunta incómoda: *"¿cómo se cuantifica qué tan bien funciona el sistema?"* Una respuesta que se ve bien no es evidencia. Hay que probar contra casos con respuesta conocida, **positivos y negativos**:

- **Positivo:** Diego tiene contrato a plazo fijo y le descontaron seguro de cesantía. ¿El agente lo detecta?
- **Negativo:** Tomás tiene la liquidación correcta. ¿El agente evita inventar problemas? Cuidado: un agente que siempre responde "todo bien" pasaría esta prueba. ¿Qué más deberías exigir?

Abre `tests/test_paso_12_mi_evaluacion.py` y completa las aserciones. Propiedades objetivas que puedes revisar: qué tools llamó, qué dice el informe, qué fuentes citó, qué **no** dice.

```python
r = correr("W004", "¿Por qué me descuentan seguro de cesantía?")
assert "buscar_en_documentos" in {t["herramienta"] for t in r.traza}
```

Después, cambia `LLM_MODEL` en `.env` y repite. Los modelos no son deterministas: corre cada caso varias veces antes de concluir algo.

## Paso 13 · La interfaz y Docker

La app (`app/streamlit_app.py`) ya está lista y **no contiene lógica del agente**: solo llama a `ejecutar()`.

```bash
streamlit run app/streamlit_app.py
```

En la barra lateral eliges quién inicia sesión; el agente solo ve su información. Prueba:

1. Camila → *Explícame mi liquidación* → mira la traza y los hallazgos.
2. Camila → *Mi bono de productividad* → ¿qué fuentes cita?
3. Camila → *Probar guardrail* → ¿llamó alguna tool?
4. Cambia a Tomás y repite la primera pregunta.
5. Abre **Configuración** y cambia el LLM a `mock`. Repite la primera pregunta.

Y para correrlo en un contenedor:

```bash
docker compose up --build        # http://localhost:8501
```

## Qué aprendiste

| Idea | Dónde la viste |
|---|---|
| RAG sirve para lo que se **lee**; las tools, para lo que se **calcula** | Pasos 3, 7 y 9 |
| El chunking debe respetar la estructura del documento | Paso 6 |
| El control de acceso va en el código, no en el prompt | Pasos 8 y 9 |
| Los números volátiles viven en una tool con fuente y fecha | Pasos 2 y 3 |
| Un agente decide; una cadena no | Pasos 1 y 10 |
| La salida de un LLM se valida, se repara y se verifica | Paso 11 |
| "Se ve bien" no es evidencia: se evalúa con casos conocidos | Paso 12 |

## Errores comunes

| Síntoma | Causa probable |
|---|---|
| `NotImplementedError` | Falta completar el paso que indica el mensaje |
| El agente no usa la tool de RAG | Revisa su docstring: ¿dice cuándo usarla? |
| Chroma devuelve resultados raros tras cambiar de modelo | Mezclaste vectores de dos modelos: reconstruye el índice (botón en la app) |
| `Connection refused` a Ollama | Ollama no está corriendo, o en Docker falta `host.docker.internal` |
| El agente responde sin llamar tools | El modelo no soporta *tool calling*: cambia a uno que sí |
| La salida no cumple el contrato | Normal en modelos pequeños: ¿qué hace el harness? ¿Se puede mejorar el prompt? |

## Desafíos extra

1. **Búsqueda híbrida:** combina la búsqueda vectorial con una por palabras clave (BM25) y compara resultados.
2. **Umbral de relevancia:** descarta resultados bajo cierto score. ¿Cuál? Hazlo con evidencia, no al azar.
3. **Memoria:** agrega un *checkpointer* para que el agente recuerde la conversación.
4. **Comparar modelos:** corre tus casos con 2 o 3 modelos y compara tasas de acierto y tiempos.
5. **Un hallazgo nuevo:** agrega al corpus una cláusula de horas extra y haz que el agente la use.
6. **Romper el sistema:** intenta que el agente entregue datos de otro trabajador. ¿Qué defensa lo detuvo?

## Referencias

- Callum Macpherson, [*Implementing RAG in LangChain with Chroma: A Step-by-Step Guide*](https://medium.com/@callumjmac/implementing-rag-in-langchain-with-chroma-a-step-by-step-guide-16fc21815339), Medium, abril de 2024 (estructura de esta guía).
- Documentación de LangChain: [Agentes](https://docs.langchain.com/oss/python/langchain/agents) y [Retrieval](https://docs.langchain.com/oss/python/langchain/retrieval).
- Documentación de [Chroma](https://docs.trychroma.com/).
- SII, [Circular N° 37 de 2026](https://www.sii.cl/normativa_legislacion/circulares/2026/circu37.pdf): tabla del impuesto único.
- Código del Trabajo (art. 42 y 50), DL 3.500 y Ley 19.728.

*Los parámetros legales del ejercicio fueron verificados el 2026-10-07 y están citados en `data/parametros_2026.json`. Vuelve a verificarlos antes de cualquier uso real.*
