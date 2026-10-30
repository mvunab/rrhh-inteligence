"""Calculo determinista de descuentos de remuneraciones (Chile, version didactica).

Regla de oro del caso: el LLM NO hace aritmetica. Todo numero que el agente
le muestre al trabajador sale de este modulo (via tools) y no del modelo.

Alcance deliberadamente acotado (ver docs/gaps_de_negocio.md): AFP, salud (Fonasa 7%),
seguro de cesantia, impuesto unico de segunda categoria y gratificacion Art. 50.
"""
from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


def redondear(x: Any) -> int:
    """Redondeo a peso entero, mitad hacia arriba (como una liquidacion)."""
    return int(_d(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cargar_parametros(path: Path | None = None) -> dict:
    path = path or (DATA_DIR / "parametros_2026.json")
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- parametros derivados
def tope_imponible_pesos(params: dict, tipo: str = "afp_salud") -> int:
    """Tope imponible en pesos = tope en UF x valor UF."""
    return redondear(_d(params["uf"]["valor"]) * _d(params["topes_uf"][tipo]))


def tope_gratificacion_mensual(params: dict) -> int:
    """Tope mensual de la gratificacion Art. 50 = 4,75 IMM / 12."""
    g = params["gratificacion"]
    return redondear(_d(g["tope_imm_anual"]) * _d(params["ingreso_minimo"]["valor"]) / 12)


def gratificacion_art50(params: dict, remuneracion_base: int) -> int:
    """25% de la remuneracion mensual (sin gratificacion), con tope mensual."""
    g = params["gratificacion"]
    bruta = _d(remuneracion_base) * _d(g["porcentaje"])
    tope = _d(g["tope_imm_anual"]) * _d(params["ingreso_minimo"]["valor"]) / 12
    return redondear(min(bruta, tope))


def tasa_afp(params: dict, afp: str) -> Decimal:
    comisiones = params["comisiones_afp"]
    if afp not in comisiones:
        raise ValueError(f"AFP desconocida: {afp!r}")
    return _d(params["cotizaciones"]["afp_obligatoria"]) + _d(comisiones[afp])


def tasa_seguro_cesantia(params: dict, tipo_contrato: str) -> Decimal:
    return _d(params["cotizaciones"]["seguro_cesantia_trabajador"][tipo_contrato])


def impuesto_unico(params: dict, base_tributable: int | Decimal) -> int:
    """Impuesto unico de segunda categoria: base x factor - rebaja (tabla SII)."""
    base = _d(base_tributable)
    if base <= 0:
        return 0
    for tramo in params["impuesto_unico"]["tramos"]:
        if tramo["hasta"] is None or base <= _d(tramo["hasta"]):
            monto = base * _d(tramo["factor"]) - _d(tramo["rebaja"])
            return max(redondear(monto), 0)
    return 0


# ---------------------------------------------------------------- calculo principal
def calcular_descuentos(
    params: dict,
    trabajador: dict,
    imponible: int,
    *,
    afp: str | None = None,
    aplicar_tope: bool = True,
    tipo_contrato: str | None = None,
) -> dict:
    """Descuentos legales de un trabajador para un monto imponible.

    Los argumentos opcionales (afp, aplicar_tope, tipo_contrato) existen para que el
    generador de datos pueda *simular errores* de una liquidacion. El calculo
    "esperado" siempre usa los datos del contrato (valores por defecto).
    """
    afp = afp or trabajador["afp"]
    tipo_contrato = tipo_contrato or trabajador["tipo_contrato"]

    tope_afp = tope_imponible_pesos(params, "afp_salud")
    tope_sc = tope_imponible_pesos(params, "seguro_cesantia")

    base_prev = min(imponible, tope_afp) if aplicar_tope else imponible
    base_sc = min(imponible, tope_sc)

    t_afp = tasa_afp(params, afp)
    t_salud = _d(params["cotizaciones"]["salud"])
    t_sc = tasa_seguro_cesantia(params, tipo_contrato)

    m_afp = redondear(_d(base_prev) * t_afp)
    m_salud = redondear(_d(base_prev) * t_salud)
    m_sc = redondear(_d(base_sc) * t_sc)

    base_trib = imponible - m_afp - m_salud - m_sc
    m_imp = impuesto_unico(params, base_trib)

    lineas = [
        {"codigo": "afp", "concepto": f"AFP {afp}", "institucion": afp, "base": base_prev,
         "tasa": float(t_afp), "monto": m_afp},
        {"codigo": "salud", "concepto": "Salud (Fonasa 7%)", "base": base_prev,
         "tasa": float(t_salud), "monto": m_salud},
        {"codigo": "seguro_cesantia", "concepto": "Seguro de cesantía", "base": base_sc,
         "tasa": float(t_sc), "monto": m_sc},
        {"codigo": "impuesto_unico", "concepto": "Impuesto único 2ª categoría",
         "base": base_trib, "tasa": None, "monto": m_imp},
    ]
    return {
        "imponible": imponible,
        "tope_afp_salud": tope_afp,
        "tope_seguro_cesantia": tope_sc,
        "base_tributable": base_trib,
        "lineas": lineas,
        "total": sum(l["monto"] for l in lineas),
    }


# ---------------------------------------------------------------- comparacion
def _causa_afp(esp: dict, pag: dict, tope_afp: int) -> str | None:
    if pag.get("institucion") and pag["institucion"] != esp.get("institucion"):
        return (f"La liquidación descuenta AFP {pag['institucion']} pero el contrato "
                f"indica AFP {esp['institucion']}.")
    if pag["base"] > tope_afp:
        return (f"La base usada (${pag['base']:,}) supera el tope imponible "
                f"(${tope_afp:,}).").replace(",", ".")
    return None


def comparar_con_liquidacion(params: dict, trabajador: dict, liquidacion: dict) -> dict:
    """Compara los descuentos esperados contra los pagados. Devuelve el diagnostico por linea."""
    tol = params.get("tolerancia_pesos", 1)
    imponible = sum(h["monto"] for h in liquidacion["haberes_imponibles"])
    esperado = calcular_descuentos(params, trabajador, imponible)
    pagadas = {l["codigo"]: l for l in liquidacion["descuentos_legales"]}

    pag_afp = pagadas["afp"]["monto"]
    pag_salud = pagadas["salud"]["monto"]
    pag_sc = pagadas["seguro_cesantia"]["monto"]
    imp_con_pagadas = impuesto_unico(params, imponible - pag_afp - pag_salud - pag_sc)

    filas: list[dict] = []
    hay_diferencia_previsional = False
    for esp in esperado["lineas"]:
        cod = esp["codigo"]
        pag = pagadas[cod]
        dif = pag["monto"] - esp["monto"]
        fila: dict[str, Any] = {
            "codigo": cod,
            "concepto": esp["concepto"],
            "concepto_pagado": pag.get("concepto"),
            "esperado": esp["monto"],
            "pagado": pag["monto"],
            "diferencia": dif,
            "base_esperada": esp["base"],
            "base_pagada": pag.get("base"),
            "estado": "ok",
            "causa_probable": None,
        }
        if abs(dif) > tol:
            if cod == "impuesto_unico":
                derivada = abs(pag["monto"] - imp_con_pagadas) <= tol
                fila["estado"] = "derivada" if derivada else "diferencia"
                if derivada:
                    fila["causa_probable"] = (
                        "Diferencia derivada: el impuesto se calculó bien, pero sobre una base "
                        "tributable distinta porque otra cotización se descontó mal."
                    )
            else:
                fila["estado"] = "diferencia"
                hay_diferencia_previsional = True
                if cod == "afp":
                    fila["causa_probable"] = _causa_afp(esp, pag, esperado["tope_afp_salud"])
                elif cod == "salud" and pag["base"] > esperado["tope_afp_salud"]:
                    fila["causa_probable"] = (
                        "La base usada supera el tope imponible de AFP/salud."
                    )
                elif cod == "seguro_cesantia" and esp["monto"] == 0 and pag["monto"] > 0:
                    fila["causa_probable"] = (
                        f"El contrato es {trabajador['tipo_contrato'].replace('_', ' ')}: "
                        "el trabajador no cotiza seguro de cesantía (lo paga el empleador)."
                    )
        filas.append(fila)

    # Gratificacion Art. 50 (verificacion del haber)
    base_grat = sum(h["monto"] for h in liquidacion["haberes_imponibles"]
                    if not h["concepto"].lower().startswith("gratificaci"))
    grat_esp = gratificacion_art50(params, base_grat)
    grat_pag = next((h["monto"] for h in liquidacion["haberes_imponibles"]
                     if h["concepto"].lower().startswith("gratificaci")), 0)
    verif_grat = {
        "concepto": "Gratificación legal Art. 50",
        "esperado": grat_esp,
        "pagado": grat_pag,
        "diferencia": grat_pag - grat_esp,
        "tope_mensual": tope_gratificacion_mensual(params),
        "estado": "ok" if abs(grat_pag - grat_esp) <= tol else "diferencia",
    }
    return {
        "imponible": imponible,
        "tope_afp_salud": esperado["tope_afp_salud"],
        "tope_seguro_cesantia": esperado["tope_seguro_cesantia"],
        "lineas": filas,
        "gratificacion": verif_grat,
        "hay_diferencias": any(f["estado"] == "diferencia" for f in filas)
        or verif_grat["estado"] != "ok",
        "hay_diferencia_previsional": hay_diferencia_previsional,
    }


def institucion_afp_de_concepto(concepto: str) -> str | None:
    m = re.search(r"AFP\s+(\w+)", concepto)
    return m.group(1) if m else None
