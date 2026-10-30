"""Almacén único de datos: trabajadores, contratos y anexos, documentos, liquidaciones y casos.

En el producto es PostgreSQL (DATABASE_URL). Sin DATABASE_URL se usa un SQLite local en data/.
La primera conexión crea las tablas y, si la base está vacía, la siembra con los archivos de data/:
esos archivos son la carga inicial, no una segunda fuente de verdad.
"""
from __future__ import annotations

import copy
import json
import os
import re
from calendar import monthrange
from datetime import date, datetime, timezone
from functools import lru_cache

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from .config import DATA_DIR, DOCS_DIR

TODOS_LOS_TRABAJADORES = "ALL"  # worker_id de los documentos compartidos
_JSON = JSON().with_variant(JSONB(), "postgresql")

meta = MetaData()

trabajadores = Table(
    "trabajadores", meta,
    Column("worker_id", String(16), primary_key=True),
    Column("ficha", _JSON, nullable=False),
)

documentos = Table(
    "documentos", meta,
    Column("nombre", String(200), primary_key=True),
    Column("worker_id", String(16), nullable=False, index=True),
    Column("doc_type", String(32), nullable=False),
    Column("contenido", Text, nullable=False),
    Column("vigente_desde", Date),
    Column("descripcion", Text, nullable=False, default=""),
    Column("cambios", _JSON, nullable=False, default=dict),
    Column("origen", String(16), nullable=False),
    Column("cargado", DateTime(timezone=True), nullable=False),
)

liquidaciones = Table(
    "liquidaciones", meta,
    Column("worker_id", String(16), primary_key=True),
    Column("periodo", String(7), primary_key=True),
    Column("datos", _JSON, nullable=False),
    Column("origen", String(16), nullable=False),
    Column("cargado", DateTime(timezone=True), nullable=False),
)

casos = Table(
    "casos", meta,
    Column("id", String(40), primary_key=True),
    Column("worker_id", String(16), nullable=False, index=True),
    Column("periodo", String(7), nullable=False),
    Column("estado", String(16), nullable=False),
    Column("datos", _JSON, nullable=False),
)

solicitudes = Table(
    "solicitudes", meta,
    Column("id", String(40), primary_key=True),
    Column("worker_id", String(16), nullable=False, index=True),
    Column("estado", String(16), nullable=False),
    Column("datos", _JSON, nullable=False),
)

borradores = Table(
    "borradores", meta,
    Column("id", String(40), primary_key=True),
    Column("worker_id", String(16), nullable=False, index=True),
    Column("periodo", String(7), nullable=False),
    Column("estado", String(16), nullable=False),
    Column("datos", _JSON, nullable=False),
)

# Campos de la ficha que un contrato o un anexo puede cambiar.
CAMPOS_FICHA = {
    "afp": str, "salud": str, "tipo_contrato": str, "fecha_termino": str, "jornada": str,
    "sueldo_base": int, "colacion": int, "movilizacion": int, "asignacion_turno": int,
    "bono_monto": int, "bono_meta_atenciones": int,
}
TIPOS_CONTRATO = ("indefinido", "plazo_fijo")


# ------------------------------------------------------------------ conexión
def url_base() -> str:
    return os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'liquidaciones.db'}"


@lru_cache(maxsize=None)
def _motor(url: str) -> Engine:
    motor = create_engine(url, pool_pre_ping=True)
    meta.create_all(motor)
    _sembrar_si_vacia(motor)
    return motor


def motor() -> Engine:
    return _motor(url_base())


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(valor) -> str | None:
    return valor.isoformat() if valor is not None else None


# ------------------------------------------------------------------ siembra desde data/
def metadata_de_nombre(nombre: str) -> tuple[str, str]:
    """(doc_type, worker_id) a partir del nombre del documento."""
    m = re.match(r"contrato_(W\d+)\.md$", nombre)
    if m:
        return "contrato", m.group(1)
    m = re.match(r"anexo_(W\d+)_", nombre)
    if m:
        return "anexo", m.group(1)
    tipo = {"reglamento_interno.md": "reglamento", "politica_bonos.md": "politica",
            "normativa_remuneraciones.md": "normativa"}.get(nombre, "otro")
    return tipo, TODOS_LOS_TRABAJADORES


