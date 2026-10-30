"""Interfaz Streamlit del agente de liquidaciones.

Ejecutar:  streamlit run app/streamlit_app.py
La app NO contiene logica del agente ni abre la base: todo pasa por la API (API_BASE_URL).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

import cliente  # noqa: E402
from cliente import ErrorApi  # noqa: E402

st.set_page_config(page_title="Asistente de liquidaciones", page_icon="🧾", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1200px;}
      .chip {display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.78rem;
             background:#eef1f7; color:#1e2761; margin-right:6px;}
      .chip-warn {background:#fff1dc; color:#8a4b00;}
      .chip-ok {background:#e3f4ea; color:#1d6b3a;}
      .pregunta {color:#555; font-size:0.9rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

PREGUNTAS_RAPIDAS = [  # (etiqueta del boton, pregunta completa)
    ("Explícame mi liquidación", "Explícame mi liquidación de septiembre."),
    ("Mi bono de productividad", "¿Por qué mi bono de este mes es cero?"),
    ("¿Cambió mi AFP?", "¿Por qué cambió mi AFP respecto al mes pasado?"),
    ("Tope imponible", "¿Cuál es el tope imponible y cuánto vale hoy?"),
    ("Probar guardrail", "¿Cuánto gana Tomás?"),
]


def md(texto: str) -> str:
    """Escapa '$' para que Streamlit no lo interprete como formula LaTeX."""
    return texto.replace("$", r"\$")


def clp(n: int | float | None) -> str:
    return "—" if n is None else f"${int(n):,}".replace(",", ".")


# ----------------------------------------------------------------------------- configuracion
def config_servidor() -> dict:
    """Configuración con la que arrancó la API (sin la API key)."""
    if "cfg_servidor" not in st.session_state:
        st.session_state["cfg_servidor"] = cliente.config_agente()
    return st.session_state["cfg_servidor"]


def ajustes_activos() -> dict:
    """Lo que se guardó en la ventana de configuración. La API lo aplica sobre su .env."""
    return dict(st.session_state.get("cfg_ui") or {})


def settings_activos() -> dict:
    return {**config_servidor(), **ajustes_activos()}


def _identidad_rag(cfg: dict) -> tuple:
    return (cfg["embeddings_provider"], cfg["embedding_model"], cfg["ollama_base_url"],
            str(cfg["chroma_dir"]), cfg["collection"])


def _volcar_dialogo(cfg: dict) -> None:
    """La ventana abre con la configuración que está en uso."""
    st.session_state["dlg_llm_provider"] = cfg["llm_provider"]
    st.session_state["dlg_llm_model"] = cfg["llm_model"]
    st.session_state["dlg_temperature"] = float(cfg["temperature"])
    st.session_state["dlg_max_pasos"] = int(cfg["max_pasos"])
    st.session_state["dlg_ollama_base_url"] = cfg["ollama_base_url"]
    st.session_state["dlg_unab_base_url"] = cfg["unab_base_url"]
    st.session_state["dlg_unab_api_key"] = cfg.get("unab_api_key", "")
    st.session_state["dlg_embeddings_provider"] = cfg["embeddings_provider"]
    st.session_state["dlg_embedding_model"] = cfg["embedding_model"]
    st.session_state["dlg_chroma_dir"] = str(cfg["chroma_dir"])
    st.session_state["dlg_collection"] = cfg["collection"]
    st.session_state["dlg_k"] = int(cfg["k"])


def _leer_borrador() -> dict:
    proveedor = st.session_state["dlg_llm_provider"]
    modelo = st.session_state["dlg_llm_model"].strip()
    emb_prov = st.session_state["dlg_embeddings_provider"]
    emb_modelo = st.session_state["dlg_embedding_model"].strip()
    borrador = {
        "llm_provider": proveedor,
        "llm_model": modelo or st.session_state["dlg_llm_model"],
        "temperature": float(st.session_state["dlg_temperature"]),
        "max_pasos": int(st.session_state["dlg_max_pasos"]),
        "ollama_base_url": st.session_state["dlg_ollama_base_url"].strip(),
        "unab_base_url": st.session_state["dlg_unab_base_url"].strip(),
        "embeddings_provider": emb_prov,
        "embedding_model": emb_modelo or st.session_state["dlg_embedding_model"],
        "chroma_dir": st.session_state["dlg_chroma_dir"].strip(),
        "collection": st.session_state["dlg_collection"].strip(),
        "k": int(st.session_state["dlg_k"]),
    }
    clave = st.session_state["dlg_unab_api_key"].strip()
    if clave:  # vacía = la que tiene la API en su .env
        borrador["unab_api_key"] = clave
    return borrador


def _validar_borrador(borrador: dict) -> str | None:
    if borrador["llm_provider"] != "mock" and not borrador["llm_model"]:
        return "Indica el modelo del agente."
    if borrador["embeddings_provider"] != "mock" and not borrador["embedding_model"]:
        return "Indica el modelo de embeddings."
    if (borrador["llm_provider"] == "unab" and not borrador.get("unab_api_key")
            and not config_servidor().get("unab_api_key_configurada")):
        return "El proveedor UNAB necesita una API key."
    if borrador["llm_provider"] == "unab" and not borrador["unab_base_url"]:
        return "Indica la URL base de UNAB."
    if borrador["llm_provider"] == "ollama" or borrador["embeddings_provider"] == "ollama":
        if not borrador["ollama_base_url"]:
            return "Indica la URL de Ollama."
    if not st.session_state["dlg_chroma_dir"].strip():
        return "Indica la carpeta de la base Chroma."
    if not borrador["collection"]:
        return "Indica el nombre de la colección."
    return None


def _guardar_configuracion(reconstruir: bool) -> None:
    borrador = _leer_borrador()
    error = _validar_borrador(borrador)
    if error:
        st.error(error)
        return
    anterior = settings_activos()
    nuevo = {**config_servidor(), **borrador}
    if reconstruir:
        with st.spinner("Reconstruyendo el índice…"):
            info = _llamar(cliente.reconstruir_indice, borrador)
        if info is None:
            return
    st.session_state["cfg_ui"] = borrador
    rag_cambio = _identidad_rag(anterior) != _identidad_rag(nuevo)
    mensaje = "Configuración aplicada."
    if reconstruir:
        mensaje += f" Índice reconstruido ({info['fragmentos']} fragmentos)."
    elif rag_cambio:
        mensaje += " El índice se actualizará en la próxima pregunta."
    st.session_state["config_abierta"] = False
    st.session_state["aviso_config"] = mensaje
    st.rerun()


def _restaurar_configuracion() -> None:
    st.session_state.pop("cfg_ui", None)
    for clave in [k for k in st.session_state if k.startswith("dlg_")]:
        del st.session_state[clave]
    st.session_state["config_abierta"] = False
    st.session_state["aviso_config"] = "Se restauró la configuración con la que arrancó la app."
    st.rerun()


def _al_cerrar_configuracion() -> None:
    st.session_state["config_abierta"] = False


@st.dialog("Configuración", width="large", on_dismiss=_al_cerrar_configuracion)
def ventana_configuracion() -> None:
    """Agente (LLM) y base vectorial del RAG."""
    st.caption("Estos valores valen para esta sesión y viajan con cada consulta a la API. "
               "Al reiniciar la API se vuelve a leer su archivo .env.")
    col_agente, col_rag = st.columns(2)
    with col_agente:
        st.subheader("Agente")
        st.selectbox(
            "Proveedor", ["ollama", "unab", "mock"], key="dlg_llm_provider",
            help="mock responde sin red. unab usa la API compatible con OpenAI.",
        )
        st.text_input("Modelo", key="dlg_llm_model", disabled=st.session_state["dlg_llm_provider"] == "mock")
        st.number_input("Temperatura", min_value=0.0, max_value=2.0, step=0.1, key="dlg_temperature")
        st.number_input("Máximo de pasos", min_value=1, max_value=30, step=1, key="dlg_max_pasos",
                        help="Tope de idas y vueltas del agente con sus herramientas.")
        if st.session_state["dlg_llm_provider"] == "unab":
            st.text_input("URL base de UNAB", key="dlg_unab_base_url")
            st.text_input("API key de UNAB", type="password", key="dlg_unab_api_key",
                          help="Vacía = la que tiene la API en su .env.")
    with col_rag:
        st.subheader("Base RAG")
        st.selectbox("Proveedor de embeddings", ["ollama", "mock"], key="dlg_embeddings_provider")
        st.text_input("Modelo de embeddings", key="dlg_embedding_model",
                      disabled=st.session_state["dlg_embeddings_provider"] == "mock")
        st.text_input("Carpeta de Chroma (en la API)", key="dlg_chroma_dir")
        st.text_input("Colección", key="dlg_collection")
        st.number_input("Fragmentos por consulta (k)", min_value=1, max_value=20, step=1, key="dlg_k")
        borrador = _leer_borrador()
        vista = _llamar(cliente.vista_agente, borrador) if _validar_borrador(borrador) is None else None
        if vista is not None:
            info = vista["indice"]
            st.caption(f"{info['documentos']} documentos en el corpus de la base.")
            if info["al_dia"]:
                st.success(f"Índice al día · {info['fragmentos']} fragmentos.")
            elif info["existe"]:
                st.warning(f"Índice desactualizado · {info['fragmentos']} fragmentos.")
            else:
                st.info("Todavía no hay un índice en esta carpeta y colección.")
    if st.session_state["dlg_llm_provider"] == "ollama" or st.session_state["dlg_embeddings_provider"] == "ollama":
        st.text_input("URL de Ollama", key="dlg_ollama_base_url",
                      help="La usan el agente, los embeddings, o ambos, cuando el proveedor es ollama.")
    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        aplicar = st.button("Aplicar", type="primary", key="aplicar_config", use_container_width=True)
    with c2:
        reconstruir = st.button("Reconstruir índice", key="reconstruir_indice", use_container_width=True)
    with c3:
        restaurar = st.button("Valores iniciales", key="restaurar_config", use_container_width=True)
    if aplicar:
        _guardar_configuracion(reconstruir=False)
    elif reconstruir:
        _guardar_configuracion(reconstruir=True)
    elif restaurar:
        _restaurar_configuracion()


# ----------------------------------------------------------------------------- sidebar
def _llamar(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except ErrorApi as e:
        st.error(e.mensaje)
        return None


def configurar_sidebar() -> tuple[dict, str]:
    cfg = settings_activos()
    st.sidebar.header("Sesión")
    trabajadores = {t["worker_id"]: t for t in cliente.trabajadores()}
    wid = st.sidebar.selectbox(
        "Iniciar sesión como",
        list(trabajadores),
        format_func=lambda w: f"{trabajadores[w]['nombre']} · {trabajadores[w]['cargo']}",
        help="Simula al usuario autenticado. El agente solo puede ver SU información.",
    )
    if st.sidebar.button("Configuración", key="abrir_config", use_container_width=True):
        _volcar_dialogo(cfg)
        st.session_state["config_abierta"] = True
    if st.session_state.get("config_abierta"):
        ventana_configuracion()
    st.sidebar.divider()
    st.sidebar.checkbox("Mostrar traza del agente", value=True, key="ver_traza")
    return cfg, wid


# ----------------------------------------------------------------------------- pestañas
def tab_liquidacion(wid: str) -> None:
    perfil = _llamar(cliente.trabajador, wid)
    if perfil is None:
        return
    periodos = perfil["periodos"]
    periodo = st.selectbox("Período", periodos, index=len(periodos) - 1)
    liq = _llamar(cliente.liquidacion, wid, periodo)
    vigente = _llamar(cliente.trabajador, wid, periodo)
    if liq is None or vigente is None:
        return
    t = vigente["ficha"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Líquido a pagar", clp(liq["liquido_a_pagar"]))
    c2.metric("Total haberes", clp(liq["total_haberes"]))
    c3.metric("Total descuentos", clp(liq["total_descuentos"]))
    st.caption(f"{t['nombre']} · {t['cargo']} · contrato {t['tipo_contrato'].replace('_', ' ')} · "
               f"AFP {t['afp']} · {t['salud']}")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Haberes")
        filas = ([{"Concepto": h["concepto"], "Tipo": "Imponible", "Monto": clp(h["monto"])}
                  for h in liq["haberes_imponibles"]]
                 + [{"Concepto": h["concepto"], "Tipo": "No imponible", "Monto": clp(h["monto"])}
                    for h in liq["haberes_no_imponibles"]])
        st.dataframe(filas, hide_index=True, use_container_width=True)
    with col_b:
        st.subheader("Descuentos")
        st.dataframe([{"Concepto": d["concepto"], "Base": clp(d["base"]),
                       "Tasa": "—" if d["tasa"] is None else f"{d['tasa'] * 100:.2f}%",
                       "Monto": clp(d["monto"])} for d in liq["descuentos_legales"]],
                     hide_index=True, use_container_width=True)
    st.info("Esta tabla muestra la liquidación tal como la emitió el sistema, sin marcar errores. "
            "Pregúntale al asistente para revisarla.")


def mostrar_resultado(res: dict) -> None:
    if not res["ok"]:
        st.error("El modelo no entregó una salida que cumpla el contrato (JSON del esquema).")
        for e in res["errores"]:
            st.caption(e)
        st.code(res["crudo"] or "(vacío)", language="text")
        return
    inf = res["informe"]
    chips = []
    if inf["fuera_de_alcance"]:
        chips.append('<span class="chip chip-warn">Fuera de alcance</span>')
    if inf["requiere_revision_rrhh"]:
        chips.append('<span class="chip chip-warn">Requiere revisión de RR.HH.</span>')
    elif not inf["fuera_de_alcance"]:
        chips.append('<span class="chip chip-ok">Sin diferencias que revisar</span>')
    if res["reparado"]:
        chips.append('<span class="chip">JSON reparado por el harness</span>')
    st.markdown(" ".join(chips), unsafe_allow_html=True)
    st.markdown(md(inf["respuesta"]))

    if inf["descuentos"]:
        st.markdown("**Tus descuentos**")
        for d in inf["descuentos"]:
            st.markdown(md(f"- **{d['concepto']} — {clp(d['monto'])}**: {d['explicacion']}"))
    for h in inf["hallazgos"]:
        dif = f" (diferencia {clp(h['monto_diferencia'])})" if h["monto_diferencia"] else ""
        texto = f"**{h['severidad'].upper()}** — {h['descripcion']}{dif}" + (
            f"\n\n{h['recomendacion']}" if h["recomendacion"] else "")
        {"info": st.info, "revisar": st.warning, "critico": st.error}[h["severidad"]](md(texto))
    if inf["fuentes"]:
        st.markdown("**Fuentes:** " + " · ".join(
            f"`{f['referencia']}`" + ("" if f["tipo"] == "documento" else " (tool)") for f in inf["fuentes"]))
    for aviso in res["advertencias"]:
        st.warning(f"Grounding check: {aviso}")

    if st.session_state.get("ver_traza", True):
        with st.expander(f"Traza del agente ({len(res['traza'])} llamadas a tools)"):
            if not res["traza"]:
                st.caption("El agente respondió sin llamar a ninguna tool.")
            for paso in res["traza"]:
                st.markdown(f"**{paso['paso']}. `{paso['herramienta']}`** · args: `{paso['args']}`")
                st.code(paso["resultado"][:900] + ("…" if len(paso["resultado"]) > 900 else ""), language="json")
        with st.expander("JSON validado contra el contrato"):
            st.json(inf)


def tab_asistente(wid: str) -> None:
    historial = st.session_state.setdefault("historial", {}).setdefault(wid, [])
    st.caption("Cada pregunta es independiente (el agente no tiene memoria de conversación).")

    cols = st.columns(len(PREGUNTAS_RAPIDAS))
    for i, (col, (etiqueta, pregunta)) in enumerate(zip(cols, PREGUNTAS_RAPIDAS)):
        if col.button(etiqueta, use_container_width=True, key=f"rapida_{i}", help=pregunta):
            st.session_state["pendiente"] = pregunta
    with st.form("form_pregunta", clear_on_submit=True):
        texto = st.text_input("O escribe tu pregunta", placeholder="Ej.: ¿Por qué me descuentan impuesto?")
        if st.form_submit_button("Preguntar") and texto.strip():
            st.session_state["pendiente"] = texto.strip()

    pregunta = st.session_state.pop("pendiente", None)
    if pregunta:
        with st.spinner("El agente está consultando sus herramientas…"):
            res = _llamar(cliente.consultar, wid, pregunta, ajustes_activos())
        if res is not None:
            historial.insert(0, {"pregunta": pregunta, "res": res})
        else:
            st.caption("Revisa el proveedor en Configuración. Con LLM y embeddings en 'mock' la API responde sin red.")

    if not historial:
        st.info("Elige una pregunta rápida o escribe la tuya.")
    for item in historial:
        with st.container(border=True):
            st.markdown(f'<div class="pregunta">🙋 {item["pregunta"]}</div>', unsafe_allow_html=True)
            mostrar_resultado(item["res"])


ARQUITECTURA = """
digraph G {
  rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#1e2761", fillcolor="#eef1f7"];
  edge [color="#555555", fontname="Helvetica", fontsize=9];
  U [label="Trabajador\\n(sesión autenticada)", fillcolor="#fff1dc"];
  A [label="Streamlit"]; P [label="API\\n(FastAPI)"]; H [label="Harness\\n(valida JSON, grounding)"]; G [label="Agente\\ncreate_agent + LLM"];
  T1 [label="obtener_liquidacion"]; T2 [label="calcular_descuentos_esperados"]; T3 [label="consultar_parametros"]; T4 [label="buscar_en_documentos", fillcolor="#e3f4ea"];
  C [label="Chroma\\n(filtro worker_id)", shape=cylinder, fillcolor="#e3f4ea"];
  D [label="Base de datos\\n(PostgreSQL) y reglas\\n(calculos.py)", shape=cylinder];
  U -> A -> P -> H -> G; G -> T1; G -> T2; G -> T3; G -> T4; T4 -> C; T1 -> D; T2 -> D; T3 -> D;
}
"""


def tab_arquitectura() -> None:
    st.graphviz_chart(ARQUITECTURA, use_container_width=True)
    st.markdown(
        """
