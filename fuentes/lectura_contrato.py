"""Lectura digital de contrato/anexo: el LLM propone campos de ficha; el analista confirma."""
from __future__ import annotations

import copy
import json
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from harness import almacen, datos
from harness.calculos import calcular_descuentos, cargar_parametros
from harness.config import Settings
from harness.llm_factory import crear_llm
from harness.schemas import extraer_json

from .contratos import _fecha, _validar_trabajador
from .pdf import extraer_texto
from .protocolo import ErrorCarga

Kind = Literal["contrato", "anexo"]

AFP_CONOCIDAS = ("Uno", "Modelo", "PlanVital", "Habitat", "Capital", "Cuprum", "ProVida")


class PropuestaCampo(BaseModel):
    valor: str | int | None = None
    evidencia: str = ""
    confianza: Literal["alta", "media", "baja"] = "media"


class LecturaContrato(BaseModel):
    resumen: str = ""
    afp: PropuestaCampo | None = None
    salud: PropuestaCampo | None = None
    tipo_contrato: PropuestaCampo | None = None
    fecha_termino: PropuestaCampo | None = None
    jornada: PropuestaCampo | None = None
    sueldo_base: PropuestaCampo | None = None
    colacion: PropuestaCampo | None = None
    movilizacion: PropuestaCampo | None = None
    asignacion_turno: PropuestaCampo | None = None
    bono_monto: PropuestaCampo | None = None
    bono_meta_atenciones: PropuestaCampo | None = None
    campos_no_mapeados: list[str] = Field(default_factory=list)


_CAMPOS = tuple(almacen.CAMPOS_FICHA.keys())

_SYSTEM = """Eres un analista de RR.HH. chileno. Lees el texto de un contrato o anexo
y propones SOLO los campos estructurados de la ficha laboral que el documento menciona
de forma explícita. Respondes únicamente con un objeto JSON válido (sin markdown).

Campos permitidos (omite los que no aparecen en el texto):
- afp: una de Uno, Modelo, PlanVital, Habitat, Capital, Cuprum, ProVida
- salud: texto corto (Fonasa, Isapre …)
- tipo_contrato: "indefinido" o "plazo_fijo"
- fecha_termino: AAAA-MM-DD si es plazo fijo
- jornada: texto breve (ej. "44 horas semanales")
- sueldo_base, colacion, movilizacion, asignacion_turno, bono_monto, bono_meta_atenciones: enteros en pesos (sin puntos ni $)

Para cada campo incluido usa: {"valor": ..., "evidencia": "cita corta del texto", "confianza": "alta"|"media"|"baja"}.
Incluye "resumen" (2-3 frases) y "campos_no_mapeados" (lista de menciones relevantes que no caben en esos campos).
No inventes montos ni AFP. Si no estás seguro, usa confianza "baja" o omite el campo.
"""


def proponer_desde_pdf(
    contenido: bytes,
    worker_id: str,
    kind: Kind,
    vigente_desde: str | None = None,
    descripcion: str = "",
) -> dict:
    """Extrae texto, propone campos con LLM/mock y arma preview. No persiste nada."""
    worker_id = _validar_trabajador(worker_id)
    texto = extraer_texto(contenido)
    if not texto.strip():
        raise ErrorCarga("El PDF no tiene texto seleccionable.")
    vigencia = _fecha(vigente_desde).isoformat()
    ficha_actual = datos.obtener_trabajador(worker_id)
    if ficha_actual is None:
        raise ErrorCarga(f"No existe el trabajador {worker_id}.")

    lectura = leer_texto(texto, kind, ficha_actual)
    cambios = cambios_desde_lectura(lectura)
    ficha_propuesta = _aplicar_preview(ficha_actual, cambios)
    return {
        "kind": kind,
        "worker_id": worker_id,
        "vigente_desde": vigencia,
        "descripcion": descripcion.strip(),
        "texto": texto.strip(),
        "propuesta": lectura.model_dump(),
        "cambios_sugeridos": cambios,
        "ficha_actual": _vista_ficha(ficha_actual),
        "ficha_propuesta": _vista_ficha(ficha_propuesta),
        "preview_descuentos": _preview_descuentos(ficha_actual, ficha_propuesta),
    }


