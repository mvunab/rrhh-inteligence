"""Recálculo de una liquidación: propuesta corregida, ajustes del analista y emisión.

La propuesta sale del motor determinista (harness.calculos), no del LLM. Queda como borrador
hasta que un analista la emite; recién ahí reemplaza a la liquidación vigente.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from harness import almacen
from harness.calculos import calcular_descuentos, cargar_parametros, gratificacion_art50
from harness.datos import obtener_liquidacion, obtener_trabajador
from rrhh.bandeja import decidir, sincronizar_casos

ORIGEN_EMITIDA = "rectificada"


def borrador_id(worker_id: str, periodo: str) -> str:
    return f"B-{worker_id}-{periodo}"


def generar(worker_id: str, periodo: str) -> dict:
    """Recalcula la liquidación emitida con la ficha vigente del periodo y la deja como borrador."""
    original = obtener_liquidacion(worker_id, periodo)
    ficha = obtener_trabajador(worker_id, periodo)
    if original is None or ficha is None:
        raise LookupError(f"No hay liquidación de {worker_id} para {periodo}.")
    params = cargar_parametros()
    imponibles, motivos = _haberes_sugeridos(params, ficha, original)
    previo = almacen.obtener_borrador(borrador_id(worker_id, periodo))
    ahora = _ahora()
    borrador = {
        "id": borrador_id(worker_id, periodo),
        "worker_id": worker_id,
        "periodo": periodo,
        "version": (previo or {}).get("version", 0) + 1,
        "estado": "borrador",
        "trabajador": {campo: ficha.get(campo) for campo in
                       ("nombre", "cargo", "area", "tipo_contrato", "afp", "salud", "fecha_inicio")},
        "original": copy.deepcopy(original),
        "motivos": motivos,
        "nota": "",
        "creado": ahora,
        "actualizado": ahora,
        "emitido": None,
    }
    return almacen.guardar_borrador(_recalcular(borrador, params, ficha, imponibles,
                                                original["haberes_no_imponibles"]))


def ajustar(id_: str, haberes_imponibles: list[dict], haberes_no_imponibles: list[dict],
            nota: str = "") -> dict:
    """El analista cambia haberes. Los descuentos legales se vuelven a calcular, no se escriben a mano."""
    borrador = _borrador_editable(id_)
    imponibles = _validar_haberes(haberes_imponibles, "imponibles")
    no_imponibles = _validar_haberes(haberes_no_imponibles, "no imponibles", permitir_vacio=True)
    if not imponibles:
        raise ValueError("La liquidación necesita al menos un haber imponible.")
    ficha = obtener_trabajador(borrador["worker_id"], borrador["periodo"])
    borrador["nota"] = str(nota or "").strip()
    previos = {h["concepto"]: h["monto"] for h in (borrador["propuesta"]["haberes_imponibles"]
                                                   + borrador["propuesta"]["haberes_no_imponibles"])}
    motivos = dict(borrador.get("motivos") or {})
    for haber in imponibles + no_imponibles:
        if previos.get(haber["concepto"]) != haber["monto"]:
            motivos[haber["concepto"]] = borrador["nota"] or "Ajuste del analista."
    borrador["motivos"] = motivos
    borrador["actualizado"] = _ahora()
    return almacen.guardar_borrador(_recalcular(borrador, cargar_parametros(), ficha, imponibles, no_imponibles))


def emitir(id_: str, nota: str) -> dict:
    """La propuesta pasa a ser la liquidación vigente y el caso queda decidido como corregido."""
    if not str(nota or "").strip():
        raise ValueError("La emisión necesita una nota.")
    borrador = _borrador_editable(id_)
    liquidacion = borrador["propuesta"]
    almacen.guardar_liquidaciones([liquidacion], ORIGEN_EMITIDA)
    sincronizar_casos([liquidacion])
    caso_id = f"{borrador['worker_id']}-{borrador['periodo']}"
    if almacen.obtener_caso(caso_id) is not None:
        decidir(caso_id, "corregir", f"Liquidación rectificada emitida ({borrador['id']}). {nota.strip()}")
    borrador.update(estado="emitida", nota=nota.strip(), emitido=_ahora(), actualizado=_ahora())
    return almacen.guardar_borrador(borrador)


def listar() -> list[dict]:
    return almacen.listar_borradores()


def obtener(id_: str) -> dict | None:
    return almacen.obtener_borrador(id_)


# ------------------------------------------------------------------ internos
def _borrador_editable(id_: str) -> dict:
    borrador = almacen.obtener_borrador(id_)
    if borrador is None:
        raise LookupError(f"No existe el borrador {id_}.")
    if borrador["estado"] != "borrador":
        raise ValueError("Esta liquidación ya fue emitida. Genera una propuesta nueva para cambiarla.")
    return borrador


def _haberes_sugeridos(params: dict, ficha: dict, original: dict) -> tuple[list[dict], dict[str, str]]:
    """Haberes imponibles corregidos: bono según la meta y gratificación Art. 50 recalculada."""
    motivos: dict[str, str] = {}
    haberes = [dict(h) for h in original["haberes_imponibles"]]
    bono = ficha.get("bono") or {}
    atenciones = (original.get("datos_variables") or {}).get("atenciones_mes")
    for haber in haberes:
        if haber["concepto"].lower().startswith("bono") and bono.get("meta_atenciones") and atenciones is not None:
            esperado = int(bono["monto"]) if atenciones >= int(bono["meta_atenciones"]) else 0
            if esperado != haber["monto"]:
                motivos[haber["concepto"]] = (f"{atenciones} atenciones registradas contra una meta de "
                                              f"{bono['meta_atenciones']}.")
                haber["monto"] = esperado
    base = sum(h["monto"] for h in haberes if not _es_gratificacion(h))
    for haber in haberes:
        if _es_gratificacion(haber):
            esperada = gratificacion_art50(params, base)
            if esperada != haber["monto"]:
                motivos[haber["concepto"]] = "25% de la remuneración mensual con tope de 4,75 IMM al año."
                haber["monto"] = esperada
    return haberes, motivos


def _recalcular(borrador: dict, params: dict, ficha: dict, imponibles: list[dict],
                no_imponibles: list[dict]) -> dict:
    original = borrador["original"]
    imponible = sum(h["monto"] for h in imponibles)
    calculo = calcular_descuentos(params, ficha, imponible)
    descuentos = [dict(linea) for linea in calculo["lineas"]]
    total_haberes = imponible + sum(h["monto"] for h in no_imponibles)
    total_descuentos = sum(d["monto"] for d in descuentos)
    borrador["propuesta"] = {
        "worker_id": original["worker_id"],
        "periodo": original["periodo"],
        "dias_trabajados": original.get("dias_trabajados"),
        "haberes_imponibles": imponibles,
        "haberes_no_imponibles": no_imponibles,
        "descuentos_legales": descuentos,
        "total_haberes": total_haberes,
        "total_descuentos": total_descuentos,
        "liquido_a_pagar": total_haberes - total_descuentos,
        "datos_variables": copy.deepcopy(original.get("datos_variables") or {}),
    }
    borrador["parametros"] = {"uf": params["uf"]["valor"], "tope_afp_salud": calculo["tope_afp_salud"],
                              "verificados": params.get("fecha_verificacion")}
    borrador["ajustes"] = _ajustes(original, borrador["propuesta"], borrador.get("motivos") or {}, ficha)
    return borrador


def _ajustes(original: dict, propuesta: dict, motivos: dict[str, str], ficha: dict) -> list[dict]:
    """Cada concepto que cambia respecto de la liquidación emitida, con su motivo."""
    filas = []
    for grupo in ("haberes_imponibles", "haberes_no_imponibles"):
        antes = {h["concepto"]: h["monto"] for h in original[grupo]}
        despues = {h["concepto"]: h["monto"] for h in propuesta[grupo]}
        for concepto in list(antes) + [c for c in despues if c not in antes]:
            a, d = antes.get(concepto, 0), despues.get(concepto, 0)
            if a != d:
                filas.append({"concepto": concepto, "emitido": a, "propuesto": d, "diferencia": d - a,
                              "motivo": motivos.get(concepto, "Ajuste del analista.")})
    pagados = {d["codigo"]: d for d in original["descuentos_legales"]}
    for linea in propuesta["descuentos_legales"]:
        previo = pagados.get(linea["codigo"], {"monto": 0, "concepto": linea["concepto"]})
        if previo["monto"] != linea["monto"]:
            filas.append({"concepto": linea["concepto"], "emitido": previo["monto"], "propuesto": linea["monto"],
                          "diferencia": linea["monto"] - previo["monto"],
                          "motivo": _motivo_descuento(linea, previo, ficha)})
    filas.append({"concepto": "Líquido a pagar", "emitido": original["liquido_a_pagar"],
                  "propuesto": propuesta["liquido_a_pagar"],
                  "diferencia": propuesta["liquido_a_pagar"] - original["liquido_a_pagar"],
                  "motivo": "Resultado de los ajustes anteriores."})
    return filas if len(filas) > 1 else []


def _motivo_descuento(linea: dict, previo: dict, ficha: dict) -> str:
    codigo = linea["codigo"]
    if codigo == "afp" and previo.get("institucion") and previo["institucion"] != linea.get("institucion"):
        return f"La ficha vigente indica AFP {linea['institucion']}, no {previo['institucion']}."
    if codigo in ("afp", "salud") and previo.get("base", 0) > linea["base"]:
        return "Base limitada al tope imponible del periodo."
    if codigo == "seguro_cesantia" and linea["monto"] == 0:
        return (f"Contrato {ficha['tipo_contrato'].replace('_', ' ')}: el trabajador no cotiza "
                "seguro de cesantía.")
    if codigo == "impuesto_unico":
        return "Base tributable recalculada con las cotizaciones corregidas."
    return "Recalculado con la ficha vigente y los parámetros del periodo."


def _validar_haberes(haberes: list[dict], nombre: str, *, permitir_vacio: bool = False) -> list[dict]:
    limpios = []
    for haber in haberes or []:
        concepto = str(haber.get("concepto") or "").strip()
        if not concepto:
            raise ValueError(f"Hay un haber {nombre} sin concepto.")
        try:
            monto = int(haber.get("monto"))
        except (TypeError, ValueError) as e:
            raise ValueError(f"El monto de {concepto} debe ser un número entero.") from e
        if monto < 0:
            raise ValueError(f"El monto de {concepto} no puede ser negativo.")
        limpios.append({"concepto": concepto, "monto": monto})
    if not limpios and not permitir_vacio:
        raise ValueError(f"Faltan haberes {nombre}.")
    return limpios


def _es_gratificacion(haber: dict) -> bool:
    return haber["concepto"].lower().startswith("gratificaci")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