**Por qué RAG aquí.** Lo que dice cada contrato y cada política es texto largo, distinto por persona
y cambia con los anexos: no cabe en un prompt fijo y no se puede calcular. Eso se *recupera*.
Lo que se puede calcular (descuentos, topes) lo hacen las tools, porque el LLM no debe hacer aritmética.

**Controles de seguridad.**
- El id del trabajador no es parámetro de ninguna tool: viene de la sesión.
- El retriever filtra por `worker_id` (el trabajador ve lo suyo y lo compartido).
- Toda fuente citada debe haber sido recuperada en la misma ejecución.
- La salida debe cumplir `agent/output.schema.json`; si no, el harness reintenta una vez.

**Límites del ejercicio.** Solo Fonasa, sin horas extra, anticipos ni licencias. El agente explica y marca
diferencias; no certifica cumplimiento legal. Ver `docs/gaps_de_negocio.md`.
"""
    )


def main() -> None:
    st.title("🧾 Asistente de liquidaciones")
    st.caption("Clínica Traumatología Cóndor (ficticia) · Caso didáctico del curso CINF110")
    try:
        cfg, wid = configurar_sidebar()
    except ErrorApi as e:
        st.error(e.mensaje)
        st.stop()
    aviso = st.session_state.pop("aviso_config", None)
    if aviso:
        st.success(aviso)
    vista = _llamar(cliente.vista_agente, ajustes_activos()) or {
        "descripcion": {"llm": "—", "embeddings": "—"}, "collection": cfg["collection"], "k": cfg["k"]}
    desc = vista["descripcion"]
    st.markdown(
        f'<span class="chip">LLM: {desc["llm"]}</span>'
        f'<span class="chip">Embeddings: {desc["embeddings"]}</span>'
        f'<span class="chip">RAG: {vista["collection"]} · k={vista["k"]}</span>',
        unsafe_allow_html=True,
    )
    t1, t2, t3 = st.tabs(["Mi liquidación", "Asistente", "Cómo funciona"])
    with t1:
        tab_liquidacion(wid)
    with t2:
        tab_asistente(wid)
    with t3:
        tab_arquitectura()


main()
