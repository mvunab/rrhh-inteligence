"""Centro de control de Recursos Humanos.

Ejecutar:  streamlit run rrhh/streamlit_app.py --server.port 8502
Habla solo con la API (API_BASE_URL). No abre el motor ni la base de datos.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import cliente  # noqa: E402
from cliente import ErrorApi, base_url  # noqa: E402

st.set_page_config(page_title="Centro de control · RR.HH.", page_icon="🗂️", layout="wide")


def clp(n: int | float | None) -> str:
    if n is None:
        return "—"
    return ("-" if n < 0 else "") + f"${abs(int(n)):,}".replace(",", ".")


def _delta(n: int) -> str | None:
    return None if n == 0 else ("+" if n > 0 else "") + clp(n)


_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def mes(periodo: str) -> str:
    """2026-09 -> septiembre 2026."""
    try:
        anio, numero = periodo.split("-")
        return f"{_MESES[int(numero) - 1]} {anio}"
    except (ValueError, IndexError):
        return periodo


def _llamar(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except ErrorApi as e:
        st.error(e.mensaje)
        return None


_SEV_ETIQUETA = {"critico": "Crítico", "revisar": "Revisar", "sin diferencias": "Sin diferencias"}
_SEV_COLOR = {"critico": "red", "revisar": "orange", "sin diferencias": "green"}
_DECISIONES = ("mantener", "corregir", "derivar")


def _titulo(texto: str) -> str:
    return texto[:1].upper() + texto[1:] if texto else texto


def _filas_seleccionadas(evento) -> list[int]:
    seleccion = getattr(evento, "selection", None)
    filas = getattr(seleccion, "rows", None)
    if filas is None and isinstance(seleccion, dict):
        filas = seleccion.get("rows", [])
    return list(filas or [])


_TIPO = {"diferencia": "Diferencia de cálculo", "revision": "Revisión humana"}
_TIPO_COLOR = {"diferencia": "red", "revision": "blue"}
_ORIGEN_FILA = {("trabajador",): "Trabajador", ("sistema",): "Sistema",
                ("trabajador", "sistema"): "Trabajador y sistema"}


def zona_bandeja() -> None:
    items = _llamar(cliente.bandeja)
    if items is None:
        return
    if not items:
        st.info("No hay nada que revisar. Aparece aquí cuando el motor encuentra una diferencia al cargar "
                "una liquidación o cuando un trabajador pide que una persona revise la suya.")
        return
    ids = [i["id"] for i in items]
    if st.session_state.get("item_id") not in ids:
        st.session_state["item_id"] = ids[0]
    pendientes = sum(1 for i in items if i["estado"] == "pendiente")
    st.caption(f"{len(items)} liquidaciones en revisión · {pendientes} pendientes. Una fila por liquidación: "
               "**Diferencia de cálculo** si el motor o el agente encontraron un monto mal calculado, "
               "**Revisión humana** si el trabajador solo pidió que una persona lo mire.")

    lista, detalle = st.columns([1.1, 1.35], gap="large")
    with lista:
        tabla = pd.DataFrame([{
            "Trabajador": i["nombre"],
            "Área": i["area"],
            "Liquidación": mes(i["periodo"] or ""),
            "Tipo": _TIPO[i["tipo"]],
            "Origen": _ORIGEN_FILA.get(tuple(i["origen"]), "—"),
            "Estado": _titulo(i["estado"]),
            "Diferencia": clp(i["diferencia_total"]) if i["tipo"] == "diferencia" else "—",
        } for i in items])
        evento = st.dataframe(
            tabla.style.map(lambda v: "color: #b91c1c; font-weight: 600" if v == _TIPO["diferencia"] else "",
                            subset=["Tipo"]),
            hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
            key="bandeja",
        )
        filas = _filas_seleccionadas(evento)
        if filas and filas[0] < len(ids):
            st.session_state["item_id"] = ids[filas[0]]
    with detalle:
        zona_item(next(i for i in items if i["id"] == st.session_state["item_id"]))


def zona_item(item: dict) -> None:
    st.subheader(item["nombre"])
    st.caption(f"Liquidación de {mes(item['periodo'] or '')} · {item['area']}")
    with st.container(horizontal=True):
        st.badge(_TIPO[item["tipo"]], color=_TIPO_COLOR[item["tipo"]])
        st.badge(_titulo(item["estado"]), color="orange" if item["estado"] == "pendiente" else "green")
        if item.get("decision"):
            st.badge(f"Decisión: {_titulo(item['decision'])}", color="gray")

    zona_pedidos(item)
    caso = _llamar(cliente.caso, item["caso_id"]) if item.get("caso_id") else None
    if caso and (caso.get("hay_diferencias") or caso["estado"] != "pendiente"):
        st.divider()
        zona_caso(caso)
    elif item["tipo"] == "revision":
        st.caption("El motor no encuentra diferencias de cálculo en esta liquidación.")


def zona_pedidos(item: dict) -> None:
    """Lo que el trabajador escribió y la respuesta del analista. Varias solicitudes de la misma
    liquidación se responden juntas."""
    solicitudes = item["solicitudes"]
    if not solicitudes:
        st.caption("La detectó el sistema al cargar la liquidación. El trabajador no ha pedido revisión.")
        return
    abiertas = [s for s in solicitudes if s["estado"] == "pendiente"]
    st.markdown("**Conversación con el agente**")
    st.caption(" · ".join(f"{s['id']} {_titulo(s['estado']).lower()} ({_motivos(s).lower()})"
                          for s in solicitudes))
    with st.container(border=True):
        with st.container(height=460, autoscroll=True, border=False):
            for quien, instante, texto in _hilo(solicitudes):
                with st.chat_message(**_AUTOR[quien]):
                    st.caption(f"{_ETIQUETA_AUTOR[quien]} · {_hora(instante)}")
                    st.markdown(texto.replace("$", r"\$"))
        if abiertas:
            respuesta = st.chat_input("Responde al trabajador como RR.HH.…", key=f"respuesta-{item['id']}")
            if respuesta and respuesta.strip():
                if all(_llamar(cliente.responder_solicitud, s["id"], respuesta) is not None for s in abiertas):
                    st.rerun()
        else:
            st.caption("Respondida. Si el trabajador vuelve a escribir, la conversación sigue aquí.")


_AUTOR = {"trabajador": {"name": "user"}, "agente": {"name": "assistant"},
          "rrhh": {"name": "RR.HH.", "avatar": ":material/support_agent:"}}
_ETIQUETA_AUTOR = {"trabajador": "Trabajador", "agente": "Agente", "rrhh": "RR.HH."}


def _hilo(solicitudes: list[dict]) -> list[tuple[str, str, str]]:
    """Todas las solicitudes de la liquidación en un solo hilo, en orden de llegada."""
    hilo = []
    for solicitud in solicitudes:
        for mensaje in solicitud["mensajes"]:
            hilo.append(("trabajador", mensaje["creado"], mensaje["texto"]))
            if mensaje.get("agente"):
                hilo.append(("agente", mensaje["creado"], mensaje["agente"]))
        if solicitud["estado"] == "respondida" and solicitud.get("respuesta"):
            hilo.append(("rrhh", solicitud.get("respondido") or solicitud["creado"], solicitud["respuesta"]))
    return sorted(hilo, key=lambda paso: paso[1])


def _hora(instante: str) -> str:
    try:
        return datetime.fromisoformat(instante).astimezone(_CHILE).strftime("%d-%m %H:%M")
    except (TypeError, ValueError):
        return ""


_CHILE = ZoneInfo("America/Santiago")


def zona_caso(caso: dict) -> None:
    st.markdown("**Diferencia de cálculo**")
    cifra, sev = st.columns([1.2, 1])
    cifra.metric("Diferencia", clp(caso["diferencia_total"]))
    sev.badge(_SEV_ETIQUETA.get(caso["severidad"], caso["severidad"]),
              color=_SEV_COLOR.get(caso["severidad"], "gray"))
    if caso.get("reabierto"):
        st.warning("Una carga nueva cambió las diferencias. El caso volvió a pendiente.")
    if not caso.get("hay_diferencias", True):
        st.success("Con la ficha vigente (contrato y anexos) esta liquidación ya no tiene diferencias.")

    diferencias = [linea for linea in caso["lineas"] if linea["estado"] == "diferencia"]
    alineadas = [linea for linea in caso["lineas"] if linea["estado"] != "diferencia"]
    for linea in diferencias:
        with st.container(border=True):
            st.markdown(f"**{linea['concepto']}**")
            esperado, pagado, delta = st.columns(3)
            esperado.metric("Esperado", clp(linea["esperado"]))
            pagado.metric("Pagado", clp(linea["pagado"]))
            delta.metric("Diferencia", clp(linea["diferencia"]))
            if linea.get("causa_probable"):
                st.caption(linea["causa_probable"].replace("$", r"\$"))
    if alineadas:
        with st.expander(f"Conceptos sin diferencia ({len(alineadas)})", expanded=not diferencias):
            st.dataframe(
                [{
                    "Concepto": linea["concepto"],
                    "Esperado": clp(linea["esperado"]),
                    "Pagado": clp(linea["pagado"]),
                } for linea in alineadas],
                hide_index=True,
                use_container_width=True,
            )

    st.markdown("**Explicación del agente**")
    informe = caso.get("informe") or {}
    if informe.get("respuesta"):
        st.markdown(informe["respuesta"].replace("$", r"\$"))
    elif informe.get("error"):
        st.error(informe["error"])
    else:
        st.caption("Todavía no hay una explicación guardada para este caso.")
    if st.button("Pedir explicación al agente", key=f"explicar-{caso['id']}"):
        with st.spinner("El agente está revisando la liquidación cargada…"):
            if _llamar(cliente.explicar, caso["id"]) is not None:
                st.rerun()

    zona_borrador(caso)

    st.markdown("**Decisión**")
    with st.form(f"decision-{caso['id']}"):
        decision = st.radio(
            "Decisión",
            _DECISIONES,
            index=_DECISIONES.index(caso["estado"]) if caso["estado"] in _DECISIONES else 0,
            format_func=_titulo,
            horizontal=True,
        )
        nota = st.text_area(
            "Nota",
            value=caso.get("nota") or "",
            placeholder="Qué se revisó y qué se va a hacer.",
        )
        if st.form_submit_button("Registrar decisión"):
            if _llamar(cliente.decidir, caso["id"], decision, nota) is not None:
                st.success("Decisión registrada.")
                st.rerun()


def zona_borrador(caso: dict) -> None:
    """Propuesta de liquidación corregida: se genera, el analista la ajusta y la emite."""
    st.markdown("**Liquidación corregida**")
    borrador_id = f"B-{caso['worker_id']}-{caso['periodo']}"
    borrador = next((b for b in (_llamar(cliente.borradores) or []) if b["id"] == borrador_id), None)
    if borrador is None or (borrador["estado"] == "emitida" and caso.get("hay_diferencias")):
        st.caption("El motor recalcula la liquidación con la ficha vigente y los parámetros del periodo. "
                   "Queda como borrador hasta que la emitas.")
        if st.button("Generar propuesta corregida", key=f"generar-{caso['id']}", type="primary"):
            if _llamar(cliente.generar_borrador, caso["worker_id"], caso["periodo"], _analista()) is not None:
                st.rerun()
        return

    emitida = borrador["estado"] == "emitida"
    version = borrador.get("version", 1)
    original, propuesta = borrador["original"], borrador["propuesta"]
    antes, despues, estado = st.columns([1, 1, 1])
    antes.metric("Líquido emitido", clp(original["liquido_a_pagar"]))
    despues.metric("Líquido propuesto", clp(propuesta["liquido_a_pagar"]),
                   delta=_delta(propuesta["liquido_a_pagar"] - original["liquido_a_pagar"]))
    estado.badge("Emitida" if emitida else f"Borrador v{version}", color="green" if emitida else "orange")

    zona_diff(borrador)
    zona_trazabilidad(borrador)

    pdf = _llamar(cliente.pdf_borrador, borrador["id"])
    if pdf is not None:
        st.download_button(
            "Descargar PDF" if emitida else "Descargar PDF borrador", data=pdf,
            file_name=f"liquidacion_{borrador['worker_id']}_{borrador['periodo']}_{borrador['estado']}.pdf",
            mime="application/pdf", key=f"pdf-{borrador['id']}-{borrador.get('version', 1)}",
        )
    if emitida:
        st.success(f"Emitida el {borrador['emitido'][:10]}. Es la liquidación vigente del trabajador.")
        return

    with st.expander("Ajustar haberes de la propuesta"):
        st.caption("Cambia montos o agrega conceptos. Los descuentos legales se recalculan solos.")
        filas = ([{"Concepto": h["concepto"], "Tipo": "Imponible", "Monto": h["monto"]}
                  for h in propuesta["haberes_imponibles"]]
                 + [{"Concepto": h["concepto"], "Tipo": "No imponible", "Monto": h["monto"]}
                    for h in propuesta["haberes_no_imponibles"]])
        editadas = st.data_editor(
            pd.DataFrame(filas), num_rows="dynamic", hide_index=True, use_container_width=True,
            key=f"haberes-{borrador['id']}-{borrador.get('version', 1)}-{borrador['actualizado']}",
            column_config={
                "Tipo": st.column_config.SelectboxColumn(options=["Imponible", "No imponible"], required=True),
                "Monto": st.column_config.NumberColumn(min_value=0, step=1, format="%d", required=True),
            },
        )
        nota_ajuste = st.text_input("Motivo del ajuste", value=borrador.get("nota") or "",
                                    key=f"nota-ajuste-{borrador['id']}")
        if st.button("Guardar ajustes", key=f"guardar-{borrador['id']}"):
            filas_validas = editadas.dropna(subset=["Concepto", "Monto"])
            imponibles = [{"concepto": f["Concepto"], "monto": int(f["Monto"])}
                          for _, f in filas_validas.iterrows() if f["Tipo"] == "Imponible"]
            no_imponibles = [{"concepto": f["Concepto"], "monto": int(f["Monto"])}
                             for _, f in filas_validas.iterrows() if f["Tipo"] != "Imponible"]
            if _llamar(cliente.ajustar_borrador, borrador["id"], imponibles, no_imponibles, nota_ajuste,
                       _analista()) is not None:
                st.rerun()

    with st.form(f"emitir-{borrador['id']}-{version}"):
        st.markdown(f"**Emitir la versión v{version}**")
        st.caption("Reemplaza a la liquidación vigente. La anterior queda guardada en la bitácora.")
        revisado = st.checkbox(f"Revisé los cambios de la versión v{version} contra la liquidación emitida")
        nota = st.text_input("Nota de emisión", placeholder="Ej.: Se aplica tope imponible y se devuelve la diferencia.")
        if st.form_submit_button("Emitir liquidación", type="primary"):
            if not revisado:
                st.error("Marca que revisaste el diff antes de emitir.")
            elif not nota.strip():
                st.error("Escribe una nota para emitir.")
            elif _llamar(cliente.emitir_borrador, borrador["id"], nota, version, _analista()) is not None:
                st.rerun()


def zona_diff(borrador: dict) -> None:
    """Qué cambia, como un diff de código: en rojo lo que sale, en verde lo que entra."""
    version = borrador.get("version", 1)
    bases = ["emitida"] + [str(n) for n in range(version - 1, 0, -1)]
    base = st.selectbox(
        "Comparar con", bases, key=f"base-{borrador['id']}-{version}",
        format_func=lambda b: "Liquidación emitida" if b == "emitida" else f"Propuesta v{b}",
    )
    diff = _llamar(cliente.diff_borrador, borrador["id"], base)
    if diff is None:
        return
    simple = diff["en_simple"]
    with st.container(border=True):
        st.caption("EN SIMPLE")
        st.markdown(f"**{simple['titular']}**".replace("$", r"\$"))
        st.markdown(f"Líquido a pagar: {clp(simple['liquido_antes'])} → **{clp(simple['liquido_despues'])}**"
                    .replace("$", r"\$"))
        explicados = set()
        for punto in simple["puntos"]:
            icono = (":green[:material/arrow_upward:]" if punto["favorece_al_trabajador"]
                     else ":red[:material/arrow_downward:]")
            st.markdown(f"{icono} {punto['texto']}".replace("$", r"\$"))
            if punto.get("por_que") and punto["por_que"] not in explicados:
                explicados.add(punto["por_que"])
                st.caption(f"Por qué: {punto['por_que']}".replace("$", r"\$"))
        st.caption(f"{simple['pie']} Flecha verde: el cambio favorece al trabajador; roja: lo perjudica.")
    n = len(diff["cambios"])
    with st.expander(f"Ver detalle técnico (diff · {n} {'concepto' if n == 1 else 'conceptos'})"):
        st.code(diff["texto"], language="diff", line_numbers=False)
        if borrador.get("ajustes"):
            st.caption("Motivo técnico de cada cambio respecto de la liquidación emitida")
            st.dataframe([{
                "Concepto": a["concepto"], "Emitido": clp(a["emitido"]), "Propuesto": clp(a["propuesto"]),
                "Diferencia": clp(a["diferencia"]), "Motivo": a["motivo"],
            } for a in borrador["ajustes"]], hide_index=True, use_container_width=True)


_ACCION = {
    "propuesta_generada": "Propuesta generada",
    "propuesta_ajustada": "Propuesta ajustada",
    "liquidacion_emitida": "Liquidación emitida",
    "liquidacion_reemplazada": "Liquidación vigente reemplazada",
}


def zona_trazabilidad(borrador: dict) -> None:
    eventos = _llamar(cliente.historial_borrador, borrador["id"]) or []
    with st.expander(f"Trazabilidad ({len(eventos)} {'evento' if len(eventos) == 1 else 'eventos'})"):
        if not eventos:
            st.caption("Sin eventos registrados.")
            return
        st.caption("Cada propuesta, ajuste y emisión queda registrado con quién lo hizo y una copia completa "
                   "de la liquidación. Los eventos no se editan ni se borran.")
        st.dataframe([{
            "Cuándo": _hora(e["cuando"]),
            "Quién": e["autor"],
            "Acción": _ACCION.get(e["accion"], e["accion"]),
            "Versión": f"v{e['datos']['version']}" if e["datos"].get("version") else "—",
            "Líquido": clp(e["datos"].get("liquido") or (e["datos"].get("nueva") or {}).get("liquido_a_pagar")),
            "Detalle": _detalle_evento(e),
        } for e in reversed(eventos)], hide_index=True, use_container_width=True)


def _detalle_evento(evento: dict) -> str:
    datos = evento["datos"]
    if evento["accion"] == "liquidacion_reemplazada":
        anterior = datos.get("anterior") or {}
        return (f"Antes {clp(anterior.get('liquido_a_pagar'))} ({datos.get('origen_anterior')}). "
                + (datos.get("nota") or ""))
    partes = []
    if datos.get("cambios") is not None:
        partes.append(", ".join(c["concepto"] for c in datos["cambios"]) or "sin cambios de montos")
    if datos.get("nota"):
        partes.append(datos["nota"])
    if datos.get("reemplaza_version"):
        partes.append(f"Reemplaza la v{datos['reemplaza_version']} ({datos.get('estado_previo')})")
    return " · ".join(partes)


def _analista() -> str:
    perfil = st.session_state.get("perfil_analista") or {}
    return perfil.get("nombre") or "Analista RR.HH."


def _asegurar_sesion() -> bool:
    """Login del analista demo (o ANALISTA_EMAIL / ANALISTA_PASSWORD)."""
    if st.session_state.get("perfil_analista"):
        return True
    perfil = _llamar(cliente.autenticar)
    if perfil is None:
        st.error("No se pudo iniciar sesión en la API. Revisa ANALISTA_EMAIL y ANALISTA_PASSWORD.")
        return False
    st.session_state["perfil_analista"] = perfil
    return True


_ORIGEN = {"base": "Sistema", "migrado": "Sistema", "excel": "Excel", "pdf": "PDF",
           "rectificada": "Rectificada"}


def zona_carga() -> None:
    st.subheader("Liquidaciones")
    st.caption("El mes sale de cada documento. No hace falta indicarlo al cargar. Excel con la plantilla, o un PDF con texto (no un escaneo).")
    archivo = _llamar(cliente.plantilla)
    if archivo is not None:
        st.download_button(
            "Descargar plantilla Excel",
            data=archivo,
            file_name="plantilla_liquidaciones.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    excel = st.file_uploader("Excel de liquidaciones", type=["xlsx"])
    if excel is not None and st.button("Cargar liquidaciones"):
        resultado = _llamar(cliente.cargar_excel, excel.name, excel.getvalue())
        if resultado is not None:
            st.success(resultado["resumen"])
    pdf_liq = st.file_uploader("PDF de liquidación", type=["pdf"], key="pdf_liquidacion")
    if pdf_liq is not None and st.button("Cargar PDF de liquidación"):
        resultado = _llamar(cliente.cargar_pdf_liquidacion, pdf_liq.name, pdf_liq.getvalue())
        if resultado is not None:
            st.success(resultado["resumen"])

    personas = _llamar(cliente.trabajadores) or []
    nombres = {p["worker_id"]: p["nombre"] for p in personas}
    cargadas = _llamar(cliente.liquidaciones) or []
    if cargadas:
        st.caption("Liquidaciones en la base")
        st.dataframe(
            [{
                "Trabajador": nombres.get(liq["worker_id"], liq["worker_id"]),
                "Liquidación de": mes(liq["periodo"]),
                "Líquido a pagar": clp(liq["liquido_a_pagar"]),
                "Origen": _ORIGEN.get(liq["origen"], liq["origen"]),
            } for liq in sorted(cargadas, key=lambda x: (x["periodo"], x["worker_id"]))],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Contrato")
    st.caption("El contrato que cargas pasa a ser el vigente del trabajador y reemplaza al anterior.")
    if not personas:
        return
    worker = st.selectbox(
        "Trabajador del contrato",
        [p["worker_id"] for p in personas],
        format_func=lambda w: next(f"{p['worker_id']} · {p['nombre']}" for p in personas if p["worker_id"] == w),
    )
    vigente_desde = st.date_input("Vigente desde", value=date.today(), key="contrato_desde")
    cambios_contrato = _campos_ficha("contrato")
    pdf = st.file_uploader("PDF del contrato", type=["pdf"], key="contrato_pdf")
    if pdf is not None and st.button("Cargar contrato"):
        resultado = _llamar(cliente.cargar_contrato, worker, pdf.name, pdf.getvalue(),
                            vigente_desde.isoformat(), cambios_contrato)
        if resultado is not None:
            st.success(resultado["resumen"])

    st.subheader("Anexo de contrato")
    st.caption("Un anexo se suma al contrato del trabajador elegido arriba. Puede haber varios, cada uno con su fecha.")
    anexo_desde = st.date_input("Anexo vigente desde", value=date.today(), key="anexo_desde")
    descripcion = st.text_input("De qué trata", placeholder="Ej.: cambio de AFP, nuevo bono, jornada", key="anexo_texto")
    cambios_anexo = _campos_ficha("anexo")
    anexo = st.file_uploader("PDF del anexo", type=["pdf"], key="anexo_pdf")
    if anexo is not None and st.button("Cargar anexo"):
        resultado = _llamar(cliente.cargar_anexo, worker, anexo.name, anexo.getvalue(),
                            anexo_desde.isoformat(), descripcion, cambios_anexo)
        if resultado is not None:
            st.success(resultado["resumen"])

    vigentes = _llamar(cliente.contratos) or []
    if vigentes:
        st.caption("Ficha vigente hoy, con el contrato y los anexos que la cambian")
        st.dataframe(
            [{
                "Trabajador": c["nombre"],
                "AFP": c["ficha"]["afp"],
                "Contrato": c["ficha"]["tipo_contrato"].replace("_", " "),
                "Sueldo base": clp(c["ficha"]["sueldo_base"]),
                "Contrato vigente desde": c["vigente_desde"] or "—",
                "Origen": "cargado" if c["origen"] == "cargado" else "carga inicial",
                "Anexos": "; ".join(
                    f"{a['vigente_desde']} {a['descripcion'] or 'sin descripción'}"
                    + (f" ({', '.join(a['cambios'])})" if a["cambios"] else "")
                    for a in c["anexos"]
                ) or "—",
            } for c in vigentes],
            hide_index=True,
            use_container_width=True,
        )


_AFP = ("Uno", "Modelo", "PlanVital", "Habitat", "Capital", "Cuprum", "ProVida")


def _campos_ficha(prefijo: str) -> dict:
    """Campos de la ficha que este documento cambia. Lo que queda en blanco no cambia."""
    with st.expander("Campos que cambia en la ficha (opcional)"):
        st.caption("El cálculo de lo esperado usa estos valores desde la fecha de vigencia.")
        c1, c2, c3 = st.columns(3)
        afp = c1.selectbox("AFP", ("sin cambio",) + _AFP, key=f"{prefijo}_afp")
        tipo = c2.selectbox("Tipo de contrato", ("sin cambio", "indefinido", "plazo_fijo"), key=f"{prefijo}_tipo")
        sueldo = c3.number_input("Sueldo base", min_value=0, step=10000, value=None, key=f"{prefijo}_sueldo")
        c4, c5, c6 = st.columns(3)
        bono = c4.number_input("Bono de productividad", min_value=0, step=10000, value=None, key=f"{prefijo}_bono")
        meta = c5.number_input("Meta de atenciones", min_value=0, step=1, value=None, key=f"{prefijo}_meta")
        turno = c6.number_input("Asignación de turno", min_value=0, step=10000, value=None, key=f"{prefijo}_turno")
    cambios = {
        "afp": None if afp == "sin cambio" else afp,
        "tipo_contrato": None if tipo == "sin cambio" else tipo,
        "sueldo_base": sueldo, "bono_monto": bono, "bono_meta_atenciones": meta, "asignacion_turno": turno,
    }
    return {k: v for k, v in cambios.items() if v is not None}


def zona_conectores() -> None:
    lista = _llamar(cliente.conectores)
    if lista is None:
        return
    for conector in lista:
        marca = "activo" if conector["disponible"] else "en espera"
        st.markdown(f"**{conector['nombre']}** · {marca}")
        st.caption(conector["detalle"])


_MOTIVO = {
    "trabajador": "La pidió el trabajador",
    "agente": "La marcó el agente",
}


def _motivos(solicitud: dict) -> str:
    return " · ".join(_MOTIVO.get(m, m) for m in solicitud.get("motivos") or [])


def zona_sectores() -> None:
    filas = _llamar(cliente.estadisticas_solicitudes)
    if filas is None:
        return
    st.caption("Solo cuentan las solicitudes que el trabajador envió. Es diferencia de cálculo si el motor "
               "o el agente encontraron un monto mal calculado; si no, es revisión humana.")
    st.dataframe(
        [{
            "Área": f["area"],
            "Trabajadores": f["trabajadores"],
            "Solicitudes": f["solicitudes"],
            "Diferencias de cálculo": f["diferencias"],
            "Revisión humana": f["revisiones"],
            "Pendientes": f["pendientes"],
        } for f in filas],
        hide_index=True,
        use_container_width=True,
    )


def main() -> None:
    if not _asegurar_sesion():
        return
    perfil = st.session_state["perfil_analista"]
    st.sidebar.markdown(f"**{perfil['nombre']}**")
    st.sidebar.caption(perfil.get("cargo") or perfil.get("email") or "")
    st.title("Centro de control de RR.HH.")
    st.caption(f"Carga y decisiones pasan por la API en {base_url()}.")
    bandeja, sectores, carga, conectores = st.tabs(["Bandeja", "Sectores", "Cargar", "Conectores"])
    with bandeja:
        zona_bandeja()
    with sectores:
        zona_sectores()
    with carga:
        zona_carga()
    with conectores:
        zona_conectores()


main()
