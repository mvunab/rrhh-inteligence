"""Liquidaciones de septiembre 2026 para probar la bandeja, en Excel y en PDF."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from fuentes.excel import COLUMNAS
from fuentes.liquidacion_pdf import lineas_liquidacion
from fuentes.pdf import pdf_de_paginas
from fuentes.protocolo import ErrorCarga

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"

# Los mismos montos que data/liquidaciones.json. W002 cuadra; los otros tres abren caso.
_FILAS = [
    {
        "worker_id": "W001", "nombre": "Camila Rojas", "periodo": "2026-09", "dias_trabajados": 30,
        "sueldo_base": 1000000, "bono_productividad": 0, "gratificacion": 219115, "asignacion_turno": 0,
        "colacion": 50000, "movilizacion": 40000,
        "afp_concepto": "AFP ProVida", "afp_institucion": "ProVida",
        "afp_base": 1219115, "afp_tasa": 0.1145, "afp_monto": 139589,
        "salud_base": 1219115, "salud_tasa": 0.07, "salud_monto": 85338,
        "cesantia_base": 1219115, "cesantia_tasa": 0.006, "cesantia_monto": 7315,
        "impuesto_base": 986873, "impuesto_monto": 513, "atenciones_mes": 112,
        "nota": "AFP ProVida y bono en cero. Abre W001-2026-09.",
    },
    {
        "worker_id": "W002", "nombre": "Tomas Aguilera", "periodo": "2026-09", "dias_trabajados": 30,
        "sueldo_base": 700000, "bono_productividad": 0, "gratificacion": 195000, "asignacion_turno": 80000,
        "colacion": 45000, "movilizacion": 40000,
        "afp_concepto": "AFP Modelo", "afp_institucion": "Modelo",
        "afp_base": 975000, "afp_tasa": 0.1058, "afp_monto": 103155,
        "salud_base": 975000, "salud_tasa": 0.07, "salud_monto": 68250,
        "cesantia_base": 975000, "cesantia_tasa": 0.006, "cesantia_monto": 5850,
        "impuesto_base": 797745, "impuesto_monto": 0, "atenciones_mes": 0,
        "nota": "Cuadra con el contrato.",
    },
    {
        "worker_id": "W003", "nombre": "Valentina Cortes", "periodo": "2026-09", "dias_trabajados": 30,
        "sueldo_base": 4500000, "bono_productividad": 0, "gratificacion": 219115, "asignacion_turno": 0,
        "colacion": 60000, "movilizacion": 0,
        "afp_concepto": "AFP Cuprum", "afp_institucion": "Cuprum",
        "afp_base": 4719115, "afp_tasa": 0.1144, "afp_monto": 539867,
        "salud_base": 4719115, "salud_tasa": 0.07, "salud_monto": 330338,
        "cesantia_base": 4719115, "cesantia_tasa": 0.006, "cesantia_monto": 28315,
        "impuesto_base": 3820595, "impuesto_monto": 191822, "atenciones_mes": 0,
        "nota": "AFP y salud sin tope imponible. Abre W003-2026-09.",
    },
    {
        "worker_id": "W004", "nombre": "Diego Fuentes", "periodo": "2026-09", "dias_trabajados": 30,
        "sueldo_base": 620000, "bono_productividad": 0, "gratificacion": 155000, "asignacion_turno": 0,
        "colacion": 40000, "movilizacion": 35000,
        "afp_concepto": "AFP Uno", "afp_institucion": "Uno",
        "afp_base": 775000, "afp_tasa": 0.1046, "afp_monto": 81065,
        "salud_base": 775000, "salud_tasa": 0.07, "salud_monto": 54250,
        "cesantia_base": 775000, "cesantia_tasa": 0.006, "cesantia_monto": 4650,
        "impuesto_base": 635035, "impuesto_monto": 0, "atenciones_mes": 0,
        "nota": "Cesantía cobrada en contrato a plazo fijo. Abre W004-2026-09.",
    },
]


def listar_muestras() -> list[dict]:
    pack = "W001, W002, W003 y W004, septiembre 2026."
    muestras = [
        {
            "id": "septiembre.xlsx",
            "nombre": "Septiembre 2026 · Excel",
            "archivo": "septiembre_2026.xlsx",
            "media": XLSX,
            "detalle": pack,
        },
        {
            "id": "septiembre.pdf",
            "nombre": "Septiembre 2026 · PDF",
            "archivo": "septiembre_2026.pdf",
            "media": PDF,
            "detalle": pack + " Una página por trabajador.",
        },
    ]
    for fila in _FILAS:
        muestras.append({
            "id": f"{fila['worker_id']}.pdf",
            "nombre": f"{fila['nombre']} · PDF",
            "archivo": f"liquidacion_{fila['worker_id']}_2026-09.pdf",
            "media": PDF,
            "detalle": fila["nota"],
        })
    return muestras


def obtener_muestra(muestra_id: str) -> tuple[bytes, str, str]:
    catalogo = {m["id"]: m for m in listar_muestras()}
    meta = catalogo.get(muestra_id)
    if meta is None:
        raise ErrorCarga(f"No existe la muestra {muestra_id}.")
    if muestra_id == "septiembre.xlsx":
        return excel_septiembre(), meta["media"], meta["archivo"]
    if muestra_id == "septiembre.pdf":
        return pdf_septiembre(), meta["media"], meta["archivo"]
    worker = muestra_id.removesuffix(".pdf")
    return pdf_trabajador(worker), meta["media"], meta["archivo"]


def excel_septiembre() -> bytes:
    libro = Workbook()
    hoja = libro.active
    hoja.title = "liquidaciones"
    hoja.append(list(COLUMNAS))
    for fila in _FILAS:
        hoja.append([fila[columna] for columna in COLUMNAS])
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()


def pdf_septiembre() -> bytes:
    return pdf_de_paginas([lineas_liquidacion(fila, fila["nombre"]) for fila in _FILAS])


def pdf_trabajador(worker_id: str) -> bytes:
    fila = next((f for f in _FILAS if f["worker_id"] == worker_id), None)
    if fila is None:
        raise ErrorCarga(f"No hay muestra PDF para {worker_id}.")
    return pdf_de_paginas([lineas_liquidacion(fila, fila["nombre"])])