def _sembrar_si_vacia(motor: Engine) -> None:
    with motor.begin() as cx:
        if cx.execute(select(trabajadores.c.worker_id).limit(1)).first() is not None:
            return
        fichas = json.loads((DATA_DIR / "trabajadores.json").read_text(encoding="utf-8"))
        cx.execute(insert(trabajadores), [{"worker_id": f["worker_id"], "ficha": f} for f in fichas])
        inicio = {f["worker_id"]: f.get("fecha_inicio") for f in fichas}
        ahora = _ahora()
        liqs = json.loads((DATA_DIR / "liquidaciones.json").read_text(encoding="utf-8"))
        cx.execute(insert(liquidaciones), [
            {"worker_id": l["worker_id"], "periodo": l["periodo"], "datos": l, "origen": "base", "cargado": ahora}
            for l in liqs
        ])
        filas = []
        for ruta in sorted(DOCS_DIR.rglob("*.md")):
            doc_type, worker_id = metadata_de_nombre(ruta.name)
            vigente = inicio.get(worker_id) if doc_type == "contrato" else None
            filas.append({
                "nombre": ruta.name, "worker_id": worker_id, "doc_type": doc_type,
                "contenido": ruta.read_text(encoding="utf-8"),
                "vigente_desde": date.fromisoformat(vigente) if vigente else None,
                "descripcion": "", "cambios": {}, "origen": "base", "cargado": ahora,
            })
        cx.execute(insert(documentos), filas)


# ------------------------------------------------------------------ trabajadores y ficha vigente
def completar_areas() -> int:
    """Completa el área en fichas ya guardadas que no la traen. No pisa el resto de la ficha."""
    semilla = {
        f["worker_id"]: f.get("area")
        for f in json.loads((DATA_DIR / "trabajadores.json").read_text(encoding="utf-8"))
        if f.get("area")
    }
    cambiadas = 0
    with motor().begin() as cx:
        for fila in cx.execute(select(trabajadores)).all():
            ficha = dict(fila.ficha)
            if ficha.get("area") or fila.worker_id not in semilla:
                continue
            ficha["area"] = semilla[fila.worker_id]
            cx.execute(update(trabajadores).where(trabajadores.c.worker_id == fila.worker_id).values(ficha=ficha))
            cambiadas += 1
    return cambiadas


def fichas_base() -> dict[str, dict]:
    with motor().connect() as cx:
        filas = cx.execute(select(trabajadores).order_by(trabajadores.c.worker_id)).all()
    return {f.worker_id: f.ficha for f in filas}


def _corte(periodo: str | None) -> date:
    """Último día del periodo AAAA-MM. Sin periodo, hoy."""
    if not periodo:
        return date.today()
    anio, mes = (int(p) for p in periodo.split("-"))
    return date(anio, mes, monthrange(anio, mes)[1])


def ficha_vigente(worker_id: str, periodo: str | None = None) -> dict | None:
    """La ficha base con los cambios del contrato y los anexos vigentes al cierre del periodo.

    Se aplican en orden de vigencia; a igual fecha el contrato va antes que el anexo.
    """
    base = fichas_base().get(worker_id)
    if base is None:
        return None
    ficha = copy.deepcopy(base)
    corte = _corte(periodo)
    with motor().connect() as cx:
        filas = cx.execute(
            select(documentos)
            .where(documentos.c.worker_id == worker_id)
            .where(documentos.c.doc_type.in_(("contrato", "anexo")))
        ).all()
    aplicables = sorted(
        (f for f in filas if f.vigente_desde is not None and f.vigente_desde <= corte),
        key=lambda f: (f.vigente_desde, f.doc_type == "anexo", f.cargado, f.nombre),
    )
    versiones = []
    for fila in aplicables:
        _aplicar(ficha, fila.cambios or {})
        versiones.append({"documento": fila.nombre, "vigente_desde": _iso(fila.vigente_desde),
                          "cambios": fila.cambios or {}})
    ficha["versiones"] = versiones
    return ficha


