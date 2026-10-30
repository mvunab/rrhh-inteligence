"""Orquesta una carga: valida, guarda en el almacén y abre o recalcula casos."""
from __future__ import annotations

from fuentes.contratos import guardar_anexo, guardar_contrato
from fuentes.excel import leer_liquidaciones
from fuentes.liquidacion_pdf import leer_liquidaciones_pdf
from fuentes.protocolo import ErrorCarga
from harness import almacen
from harness.config import Settings
from harness.datos import obtener_trabajador
from harness.runtime import ejecutar

from .bandeja import guardar_informe, obtener_caso, recalcular_trabajador, sincronizar_casos


def procesar_excel(contenido: bytes) -> str:
    return _guardar(leer_liquidaciones(contenido), "excel")


def procesar_pdf_liquidacion(contenido: bytes) -> str:
    return _guardar(leer_liquidaciones_pdf(contenido), "pdf")


def _guardar(liquidaciones: list[dict], origen: str) -> str:
    for liq in liquidaciones:
        if obtener_trabajador(liq["worker_id"]) is None:
            raise ErrorCarga(f"No existe el trabajador {liq['worker_id']} en los datos de la clínica.")
    almacen.guardar_liquidaciones(liquidaciones, origen)
    casos = sincronizar_casos(liquidaciones)
    periodos = ", ".join(sorted({liq["periodo"] for liq in liquidaciones}))
    base = f"Se guardaron {len(liquidaciones)} liquidación(es) del periodo {periodos}."
    if casos:
        return f"{base} Casos con diferencias: {', '.join(casos)}."
    return f"{base} Ninguna tiene diferencias que revisar."


def procesar_contrato(contenido: bytes, worker_id: str, vigente_desde: str | None = None,
                      cambios: dict | None = None) -> str:
    nombre = guardar_contrato(contenido, worker_id, vigente_desde, cambios)
    return _tras_documento(worker_id.strip(), nombre, "Contrato vigente")


def procesar_anexo(contenido: bytes, worker_id: str, vigente_desde: str | None = None,
                   descripcion: str = "", cambios: dict | None = None) -> str:
    nombre = guardar_anexo(contenido, worker_id, vigente_desde, descripcion, cambios)
    return _tras_documento(worker_id.strip(), nombre, "Anexo")


def _tras_documento(worker_id: str, nombre: str, etiqueta: str) -> str:
    doc = next(d for d in almacen.documentos_de_contrato(worker_id) if d["documento"] == nombre)
    texto = f"{etiqueta} de {worker_id} guardado como {nombre}, vigente desde {doc['vigente_desde']}."
    if not doc["cambios"]:
        return texto + " No cambia campos de la ficha."
    cambios = ", ".join(f"{k} = {v}" for k, v in doc["cambios"].items())
    revisados = recalcular_trabajador(worker_id, doc["vigente_desde"])
    texto += f" Cambia {cambios}."
    if revisados:
        texto += f" Se recalcularon: {', '.join(revisados)}."
    return texto


def explicar_caso(caso_id: str) -> dict:
    """Pide el informe al agente y lo guarda. La decisión de RR.HH. no depende de esto."""
    caso = obtener_caso(caso_id)
    if caso is None:
        raise ValueError(f"No existe el caso {caso_id}.")
    pregunta = f"Revisa la liquidación de {caso['periodo']} y explica las diferencias."
    try:
        res = ejecutar(caso["worker_id"], pregunta, Settings())
        informe = res.informe.model_dump() if res.ok else {"error": "; ".join(res.errores) or "Sin informe."}
    except Exception as e:  # noqa: BLE001 - el caso sigue decidible si el modelo falla
        informe = {"error": f"{type(e).__name__}: {e}"}
    return guardar_informe(caso_id, informe)
