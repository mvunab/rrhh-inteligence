"""Centro de control de Recursos Humanos.

Ejecutar:  streamlit run rrhh/streamlit_app.py --server.port 8502
Habla solo con la API (API_BASE_URL). No abre el motor ni la base de datos.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import cliente  # noqa: E402
from cliente import ErrorApi, base_url  # noqa: E402

st.set_page_config(page_title="Centro de control · RR.HH.", page_icon="🗂️", layout="wide")


def clp(n: int | float | None) -> str:
    return "—" if n is None else f"${int(n):,}".replace(",", ".")


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
_SEV_FONDO = {
    "Crítico": "background-color: #7f1d1d; color: #fecaca; font-weight: 600",
    "Revisar": "background-color: #78350f; color: #fde68a; font-weight: 600",
    "Sin diferencias": "background-color: #14532d; color: #bbf7d0; font-weight: 600",
}
_DECISIONES = ("mantener", "corregir", "derivar")


def _titulo(texto: str) -> str:
    return texto[:1].upper() + texto[1:] if texto else texto


def _nombres() -> dict[str, str]:
    return {t["worker_id"]: t["nombre"] for t in (_llamar(cliente.trabajadores) or [])}


def _filas_seleccionadas(evento) -> list[int]:
    seleccion = getattr(evento, "selection", None)
    filas = getattr(seleccion, "rows", None)
    if filas is None and isinstance(seleccion, dict):
        filas = seleccion.get("rows", [])
    return list(filas or [])


def zona_casos() -> None:
    casos = _llamar(cliente.casos)
    if casos is None:
        return
    if not casos:
        st.info("No hay casos. Carga una liquidación con diferencias para abrir uno.")
        return
    nombres = _nombres()
    ids = [c["id"] for c in casos]
    if st.session_state.get("caso_id") not in ids:
        st.session_state["caso_id"] = ids[0]
    con_diferencias = sum(1 for c in casos if c.get("hay_diferencias", True))
    st.caption(f"{len(casos)} casos · {con_diferencias} con diferencias. Haz clic en una fila para abrir el caso.")

    lista, detalle = st.columns([1, 1.35], gap="large")
    with lista:
        tabla = pd.DataFrame([{
            "Trabajador": nombres.get(c["worker_id"], c["worker_id"]),
            "Liquidación": mes(c["periodo"]),
            "Estado": _titulo(c["estado"]),
            "Severidad": _SEV_ETIQUETA.get(c["severidad"], c["severidad"]),
            "Diferencia": clp(c["diferencia_total"]),
        } for c in casos])
        evento = st.dataframe(
            tabla.style.map(lambda valor: _SEV_FONDO.get(valor, ""), subset=["Severidad"]),
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            key="bandeja",
        )
        filas = _filas_seleccionadas(evento)
        if filas and filas[0] < len(ids):
            st.session_state["caso_id"] = ids[filas[0]]
    with detalle:
        zona_caso(nombres)


def zona_caso(nombres: dict[str, str] | None = None) -> None:
    caso_id = st.session_state.get("caso_id")
    if not caso_id:
        st.info("Elige un caso en la bandeja.")
        return
    caso = _llamar(cliente.caso, caso_id)
    if caso is None:
        return
    if nombres is None:
        nombres = _nombres()
    st.subheader(nombres.get(caso["worker_id"], caso["worker_id"]))
    st.caption(f"Liquidación de {mes(caso['periodo'])} · {caso['id']}")
    cifra, sev, estado = st.columns([1.2, 1, 1])
    cifra.metric("Diferencia", clp(caso["diferencia_total"]))
    sev.badge(_SEV_ETIQUETA.get(caso["severidad"], caso["severidad"]),
              color=_SEV_COLOR.get(caso["severidad"], "gray"))
    estado.badge(_titulo(caso["estado"]), color="blue" if caso["estado"] != "pendiente" else "gray")
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


_ORIGEN = {"base": "Sistema", "migrado": "Sistema", "excel": "Excel", "pdf": "PDF"}


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


def main() -> None:
    st.title("Centro de control de RR.HH.")
    st.caption(f"Carga y decisiones pasan por la API en {base_url()}.")
    casos, carga, conectores = st.tabs(["Casos", "Cargar", "Conectores"])
    with casos:
        zona_casos()
    with carga:
        zona_carga()
    with conectores:
        zona_conectores()


main()
