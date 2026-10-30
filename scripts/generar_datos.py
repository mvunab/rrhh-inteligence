#!/usr/bin/env python
"""Genera los datos sinteticos del caso (trabajadores, contratos y liquidaciones).

Uso (desde la raiz del proyecto):  python scripts/generar_datos.py

Produce:
  data/trabajadores.json              datos estructurados del contrato
  data/liquidaciones.json             liquidaciones de 2026-08 y 2026-09
  data/documentos/contratos/*.md      un contrato por trabajador (texto para RAG)
  tests/fixtures/errores_sembrados.json   la "respuesta correcta" para tests y para el docente

Los errores se siembran SOLO en la liquidacion de septiembre 2026:
  W001 Camila   -> se desconto AFP ProVida en vez de AFP Habitat (cotizacion distinta a su contrato)
  W003 Valentina-> AFP y salud calculadas sobre el total, sin aplicar el tope imponible
  W004 Diego    -> se desconto seguro de cesantia a un contrato a plazo fijo
  W002 Tomas    -> liquidacion correcta (caso de control)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.calculos import calcular_descuentos, cargar_parametros, gratificacion_art50  # noqa: E402

DATA = ROOT / "data"
EMPRESA = "Clínica Traumatología Cóndor SpA (ficticia)"

TRABAJADORES = [
    {
        "worker_id": "W001", "nombre": "Camila Rojas Pizarro", "cargo": "Kinesióloga",
        "tipo_contrato": "indefinido", "fecha_inicio": "2023-03-01", "fecha_termino": None,
        "afp": "Habitat", "salud": "Fonasa", "sueldo_base": 1_000_000,
        "colacion": 50_000, "movilizacion": 40_000, "asignacion_turno": 0,
        "bono": {"nombre": "Bono de productividad", "monto": 150_000, "meta_atenciones": 120},
        "jornada": "44 horas semanales, de lunes a viernes",
    },
    {
        "worker_id": "W002", "nombre": "Tomás Aguilera Soto", "cargo": "Técnico paramédico",
        "tipo_contrato": "indefinido", "fecha_inicio": "2022-08-15", "fecha_termino": None,
        "afp": "Modelo", "salud": "Fonasa", "sueldo_base": 700_000,
        "colacion": 45_000, "movilizacion": 40_000, "asignacion_turno": 80_000,
        "bono": None,
        "jornada": "44 horas semanales, en régimen de turnos rotativos",
    },
    {
        "worker_id": "W003", "nombre": "Valentina Cortés Vera", "cargo": "Médica traumatóloga",
        "tipo_contrato": "indefinido", "fecha_inicio": "2021-01-04", "fecha_termino": None,
        "afp": "Cuprum", "salud": "Fonasa", "sueldo_base": 4_500_000,
        "colacion": 60_000, "movilizacion": 0, "asignacion_turno": 0,
        "bono": None,
        "jornada": "44 horas semanales, de lunes a viernes",
    },
    {
        "worker_id": "W004", "nombre": "Diego Fuentes Lagos", "cargo": "Ejecutivo de admisión",
        "tipo_contrato": "plazo_fijo", "fecha_inicio": "2026-07-01", "fecha_termino": "2026-12-31",
        "afp": "Uno", "salud": "Fonasa", "sueldo_base": 620_000,
        "colacion": 40_000, "movilizacion": 35_000, "asignacion_turno": 0,
        "bono": None,
        "jornada": "44 horas semanales, de lunes a viernes",
    },
]

# Datos variables por periodo (atenciones registradas en el mes)
ATENCIONES = {("W001", "2026-08"): 128, ("W001", "2026-09"): 112}

# Errores sembrados (solo septiembre): parametros que se pasan a calcular_descuentos
ERRORES = {
    "W001": {"afp": "ProVida"},
    "W003": {"aplicar_tope": False},
    "W004": {"tipo_contrato": "indefinido"},
}

PERIODOS = ["2026-08", "2026-09"]


def _fmt(n: int) -> str:
    return f"${n:,}".replace(",", ".")


def construir_liquidacion(params: dict, t: dict, periodo: str) -> dict:
    atenciones = ATENCIONES.get((t["worker_id"], periodo))
    imponibles = [{"concepto": "Sueldo base", "monto": t["sueldo_base"]}]
    if t["asignacion_turno"]:
        imponibles.append({"concepto": "Asignación de turno", "monto": t["asignacion_turno"]})
    if t["bono"]:
        cumple = atenciones is not None and atenciones >= t["bono"]["meta_atenciones"]
        imponibles.append({"concepto": t["bono"]["nombre"],
                           "monto": t["bono"]["monto"] if cumple else 0})
    base_grat = sum(h["monto"] for h in imponibles)
    imponibles.append({"concepto": "Gratificación legal Art. 50",
                       "monto": gratificacion_art50(params, base_grat)})

    no_imponibles = []
    if t["colacion"]:
        no_imponibles.append({"concepto": "Asignación de colación", "monto": t["colacion"]})
    if t["movilizacion"]:
        no_imponibles.append({"concepto": "Asignación de movilización", "monto": t["movilizacion"]})

    imponible = sum(h["monto"] for h in imponibles)
    kwargs = ERRORES.get(t["worker_id"], {}) if periodo == "2026-09" else {}
    calc = calcular_descuentos(params, t, imponible, **kwargs)
    descuentos = [
        {k: v for k, v in linea.items()} for linea in calc["lineas"]
    ]
    total_haberes = imponible + sum(h["monto"] for h in no_imponibles)
    total_desc = sum(d["monto"] for d in descuentos)
    liq = {
        "worker_id": t["worker_id"],
        "periodo": periodo,
        "dias_trabajados": 30,
        "haberes_imponibles": imponibles,
        "haberes_no_imponibles": no_imponibles,
        "descuentos_legales": descuentos,
        "total_haberes": total_haberes,
        "total_descuentos": total_desc,
        "liquido_a_pagar": total_haberes - total_desc,
        "datos_variables": {},
    }
    if atenciones is not None:
        liq["datos_variables"]["atenciones_mes"] = atenciones
    return liq


def contrato_md(t: dict) -> str:
    wid = t["worker_id"]
    indef = t["tipo_contrato"] == "indefinido"
    duracion = (
        "El presente contrato es de duración indefinida."
        if indef else
        f"El presente contrato es a plazo fijo, desde el {t['fecha_inicio']} hasta el "
        f"{t['fecha_termino']}, fecha en la que expira por el solo cumplimiento del plazo. "
        "En los contratos a plazo fijo el seguro de cesantía es de cargo exclusivo del "
        "empleador (3% de la remuneración imponible): el trabajador no cotiza seguro de cesantía."
    )
    asign = []
    if t["colacion"]:
        asign.append(f"asignación de colación de {_fmt(t['colacion'])} mensuales")
    if t["movilizacion"]:
        asign.append(f"asignación de movilización de {_fmt(t['movilizacion'])} mensuales")
    asign_txt = (" y ".join(asign) + ", ambas no imponibles ni tributables.") if asign else \
        "El trabajador no recibe asignaciones de colación ni de movilización."

    if t["bono"]:
        b = t["bono"]
        bonos = (
            f"Las partes pactan un {b['nombre'].lower()} según el Anexo N° 1 de este contrato."
        )
        anexo = (
            "## ANEXO N° 1: Bono de productividad\n\n"
            f"Se pacta un bono de productividad mensual de {_fmt(b['monto'])} para {t['nombre']}, "
            f"condicionado al cumplimiento de la meta de {b['meta_atenciones']} atenciones "
            "kinesiológicas realizadas en el mes calendario, medidas con los registros clínicos "
            "cerrados del sistema de agenda. Si la meta no se alcanza dentro del mes, el bono de "
            "ese mes es de $0 (el bono no es proporcional). El bono es imponible y tributable."
        )
    elif t["asignacion_turno"]:
        bonos = "Las partes pactan una asignación de turno según el Anexo N° 1 de este contrato."
        anexo = (
            "## ANEXO N° 1: Asignación de turno\n\n"
            f"Se pacta una asignación de turno fija de {_fmt(t['asignacion_turno'])} mensuales por "
            "trabajar en régimen de turnos rotativos. No depende del cumplimiento de metas. "
            "La asignación de turno es imponible y tributable."
        )
    else:
        bonos = "No se pactan bonos variables en este contrato."
        anexo = (
            "## ANEXO N° 1: Sin anexos\n\n"
            "Este contrato no tiene anexos de remuneración variable. La remuneración del "
            "trabajador está compuesta únicamente por el sueldo base, la gratificación legal y "
            "las asignaciones indicadas en las cláusulas anteriores."
        )

    return f"""# Contrato de trabajo de {t['nombre']} ({wid})

