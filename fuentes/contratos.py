"""Contratos y anexos en PDF. El texto va al corpus del RAG y los campos que cambian, a la ficha."""
from __future__ import annotations

import re
from datetime import date

from harness import almacen, datos

from .pdf import extraer_texto
from .protocolo import ErrorCarga, ResultadoCarga


def markdown_contrato(worker_id: str, texto: str, vigente_desde: str | None = None) -> str:
    """Encabezados que el troceador de harness/ingest.py conserva."""
    vigencia = f"Vigente desde: {vigente_desde}\n\n" if vigente_desde else ""
    return f"# Contrato de trabajo ({worker_id})\n\n{vigencia}## Texto extraído del PDF\n\n{texto.strip()}\n"


def markdown_anexo(worker_id: str, texto: str, vigente_desde: str, descripcion: str) -> str:
    titulo = descripcion.strip() or "Anexo de contrato"
    return (
        f"# Anexo de contrato ({worker_id})\n\n"
        f"Vigente desde: {vigente_desde}\n\n"
        f"## Anexo vigente desde {vigente_desde}: {titulo}\n\n{texto.strip()}\n"
    )


def guardar_contrato(contenido: bytes, worker_id: str, vigente_desde: str | None = None,
                     cambios: dict | None = None) -> str:
    """Guarda el contrato como el vigente del trabajador. Reemplaza al anterior. Devuelve su nombre."""
    worker_id = _validar_trabajador(worker_id)
    texto = extraer_texto(contenido)
    vigencia = _fecha(vigente_desde)
    nombre = f"contrato_{worker_id}.md"
    almacen.guardar_documento(
        nombre, worker_id, "contrato", markdown_contrato(worker_id, texto, vigencia.isoformat()),
        vigente_desde=vigencia, cambios=_cambios(cambios),
    )
    return nombre


def guardar_anexo(contenido: bytes, worker_id: str, vigente_desde: str | None = None,
                  descripcion: str = "", cambios: dict | None = None) -> str:
    """Suma un anexo al contrato del trabajador. Los anexos no reemplazan al contrato ni entre sí."""
    worker_id = _validar_trabajador(worker_id)
    texto = extraer_texto(contenido)
    vigencia = _fecha(vigente_desde)
    nombre = f"anexo_{worker_id}_{vigencia.isoformat()}.md"
    n = 1
    while almacen.existe_documento(nombre):
        n += 1
        nombre = f"anexo_{worker_id}_{vigencia.isoformat()}_{n}.md"
    almacen.guardar_documento(
        nombre, worker_id, "anexo", markdown_anexo(worker_id, texto, vigencia.isoformat(), descripcion),
        vigente_desde=vigencia, descripcion=descripcion.strip(), cambios=_cambios(cambios),
    )
    return nombre


def contratos_vigentes() -> list[dict]:
    """Por trabajador: la ficha vigente hoy, el contrato y sus anexos con fecha y cambios."""
    filas = []
    for worker_id, ficha in datos.cargar_trabajadores().items():
        documentos = almacen.documentos_de_contrato(worker_id)
        contrato = next((d for d in documentos if d["tipo"] == "contrato"), None)
        filas.append({
            "worker_id": worker_id,
            "nombre": ficha["nombre"],
            "origen": contrato["origen"] if contrato else "base",
            "vigente_desde": contrato["vigente_desde"] if contrato else ficha.get("fecha_inicio"),
            "cargado": contrato["cargado"] if contrato and contrato["origen"] == "cargado" else None,
            "cambios": contrato["cambios"] if contrato else {},
            "anexos": [d for d in documentos if d["tipo"] == "anexo"],
            "ficha": {k: ficha.get(k) for k in (
                "afp", "salud", "tipo_contrato", "fecha_termino", "sueldo_base",
                "colacion", "movilizacion", "asignacion_turno", "bono")},
        })
    return filas


def _validar_trabajador(worker_id: str) -> str:
    worker_id = worker_id.strip()
    if not re.fullmatch(r"W\d+", worker_id):
        raise ErrorCarga("El trabajador debe ser W seguido de números.")
    if datos.obtener_trabajador(worker_id) is None:
        raise ErrorCarga(f"No existe el trabajador {worker_id} en los datos de la clínica.")
    return worker_id


def _fecha(valor: str | None) -> date:
    """Fecha ISO. Sin valor se usa hoy."""
    if not valor or not str(valor).strip():
        return date.today()
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError as e:
        raise ErrorCarga("La fecha de vigencia debe ser AAAA-MM-DD.") from e


def _cambios(cambios: dict | None) -> dict:
    try:
        return almacen.validar_cambios(cambios)
    except ValueError as e:
        raise ErrorCarga(str(e)) from e


class PdfConector:
    nombre = "PDF"
    disponible = True
    detalle = "Contrato o anexo en PDF con texto seleccionable"

    def cargar(self, contenido: bytes, **opciones) -> ResultadoCarga:
        worker_id = str(opciones["worker_id"])
        nombre = guardar_contrato(contenido, worker_id, opciones.get("vigente_desde"), opciones.get("cambios"))
        return ResultadoCarga(
            origen=self.nombre,
            resumen=f"Contrato de {worker_id} guardado",
            documento={"worker_id": worker_id, "documento": nombre},
        )