def leer_texto(texto: str, kind: Kind, ficha_actual: dict | None = None) -> LecturaContrato:
    settings = Settings()
    if settings.llm_provider == "mock":
        return _mock_lectura(texto, kind)
    return _llm_lectura(texto, kind, ficha_actual or {}, settings)


def cambios_desde_lectura(lectura: LecturaContrato) -> dict:
    crudos: dict = {}
    for campo in _CAMPOS:
        prop = getattr(lectura, campo, None)
        if prop is None or prop.valor is None or prop.valor == "":
            continue
        crudos[campo] = prop.valor
    try:
        return almacen.validar_cambios(crudos)
    except ValueError as e:
        raise ErrorCarga(str(e)) from e


def parsear_lectura(texto: str) -> LecturaContrato:
    try:
        return LecturaContrato.model_validate_json(extraer_json(texto))
    except (ValidationError, ValueError, json.JSONDecodeError) as e:
        raise ErrorCarga(f"La lectura del modelo no es válida: {e}") from e


def _llm_lectura(texto: str, kind: Kind, ficha: dict, settings: Settings) -> LecturaContrato:
    llm = crear_llm(settings)
    ficha_resumen = {
        k: ficha.get(k) for k in ("afp", "salud", "tipo_contrato", "sueldo_base", "jornada")
    }
    bono = ficha.get("bono") or {}
    ficha_resumen["bono_monto"] = bono.get("monto")
    ficha_resumen["bono_meta_atenciones"] = bono.get("meta_atenciones")
    humano = (
        f"Tipo de documento: {kind}\n"
        f"Ficha actual del trabajador (referencia; solo propone cambios si el texto los dice):\n"
        f"{json.dumps(ficha_resumen, ensure_ascii=False)}\n\n"
        f"Texto del documento:\n{texto[:12000]}"
    )
    try:
        resp = llm.invoke([SystemMessage(content=_SYSTEM), HumanMessage(content=humano)])
        contenido = resp.content if isinstance(resp.content, str) else str(resp.content)
        return parsear_lectura(contenido)
    except ErrorCarga:
        raise
    except Exception as e:  # noqa: BLE001
        raise ErrorCarga(f"No se pudo leer el documento con el modelo: {e}") from e


