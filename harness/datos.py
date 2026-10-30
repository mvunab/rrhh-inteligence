"""Acceso a los datos estructurados del caso (trabajadores y liquidaciones), desde el almacén."""
from __future__ import annotations

from . import almacen


def cargar_trabajadores() -> dict[str, dict]:
    """Fichas vigentes hoy, con los cambios de contrato y anexos ya aplicados."""
    return {wid: almacen.ficha_vigente(wid) for wid in almacen.fichas_base()}


def cargar_liquidaciones() -> list[dict]:
    return almacen.listar_liquidaciones()


def obtener_trabajador(worker_id: str, periodo: str | None = None) -> dict | None:
    """Ficha vigente al cierre del periodo (sin periodo, hoy)."""
    return almacen.ficha_vigente(worker_id, periodo)


def periodos_disponibles(worker_id: str) -> list[str]:
    return sorted(l["periodo"] for l in almacen.listar_liquidaciones(worker_id))


def obtener_liquidacion(worker_id: str, periodo: str | None = None) -> dict | None:
    """Liquidacion de UN trabajador. Si no se indica periodo, devuelve la mas reciente."""
    propias = almacen.listar_liquidaciones(worker_id)
    if not propias:
        return None
    periodo = periodo or max(l["periodo"] for l in propias)
    return next((l for l in propias if l["periodo"] == periodo), None)
