"""Liquidaciones desde una planilla con columnas fijas."""
from __future__ import annotations

import re
from io import BytesIO

from openpyxl import Workbook, load_workbook

from harness.calculos import redondear

from .protocolo import ErrorCarga, ResultadoCarga

COLUMNAS = (
    "worker_id", "periodo", "dias_trabajados",
    "sueldo_base", "bono_productividad", "gratificacion", "asignacion_turno",
    "colacion", "movilizacion",
    "afp_concepto", "afp_institucion", "afp_base", "afp_tasa", "afp_monto",
    "salud_base", "salud_tasa", "salud_monto",
    "cesantia_base", "cesantia_tasa", "cesantia_monto",
    "impuesto_base", "impuesto_monto",
    "atenciones_mes",
)

_PESOS = (
    "sueldo_base", "bono_productividad", "gratificacion", "asignacion_turno",
    "colacion", "movilizacion",
    "afp_base", "afp_monto", "salud_base", "salud_monto",
    "cesantia_base", "cesantia_monto", "impuesto_base", "impuesto_monto",
)
_TASAS = ("afp_tasa", "salud_tasa", "cesantia_tasa")


def plantilla_bytes() -> bytes:
    """Planilla vacía con los encabezados, más una fila de ejemplo (Camila, septiembre)."""
    libro = Workbook()
    hoja = libro.active
    hoja.title = "liquidaciones"
    hoja.append(list(COLUMNAS))
    hoja.append([
        "W001", "2026-09", 30,
        1000000, 0, 219115, 0,
        50000, 40000,
        "AFP ProVida", "ProVida", 1219115, 0.1145, 139589,
        1219115, 0.07, 85338,
        1219115, 0.006, 7315,
        986873, 513,
        112,
    ])
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()


def liquidacion_desde_campos(datos: dict, origen: str) -> dict:
    """Misma liquidación que una fila de Excel. `origen` aparece en el mensaje de error."""
    return _fila_a_liquidacion(datos, origen)


def leer_liquidaciones(contenido: bytes) -> list[dict]:
    """Convierte la primera hoja en liquidaciones con la misma forma que data/liquidaciones.json."""
    try:
        libro = load_workbook(BytesIO(contenido), data_only=True)
    except Exception as e:  # noqa: BLE001 - openpyxl no distingue un xlsx corrupto
        raise ErrorCarga(f"No se pudo leer el Excel: {e}") from e
    hoja = libro.active
    filas = list(hoja.iter_rows(values_only=True))
    if not filas:
        raise ErrorCarga("El Excel está vacío.")
    encabezados = [str(c).strip() if c is not None else "" for c in filas[0]]
    faltan = [c for c in COLUMNAS if c not in encabezados]
    if faltan:
        raise ErrorCarga("Faltan columnas: " + ", ".join(faltan))
    idx = {nombre: encabezados.index(nombre) for nombre in COLUMNAS}
    liquidaciones = []
    vistas: set[tuple[str, str]] = set()
    for n, fila in enumerate(filas[1:], start=2):
        if fila is None or all(c is None or str(c).strip() == "" for c in fila):
            continue
        datos = {nombre: fila[pos] if pos < len(fila) else None for nombre, pos in idx.items()}
        liq = liquidacion_desde_campos(datos, f"Fila {n}")
        clave = (liq["worker_id"], liq["periodo"])
        if clave in vistas:
            raise ErrorCarga(f"La fila {n} repite {clave[0]} {clave[1]}.")
        vistas.add(clave)
        liquidaciones.append(liq)
    if not liquidaciones:
        raise ErrorCarga("El archivo no trae liquidaciones.")
    return liquidaciones