> Documento ficticio con fines didácticos. Empleador: {EMPRESA}.

## CLÁUSULA PRIMERA: Partes y cargo

La {EMPRESA}, en adelante el empleador, contrata a {t['nombre']} (código {wid}) para desempeñar el cargo de {t['cargo']}, a partir del {t['fecha_inicio']}.

## CLÁUSULA SEGUNDA: Jornada de trabajo

La jornada de trabajo será de {t['jornada']}.

## CLÁUSULA TERCERA: Remuneración base

El empleador pagará al trabajador un sueldo base mensual de {_fmt(t['sueldo_base'])}, pagadero el último día hábil de cada mes, mediante transferencia bancaria.

## CLÁUSULA CUARTA: Gratificación legal

Las partes acuerdan pagar la gratificación legal por el sistema del artículo 50 del Código del Trabajo, en forma mensual: 25% de la remuneración mensual imponible (sin considerar la propia gratificación), con el tope de 4,75 ingresos mínimos mensuales al año, pagadero en doceavos.

## CLÁUSULA QUINTA: Asignaciones no imponibles

El trabajador recibirá una {asign_txt}

## CLÁUSULA SEXTA: Bonos y asignaciones variables

{bonos}

## CLÁUSULA SÉPTIMA: Previsión y salud

El trabajador declara estar afiliado a la AFP {t['afp']} y al sistema de salud {t['salud']}. El empleador descontará de la remuneración las cotizaciones correspondientes a la AFP {t['afp']} y a {t['salud']}, y las enterará en las instituciones respectivas.