def _aplicar(ficha: dict, cambios: dict) -> None:
    for campo, valor in cambios.items():
        if campo in ("bono_monto", "bono_meta_atenciones"):
            bono = dict(ficha.get("bono") or {"nombre": "Bono de productividad", "monto": 0, "meta_atenciones": 0})
            bono["monto" if campo == "bono_monto" else "meta_atenciones"] = valor
            ficha["bono"] = bono
        else:
            ficha[campo] = valor


def validar_cambios(cambios: dict | None) -> dict:
    """Deja solo los campos conocidos con valor. Los vacíos no cambian nada."""
    limpios: dict = {}
    for campo, valor in (cambios or {}).items():
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            continue
        tipo = CAMPOS_FICHA.get(campo)
        if tipo is None:
            raise ValueError(f"El campo {campo} no se puede cambiar con un contrato o anexo.")
        if tipo is int:
            try:
                numero = int(str(valor).replace(".", "").replace("$", "").strip())
            except ValueError as e:
                raise ValueError(f"{campo} debe ser un monto en pesos.") from e
            if numero < 0:
                raise ValueError(f"{campo} no puede ser negativo.")
            limpios[campo] = numero
        else:
            limpios[campo] = str(valor).strip()
    if "tipo_contrato" in limpios and limpios["tipo_contrato"] not in TIPOS_CONTRATO:
        raise ValueError("El tipo de contrato debe ser indefinido o plazo_fijo.")
    if "fecha_termino" in limpios:
        try:
            date.fromisoformat(limpios["fecha_termino"])
        except ValueError as e:
            raise ValueError("La fecha de término debe ser AAAA-MM-DD.") from e
    return limpios


# ------------------------------------------------------------------ documentos (corpus del RAG)
def corpus() -> list[dict]:
    with motor().connect() as cx:
        filas = cx.execute(select(documentos).order_by(documentos.c.nombre)).all()
    return [{"nombre": f.nombre, "worker_id": f.worker_id, "doc_type": f.doc_type, "contenido": f.contenido}
            for f in filas]


def guardar_documento(nombre: str, worker_id: str, doc_type: str, contenido: str, *,
                      vigente_desde: date | None, descripcion: str = "", cambios: dict | None = None) -> None:
    with motor().begin() as cx:
        cx.execute(delete(documentos).where(documentos.c.nombre == nombre))
        cx.execute(insert(documentos).values(
            nombre=nombre, worker_id=worker_id, doc_type=doc_type, contenido=contenido,
            vigente_desde=vigente_desde, descripcion=descripcion, cambios=cambios or {},
            origen="cargado", cargado=_ahora(),
        ))


def existe_documento(nombre: str) -> bool:
    with motor().connect() as cx:
        return cx.execute(select(documentos.c.nombre).where(documentos.c.nombre == nombre)).first() is not None


def documentos_de_contrato(worker_id: str) -> list[dict]:
    with motor().connect() as cx:
        filas = cx.execute(
            select(documentos)
            .where(documentos.c.worker_id == worker_id)
            .where(documentos.c.doc_type.in_(("contrato", "anexo")))
        ).all()
    salida = [{
        "documento": f.nombre, "tipo": f.doc_type, "origen": f.origen,
        "vigente_desde": _iso(f.vigente_desde), "descripcion": f.descripcion,
        "cambios": f.cambios or {}, "cargado": _iso(f.cargado),
    } for f in filas]
    return sorted(salida, key=lambda d: (d["vigente_desde"] or "", d["tipo"] == "anexo", d["documento"]))


