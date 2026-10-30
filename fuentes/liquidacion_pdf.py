"""Liquidación de sueldo en PDF con texto. Un bloque por trabajador."""
from __future__ import annotations

import re
import unicodedata

from fuentes.excel import COLUMNAS, liquidacion_desde_campos
from fuentes.pdf import extraer_texto
from fuentes.protocolo import ErrorCarga, ResultadoCarga

_ETIQUETAS = {
    "worker_id": "worker_id",
    "trabajador": "worker_id",
    "periodo": "periodo",
    "dias_trabajados": "dias_trabajados",
    "dias trabajados": "dias_trabajados",
    "sueldo_base": "sueldo_base",
    "sueldo base": "sueldo_base",
    "bono_productividad": "bono_productividad",
    "bono productividad": "bono_productividad",
    "bono de productividad": "bono_productividad",
    "gratificacion": "gratificacion",
    "asignacion_turno": "asignacion_turno",
    "asignacion turno": "asignacion_turno",
    "asignacion de turno": "asignacion_turno",
    "colacion": "colacion",
    "movilizacion": "movilizacion",
    "afp_concepto": "afp_concepto",
    "afp concepto": "afp_concepto",
    "afp_institucion": "afp_institucion",
    "afp institucion": "afp_institucion",
    "afp_base": "afp_base",
    "afp base": "afp_base",
    "afp_tasa": "afp_tasa",
    "afp tasa": "afp_tasa",
    "afp_monto": "afp_monto",
    "afp monto": "afp_monto",
    "salud_base": "salud_base",
    "salud base": "salud_base",
    "salud_tasa": "salud_tasa",
    "salud tasa": "salud_tasa",
    "salud_monto": "salud_monto",
    "salud monto": "salud_monto",
    "cesantia_base": "cesantia_base",
    "cesantia base": "cesantia_base",
    "cesantia_tasa": "cesantia_tasa",
    "cesantia tasa": "cesantia_tasa",
    "cesantia_monto": "cesantia_monto",
    "cesantia monto": "cesantia_monto",
    "impuesto_base": "impuesto_base",
    "impuesto base": "impuesto_base",
    "impuesto_monto": "impuesto_monto",
    "impuesto monto": "impuesto_monto",
    "atenciones_mes": "atenciones_mes",
    "atenciones mes": "atenciones_mes",
}
_TASAS = {"afp_tasa", "salud_tasa", "cesantia_tasa"}
_MILES = re.compile(r"\d{1,3}(\.\d{3})+")


def leer_liquidaciones_pdf(contenido: bytes) -> list[dict]:
    texto = _sin_acentos(extraer_texto(contenido))
    partes = re.split(r"(?im)^liquidacion de sueldo\s*$", texto)
    bloques = [parte.strip() for parte in partes if parte.strip()]
    if not bloques:
        raise ErrorCarga("El PDF no trae liquidaciones.")
    liquidaciones = []
    vistas: set[tuple[str, str]] = set()
    for n, bloque in enumerate(bloques, start=1):
        liq = liquidacion_desde_campos(_campos(bloque, n), f"PDF {n}")
        clave = (liq["worker_id"], liq["periodo"])
        if clave in vistas:
            raise ErrorCarga(f"El PDF repite {clave[0]} {clave[1]}.")
        vistas.add(clave)
        liquidaciones.append(liq)
    return liquidaciones


def lineas_liquidacion(fila: dict, nombre: str) -> list[str]:
    """Texto que leer_liquidaciones_pdf vuelve a convertir en una liquidación."""
    etiquetas = (
        ("Trabajador", "worker_id"), ("Periodo", "periodo"), ("Dias trabajados", "dias_trabajados"),
        ("Sueldo base", "sueldo_base"), ("Bono de productividad", "bono_productividad"),
        ("Gratificacion", "gratificacion"), ("Asignacion de turno", "asignacion_turno"),
        ("Colacion", "colacion"), ("Movilizacion", "movilizacion"),
        ("AFP concepto", "afp_concepto"), ("AFP institucion", "afp_institucion"),
        ("AFP base", "afp_base"), ("AFP tasa", "afp_tasa"), ("AFP monto", "afp_monto"),
        ("Salud base", "salud_base"), ("Salud tasa", "salud_tasa"), ("Salud monto", "salud_monto"),
        ("Cesantia base", "cesantia_base"), ("Cesantia tasa", "cesantia_tasa"),
        ("Cesantia monto", "cesantia_monto"),
        ("Impuesto base", "impuesto_base"), ("Impuesto monto", "impuesto_monto"),
        ("Atenciones mes", "atenciones_mes"),
    )
    lineas = ["LIQUIDACION DE SUELDO", f"Nombre: {nombre}"]
    lineas.extend(f"{etiqueta}: {fila[columna]}" for etiqueta, columna in etiquetas)
    return lineas


def _campos(bloque: str, numero: int) -> dict:
    datos: dict[str, str] = {}
    for linea in bloque.splitlines():
        coincidencia = re.match(r"\s*([^:]+):\s*(.*?)\s*$", linea)
        if not coincidencia:
            continue
        clave = _ETIQUETAS.get(_sin_acentos(coincidencia.group(1)).lower().strip())
        if clave:
            datos[clave] = _normalizar(clave, coincidencia.group(2))
    faltan = [columna for columna in COLUMNAS if columna not in datos or datos[columna] == ""]
    if faltan:
        raise ErrorCarga(f"PDF {numero}: faltan datos: " + ", ".join(faltan))
    return datos


def _normalizar(columna: str, valor: str) -> str:
    texto = valor.strip().replace("$", "").replace(" ", "")
    if columna in _TASAS:
        return texto.replace("%", "").replace(",", ".")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif _MILES.fullmatch(texto):
        texto = texto.replace(".", "")
    return texto


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


class LiquidacionPdfConector:
    nombre = "PDF liquidación"
    disponible = True
    detalle = "Liquidación en PDF con texto. Un bloque LIQUIDACION DE SUELDO por trabajador."

    def cargar(self, contenido: bytes, **opciones) -> ResultadoCarga:
        liquidaciones = leer_liquidaciones_pdf(contenido)
        return ResultadoCarga(
            origen=self.nombre,
            resumen=f"{len(liquidaciones)} liquidación(es) desde PDF",
            liquidaciones=liquidaciones,
        )