## CLÁUSULA OCTAVA: Duración del contrato

{duracion}

## CLÁUSULA NOVENA: Descuentos

El empleador descontará de la remuneración las cotizaciones previsionales, de salud y de seguro de cesantía que correspondan, el impuesto único de segunda categoría y los demás descuentos que el trabajador autorice por escrito, conforme al Reglamento Interno.

## CLÁUSULA DÉCIMA: Reglamento Interno

El trabajador declara conocer el Reglamento Interno de Orden, Higiene y Seguridad y la Política de Bonos Variables vigentes, que forman parte de este contrato.

{anexo}
"""


def main() -> None:
    params = cargar_parametros()
    liquidaciones = [construir_liquidacion(params, t, p) for t in TRABAJADORES for p in PERIODOS]

    (DATA / "trabajadores.json").write_text(
        json.dumps(TRABAJADORES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DATA / "liquidaciones.json").write_text(
        json.dumps(liquidaciones, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (DATA / "documentos" / "contratos").mkdir(parents=True, exist_ok=True)
    for t in TRABAJADORES:
        (DATA / "documentos" / "contratos" / f"contrato_{t['worker_id']}.md").write_text(
            contrato_md(t), encoding="utf-8")

    fixtures = ROOT / "tests" / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / "errores_sembrados.json").write_text(json.dumps({
        "periodo": "2026-09",
        "W001": {"lineas_con_diferencia": ["afp"], "derivadas": ["impuesto_unico"],
                 "descripcion": "AFP ProVida en vez de Habitat"},
        "W002": {"lineas_con_diferencia": [], "derivadas": [], "descripcion": "Sin errores"},
        "W003": {"lineas_con_diferencia": ["afp", "salud"], "derivadas": ["impuesto_unico"],
                 "descripcion": "AFP y salud sin tope imponible"},
        "W004": {"lineas_con_diferencia": ["seguro_cesantia"], "derivadas": [],
                 "descripcion": "Seguro de cesantía en contrato a plazo fijo"},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {len(TRABAJADORES)} trabajadores, {len(liquidaciones)} liquidaciones")


if __name__ == "__main__":
    main()