# ------------------------------------------------------------------ liquidaciones
def listar_liquidaciones(worker_id: str | None = None) -> list[dict]:
    consulta = select(liquidaciones).order_by(liquidaciones.c.worker_id, liquidaciones.c.periodo)
    if worker_id is not None:
        consulta = consulta.where(liquidaciones.c.worker_id == worker_id)
    with motor().connect() as cx:
        return [f.datos for f in cx.execute(consulta).all()]


def resumen_liquidaciones() -> list[dict]:
    with motor().connect() as cx:
        filas = cx.execute(select(liquidaciones).order_by(liquidaciones.c.periodo, liquidaciones.c.worker_id)).all()
    return [{"worker_id": f.worker_id, "periodo": f.periodo, "origen": f.origen, "cargado": _iso(f.cargado),
             "liquido_a_pagar": f.datos.get("liquido_a_pagar")} for f in filas]


def guardar_liquidaciones(nuevas: list[dict], origen: str) -> None:
    ahora = _ahora()
    with motor().begin() as cx:
        for liq in nuevas:
            cx.execute(delete(liquidaciones).where(liquidaciones.c.worker_id == liq["worker_id"])
                       .where(liquidaciones.c.periodo == liq["periodo"]))
            cx.execute(insert(liquidaciones).values(
                worker_id=liq["worker_id"], periodo=liq["periodo"], datos=liq, origen=origen, cargado=ahora))


# ------------------------------------------------------------------ casos de RR.HH.
def listar_casos() -> list[dict]:
    with motor().connect() as cx:
        return [f.datos for f in cx.execute(select(casos)).all()]


def obtener_caso(caso_id: str) -> dict | None:
    with motor().connect() as cx:
        fila = cx.execute(select(casos).where(casos.c.id == caso_id)).first()
    return fila.datos if fila else None


def guardar_caso(caso: dict) -> dict:
    with motor().begin() as cx:
        cx.execute(delete(casos).where(casos.c.id == caso["id"]))
        cx.execute(insert(casos).values(id=caso["id"], worker_id=caso["worker_id"], periodo=caso["periodo"],
                                        estado=caso["estado"], datos=caso))
    return caso


# ------------------------------------------------------------------ solicitudes al analista
def listar_solicitudes(worker_id: str | None = None) -> list[dict]:
    consulta = select(solicitudes)
    if worker_id is not None:
        consulta = consulta.where(solicitudes.c.worker_id == worker_id)
    with motor().connect() as cx:
        return [f.datos for f in cx.execute(consulta).all()]


def obtener_solicitud(solicitud_id: str) -> dict | None:
    with motor().connect() as cx:
        fila = cx.execute(select(solicitudes).where(solicitudes.c.id == solicitud_id)).first()
    return fila.datos if fila else None


def guardar_solicitud(solicitud: dict) -> dict:
    with motor().begin() as cx:
        cx.execute(delete(solicitudes).where(solicitudes.c.id == solicitud["id"]))
        cx.execute(insert(solicitudes).values(
            id=solicitud["id"], worker_id=solicitud["worker_id"], estado=solicitud["estado"], datos=solicitud))
    return solicitud


# ------------------------------------------------------------------ borradores de liquidación corregida
def listar_borradores() -> list[dict]:
    with motor().connect() as cx:
        return [f.datos for f in cx.execute(select(borradores).order_by(borradores.c.periodo,
                                                                         borradores.c.worker_id)).all()]


def obtener_borrador(borrador_id: str) -> dict | None:
    with motor().connect() as cx:
        fila = cx.execute(select(borradores).where(borradores.c.id == borrador_id)).first()
    return fila.datos if fila else None


def guardar_borrador(borrador: dict) -> dict:
    with motor().begin() as cx:
        cx.execute(delete(borradores).where(borradores.c.id == borrador["id"]))
        cx.execute(insert(borradores).values(
            id=borrador["id"], worker_id=borrador["worker_id"], periodo=borrador["periodo"],
            estado=borrador["estado"], datos=borrador))
    return borrador