def _fila_a_liquidacion(datos: dict, fila: int) -> dict:
    worker = str(datos["worker_id"] or "").strip()
    if not re.fullmatch(r"W\d+", worker):
        raise ErrorCarga(f"{fila}: worker_id debe ser W seguido de números.")
    periodo = _periodo(datos["periodo"], fila)
    pesos = {k: _peso(datos[k], fila, k) for k in _PESOS}
    tasas = {k: _tasa(datos[k], fila, k) for k in _TASAS}
    dias = _entero(datos["dias_trabajados"], fila, "dias_trabajados")
    atenciones = datos["atenciones_mes"]
    imponibles = [{"concepto": "Sueldo base", "monto": pesos["sueldo_base"]}]
    if pesos["bono_productividad"]:
        imponibles.append({"concepto": "Bono de productividad", "monto": pesos["bono_productividad"]})
    elif datos["bono_productividad"] not in (None, ""):
        imponibles.append({"concepto": "Bono de productividad", "monto": 0})
    if pesos["asignacion_turno"]:
        imponibles.append({"concepto": "Asignación de turno", "monto": pesos["asignacion_turno"]})
    imponibles.append({"concepto": "Gratificación legal Art. 50", "monto": pesos["gratificacion"]})
    no_imponibles = []
    if datos["colacion"] not in (None, ""):
        no_imponibles.append({"concepto": "Asignación de colación", "monto": pesos["colacion"]})
    if datos["movilizacion"] not in (None, ""):
        no_imponibles.append({"concepto": "Asignación de movilización", "monto": pesos["movilizacion"]})
    descuentos = [
        {"codigo": "afp", "concepto": str(datos["afp_concepto"] or "").strip() or "AFP",
         "institucion": str(datos["afp_institucion"] or "").strip(),
         "base": pesos["afp_base"], "tasa": tasas["afp_tasa"], "monto": pesos["afp_monto"]},
        {"codigo": "salud", "concepto": "Salud (Fonasa 7%)", "base": pesos["salud_base"],
         "tasa": tasas["salud_tasa"], "monto": pesos["salud_monto"]},
        {"codigo": "seguro_cesantia", "concepto": "Seguro de cesantía", "base": pesos["cesantia_base"],
         "tasa": tasas["cesantia_tasa"], "monto": pesos["cesantia_monto"]},
        {"codigo": "impuesto_unico", "concepto": "Impuesto único 2ª categoría",
         "base": pesos["impuesto_base"], "tasa": None, "monto": pesos["impuesto_monto"]},
    ]
    total_haberes = sum(h["monto"] for h in imponibles) + sum(h["monto"] for h in no_imponibles)
    total_descuentos = sum(d["monto"] for d in descuentos)
    liq = {
        "worker_id": worker,
        "periodo": periodo,
        "dias_trabajados": dias,
        "haberes_imponibles": imponibles,
        "haberes_no_imponibles": no_imponibles,
        "descuentos_legales": descuentos,
        "total_haberes": total_haberes,
        "total_descuentos": total_descuentos,
        "liquido_a_pagar": total_haberes - total_descuentos,
    }
    if atenciones not in (None, ""):
        liq["datos_variables"] = {"atenciones_mes": _entero(atenciones, fila, "atenciones_mes")}
    return liq


def _periodo(valor, fila: int) -> str:
    if hasattr(valor, "strftime"):
        texto = valor.strftime("%Y-%m")
    else:
        texto = str(valor or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", texto):
        raise ErrorCarga(f"{fila}: periodo debe ser AAAA-MM.")
    return texto


def _peso(valor, fila: int, columna: str) -> int:
    if valor is None or valor == "":
        raise ErrorCarga(f"{fila}: falta {columna}.")
    try:
        return redondear(valor)
    except Exception as e:  # noqa: BLE001
        raise ErrorCarga(f"{fila}: {columna} no es un monto.") from e


def _entero(valor, fila: int, columna: str) -> int:
    if valor is None or valor == "":
        raise ErrorCarga(f"{fila}: falta {columna}.")
    try:
        return int(valor)
    except (TypeError, ValueError) as e:
        raise ErrorCarga(f"{fila}: {columna} no es un entero.") from e


def _tasa(valor, fila: int, columna: str) -> float:
    if valor is None or valor == "":
        raise ErrorCarga(f"{fila}: falta {columna}.")
    try:
        tasa = float(valor)
    except (TypeError, ValueError) as e:
        raise ErrorCarga(f"{fila}: {columna} no es una tasa.") from e
    if tasa > 1:
        tasa = tasa / 100
    if tasa < 0:
        raise ErrorCarga(f"{fila}: {columna} no puede ser negativa.")
    return tasa


class ExcelConector:
    nombre = "Excel"
    disponible = True
    detalle = "Liquidaciones en la plantilla .xlsx"

    def cargar(self, contenido: bytes, **opciones) -> ResultadoCarga:
        liquidaciones = leer_liquidaciones(contenido)
        return ResultadoCarga(
            origen=self.nombre,
            resumen=f"{len(liquidaciones)} liquidación(es)",
            liquidaciones=liquidaciones,
        )
