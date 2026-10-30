"""Runtime del agente: arma el agente, lo ejecuta, valida la salida y revisa el grounding."""
from __future__ import annotations

from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from . import datos
from .config import AGENT_DIR, Settings
from .ingest import asegurar_indice
from .llm_factory import crear_embeddings, crear_llm
from .schemas import InformeLiquidacion, parsear_informe
from .tools import crear_herramientas


@dataclass
class ResultadoEjecucion:
    informe: InformeLiquidacion | None
    crudo: str
    traza: list[dict] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    reparado: bool = False

    @property
    def ok(self) -> bool:
        return self.informe is not None


def cargar_instrucciones() -> str:
    return (AGENT_DIR / "agent.md").read_text(encoding="utf-8")


def prompt_de_sistema(worker_id: str) -> str:
    t = datos.obtener_trabajador(worker_id)
    periodos = datos.periodos_disponibles(worker_id)
    return (f"{cargar_instrucciones()}\n\n---\nTrabajador autenticado: {t['nombre']} ({worker_id}). "
            f"Periodo más reciente: {periodos[-1]}. Periodos disponibles: {', '.join(periodos)}.")


# ------------------------------------------------------------------ PASO 10: el agente
def construir_agente(worker_id: str, settings: Settings, *, llm: BaseChatModel | None = None,
                     indice: Chroma | None = None, embeddings: Embeddings | None = None):
    llm = llm or crear_llm(settings)
    if indice is None:
        indice = asegurar_indice(embeddings or crear_embeddings(settings), settings)
    herramientas = crear_herramientas(worker_id, indice, settings)
    return create_agent(model=llm, tools=herramientas, system_prompt=prompt_de_sistema(worker_id))


def _traza(mensajes: list) -> tuple[list[dict], set[str], set[str]]:
    """Extrae la traza de tools y lo que realmente se recupero (para el grounding check)."""
    resultados = {m.tool_call_id: m for m in mensajes if isinstance(m, ToolMessage)}
    traza, ids_recuperados, tools_usadas = [], set(), set()
    for m in mensajes:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                res = resultados.get(tc["id"])
                traza.append({"paso": len(traza) + 1, "herramienta": tc["name"], "args": tc["args"],
                              "resultado": str(res.content) if res is not None else ""})
                tools_usadas.add(tc["name"])
                if res is not None and res.artifact:
                    ids_recuperados.update(res.artifact)
    return traza, ids_recuperados, tools_usadas


def _revisar_fuentes(informe: InformeLiquidacion, ids: set[str], tools: set[str]) -> list[str]:
    """Grounding: toda fuente citada debe haber sido recuperada/usada en ESTA ejecucion."""
    avisos = []
    for f in informe.fuentes:
        if f.tipo == "documento" and f.referencia not in ids:
            avisos.append(f"Fuente documental no recuperada en esta consulta: {f.referencia}")
        if f.tipo == "herramienta" and f.referencia not in tools:
            avisos.append(f"Herramienta citada pero no usada: {f.referencia}")
    return avisos


def _reparar(llm: BaseChatModel, crudo: str, error: str) -> str:
    msgs = [SystemMessage(content="Corriges salidas JSON. Responde SOLO con el JSON corregido."),
            HumanMessage(content=("Este texto debía ser un objeto JSON con los campos: respuesta, descuentos, "
                                  "hallazgos, fuentes, requiere_revision_rrhh, fuera_de_alcance.\n"
                                  f"Error de validación: {error}\n\nTexto:\n{crudo}"))]
    return str(llm.invoke(msgs).content)


# ------------------------------------------------------------------ PASO 11: ejecutar y validar
def ejecutar(worker_id: str, pregunta: str, settings: Settings | None = None, *,
             llm: BaseChatModel | None = None, indice: Chroma | None = None,
             embeddings: Embeddings | None = None) -> ResultadoEjecucion:
    settings = settings or Settings()
    llm = llm or crear_llm(settings)
    agente = construir_agente(worker_id, settings, llm=llm, indice=indice, embeddings=embeddings)
    estado = agente.invoke({"messages": [HumanMessage(content=pregunta)]},
                           config={"recursion_limit": settings.max_pasos * 2 + 2})
    mensajes = estado["messages"]
    traza, ids, tools = _traza(mensajes)
    crudo = str(mensajes[-1].content)

    errores: list[str] = []
    informe, reparado = None, False
    try:
        informe = parsear_informe(crudo)
    except ValueError as e:
        errores.append(f"Salida inválida: {e}")
        try:  # un solo intento de reparación
            crudo = _reparar(llm, crudo, str(e))
            informe, reparado = parsear_informe(crudo), True
        except Exception as e2:  # noqa: BLE001
            errores.append(f"La reparación falló: {e2}")

    avisos = _revisar_fuentes(informe, ids, tools) if informe else []
    return ResultadoEjecucion(informe=informe, crudo=crudo, traza=traza, errores=errores,
                              advertencias=avisos, reparado=reparado)