def _mock_lectura(texto: str, kind: Kind) -> LecturaContrato:
    """Heurística determinista para tests y demos sin LLM."""
    campos: dict[str, PropuestaCampo] = {}
    no_mapeados: list[str] = []

    def _peso(patron: str) -> tuple[int, str] | None:
        m = re.search(patron, texto, re.I)
        if not m:
            return None
        bruto = m.group(1)
        try:
            return int(bruto.replace(".", "").replace(",", "")), m.group(0)[:120]
        except ValueError:
            return None

    sueldo = _peso(r"sueldo\s+base[^$]{0,40}\$\s*([\d.]+)")
    if sueldo:
        campos["sueldo_base"] = PropuestaCampo(valor=sueldo[0], evidencia=sueldo[1], confianza="alta")

    cola = _peso(r"colaci[oó]n[^$]{0,40}\$\s*([\d.]+)")
    if cola:
        campos["colacion"] = PropuestaCampo(valor=cola[0], evidencia=cola[1], confianza="alta")

    mov = _peso(r"movilizaci[oó]n[^$]{0,40}\$\s*([\d.]+)")
    if mov:
        campos["movilizacion"] = PropuestaCampo(valor=mov[0], evidencia=mov[1], confianza="alta")

    turno = _peso(r"asignaci[oó]n\s+de\s+turno[^$]{0,40}\$\s*([\d.]+)")
    if turno:
        campos["asignacion_turno"] = PropuestaCampo(valor=turno[0], evidencia=turno[1], confianza="alta")

    bono = _peso(r"bono\s+de\s+productividad[^$]{0,60}\$\s*([\d.]+)")
    if bono:
        campos["bono_monto"] = PropuestaCampo(valor=bono[0], evidencia=bono[1], confianza="alta")

    meta = re.search(r"meta\s+de\s+(\d+)\s+atenciones", texto, re.I)
    if meta:
        campos["bono_meta_atenciones"] = PropuestaCampo(
            valor=int(meta.group(1)), evidencia=meta.group(0), confianza="alta",
        )

    for nombre in AFP_CONOCIDAS:
        m = re.search(rf"AFP\s+{re.escape(nombre)}\b", texto, re.I)
        if m:
            campos["afp"] = PropuestaCampo(valor=nombre, evidencia=m.group(0), confianza="alta")
            break

    salud = re.search(r"(Fonasa|Isapre\s+\w+)", texto, re.I)
    if salud:
        campos["salud"] = PropuestaCampo(
            valor=salud.group(1).strip().title() if salud.group(1).lower() == "fonasa" else salud.group(1).strip(),
            evidencia=salud.group(0),
            confianza="alta",
        )

    if re.search(r"duraci[oó]n\s+indefinida|contrato\s+indefinido|de\s+duraci[oó]n\s+indefinida", texto, re.I):
        m = re.search(r".{0,40}(indefinid\w+).{0,40}", texto, re.I)
        campos["tipo_contrato"] = PropuestaCampo(
            valor="indefinido",
            evidencia=(m.group(0).strip() if m else "duración indefinida"),
            confianza="alta",
        )
    elif re.search(r"plazo\s+fijo", texto, re.I):
        m = re.search(r".{0,40}plazo\s+fijo.{0,40}", texto, re.I)
        campos["tipo_contrato"] = PropuestaCampo(
            valor="plazo_fijo",
            evidencia=(m.group(0).strip() if m else "plazo fijo"),
            confianza="alta",
        )

    jornada = re.search(r"(\d+\s+horas\s+semanales[^.\\n]*)", texto, re.I)
    if jornada:
        campos["jornada"] = PropuestaCampo(valor=jornada.group(1).strip(), evidencia=jornada.group(0), confianza="media")

    if kind == "anexo" and "afp" not in campos and "sueldo_base" not in campos:
        no_mapeados.append("Anexo sin cambios tipados detectados en el texto.")

    etiq = "contrato" if kind == "contrato" else "anexo"
    resumen = (
        f"Lectura mock del {etiq}: "
        + (", ".join(f"{k}={c.valor}" for k, c in campos.items()) or "sin campos tipados")
        + "."
    )
    return LecturaContrato(resumen=resumen, campos_no_mapeados=no_mapeados, **campos)


def _aplicar_preview(ficha: dict, cambios: dict) -> dict:
    out = copy.deepcopy(ficha)
    almacen._aplicar(out, cambios)  # noqa: SLF001 — misma lógica que ficha_vigente
    return out


def _vista_ficha(ficha: dict) -> dict:
    bono = ficha.get("bono") or {}
    return {
        "afp": ficha.get("afp"),
        "salud": ficha.get("salud"),
        "tipo_contrato": ficha.get("tipo_contrato"),
        "fecha_termino": ficha.get("fecha_termino"),
        "jornada": ficha.get("jornada"),
        "sueldo_base": ficha.get("sueldo_base"),
        "colacion": ficha.get("colacion"),
        "movilizacion": ficha.get("movilizacion"),
        "asignacion_turno": ficha.get("asignacion_turno"),
        "bono_monto": bono.get("monto"),
        "bono_meta_atenciones": bono.get("meta_atenciones"),
    }


def _imponible_estimado(ficha: dict) -> int:
    base = int(ficha.get("sueldo_base") or 0)
    bono = int((ficha.get("bono") or {}).get("monto") or 0)
    return base + bono


def _resumen_descuentos(ficha: dict) -> dict:
    params = cargar_parametros()
    imponible = _imponible_estimado(ficha)
    if imponible <= 0:
        return {"imponible": 0, "total": 0, "lineas": []}
    calc = calcular_descuentos(params, ficha, imponible)
    return {
        "imponible": calc["imponible"],
        "total": calc["total"],
        "lineas": [
            {"codigo": l["codigo"], "concepto": l["concepto"], "monto": l["monto"]}
            for l in calc["lineas"]
        ],
    }


def _preview_descuentos(actual: dict, propuesta: dict) -> dict:
    return {
        "actual": _resumen_descuentos(actual),
        "propuesta": _resumen_descuentos(propuesta),
    }
