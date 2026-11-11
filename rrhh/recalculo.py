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


class VersionDesactualizada(ValueError):
    """Se intentó emitir una versión distinta de la que está guardada."""


AUTOR_POR_DEFECTO = "Analista RR.HH."


def generar(worker_id: str, periodo: str, autor: str = AUTOR_POR_DEFECTO) -> dict:
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
        "autor": _autor(autor),
    }
    borrador = _recalcular(borrador, params, ficha, imponibles, original["haberes_no_imponibles"])
    return almacen.guardar_borrador(borrador, _evento("propuesta_generada", borrador, {
        "motivos": motivos, "reemplaza_version": (previo or {}).get("version"),
        "estado_previo": (previo or {}).get("estado")}))


def ajustar(id_: str, haberes_imponibles: list[dict], haberes_no_imponibles: list[dict],
            nota: str = "", autor: str = AUTOR_POR_DEFECTO) -> dict:
    """El analista cambia haberes. Los descuentos legales se vuelven a calcular, no se escriben a mano.
    Cada ajuste es una versión nueva."""
    borrador = _borrador_editable(id_)
    anterior = copy.deepcopy(borrador["propuesta"])
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
    borrador.update(actualizado=_ahora(), version=borrador["version"] + 1, autor=_autor(autor))
    borrador = _recalcular(borrador, cargar_parametros(), ficha, imponibles, no_imponibles)
    cambios = diff_liquidaciones(anterior, borrador["propuesta"])["cambios"]
    if not cambios:
        raise ValueError("El ajuste no cambia ningún monto.")
    return almacen.guardar_borrador(borrador, _evento("propuesta_ajustada", borrador, {
        "nota": borrador["nota"], "cambios": cambios}))


def emitir(id_: str, nota: str, version: int, autor: str = AUTOR_POR_DEFECTO) -> dict:
    """La propuesta pasa a ser la liquidación vigente y el caso queda decidido como corregido.

    Exige la versión que el analista revisó en el diff: si alguien la cambió después, no se emite.
    """
    if not str(nota or "").strip():
        raise ValueError("La emisión necesita una nota.")
    borrador = _borrador_editable(id_)
    if version != borrador["version"]:
        raise VersionDesactualizada(
            f"Revisaste la versión v{version}, pero la propuesta ya va en v{borrador['version']}. "
            "Revisa los cambios otra vez antes de emitir.")
    autor = _autor(autor)
    liquidacion = borrador["propuesta"]
    anterior = obtener_liquidacion(borrador["worker_id"], borrador["periodo"])
    almacen.guardar_liquidaciones([liquidacion], ORIGEN_EMITIDA, autor,
                                  {"borrador": borrador["id"], "version": version, "nota": nota.strip()})
    sincronizar_casos([liquidacion])
    caso_id = f"{borrador['worker_id']}-{borrador['periodo']}"
    if almacen.obtener_caso(caso_id) is not None:
        decidir(caso_id, "corregir",
                f"Liquidación rectificada emitida ({borrador['id']} v{version}, {autor}). {nota.strip()}")
    borrador.update(estado="emitida", nota=nota.strip(), emitido=_ahora(), actualizado=_ahora(), autor=autor)
    return almacen.guardar_borrador(borrador, _evento("liquidacion_emitida", borrador, {
        "nota": nota.strip(),
        "liquido_anterior": (anterior or borrador["original"])["liquido_a_pagar"],
        "cambios": diff_liquidaciones(anterior or borrador["original"], liquidacion)["cambios"],
    }))


def historial(id_: str) -> list[dict]:
    """Todo lo que pasó con la liquidación del periodo: propuestas, ajustes, emisiones y reemplazos."""
    borrador = almacen.obtener_borrador(id_)
    if borrador is None:
        raise LookupError(f"No existe el borrador {id_}.")
    return almacen.listar_bitacora(borrador["worker_id"], borrador["periodo"])


def comparar(id_: str, base: str = "emitida") -> dict:
    """Diff entre la liquidación emitida (o una versión anterior de la propuesta) y la versión actual."""
    borrador = almacen.obtener_borrador(id_)
    if borrador is None:
        raise LookupError(f"No existe el borrador {id_}.")
    actual = f"Propuesta v{borrador['version']}" + (" (emitida)" if borrador["estado"] == "emitida" else "")
    if base == "emitida":
        antes, etiqueta = borrador["original"], "Liquidación emitida"
    else:
        try:
            numero = int(str(base).lstrip("v"))
        except ValueError as e:
            raise ValueError("Compara contra 'emitida' o un número de versión.") from e
        registro = next((e["datos"]["propuesta"] for e in reversed(historial(id_))
                         if e["datos"].get("version") == numero and "propuesta" in e["datos"]), None)
        if registro is None:
            raise LookupError(f"No hay registro de la versión v{numero}.")
        antes, etiqueta = registro, f"Propuesta v{numero}"
    diff = diff_liquidaciones(antes, borrador["propuesta"], etiqueta, actual)
    motivos = {a["concepto"]: a["motivo"] for a in borrador.get("ajustes") or []}
    nombre = (borrador.get("trabajador") or {}).get("nombre") or borrador["worker_id"]
    diff["en_simple"] = en_simple(diff, antes, borrador["propuesta"], motivos, nombre, etiqueta)
    return diff


def en_simple(diff: dict, antes: dict, despues: dict, motivos: dict[str, str], nombre: str,
              referencia: str) -> dict:
    """El mismo diff contado para alguien que no lee tablas: cuánto cambia el pago y por qué."""
    primero = nombre.split()[0]
    delta = diff["diferencia_liquido"]
    if delta > 0:
        titular = f"{primero} recibiría {_clp(delta)} más que en la {referencia.lower()}."
    elif delta < 0:
        titular = f"{primero} recibiría {_clp(-delta)} menos que en la {referencia.lower()}."
    else:
        titular = f"El monto que recibe {primero} no cambia respecto de la {referencia.lower()}."
    puntos = []
    for cambio in diff["cambios"]:
        a, d, concepto = cambio["antes"], cambio["despues"], cambio["concepto"]
        descuento = cambio["seccion"] == "Descuentos legales"
        if a is None:
            texto, favorece = f"Se agrega **{concepto}** por {_clp(d)}.", not descuento
        elif d is None:
            texto, favorece = f"Se quita **{concepto}**, que era de {_clp(a)}.", descuento
        elif d == a:
            continue
        else:
            verbo = "sube" if d > a else "baja"
            sujeto = f"El descuento de **{concepto}**" if descuento else f"**{concepto}**"
            texto = f"{sujeto} {verbo} de {_clp(a)} a {_clp(d)} ({_clp(abs(d - a))} {'más' if d > a else 'menos'})."
            favorece = (d < a) if descuento else (d > a)
        puntos.append({"texto": texto, "por_que": _motivo_simple(motivos.get(concepto)),
                       "favorece_al_trabajador": favorece})
    sin_cambio = sum(len(antes.get(g) or []) for g in ("haberes_imponibles", "haberes_no_imponibles",
                                                       "descuentos_legales")) - len(
        [c for c in diff["cambios"] if c["antes"] is not None and c["antes"] != c["despues"]])
    return {
        "titular": titular,
        "liquido_antes": antes.get("liquido_a_pagar", 0),
        "liquido_despues": despues.get("liquido_a_pagar", 0),
        "puntos": puntos,
        "pie": (f"El resto de la liquidación ({sin_cambio} conceptos) queda igual." if sin_cambio > 0
                else "Todos los conceptos cambian."),
    }


def diff_liquidaciones(antes: dict, despues: dict, etiqueta_antes: str = "antes",
                       etiqueta_despues: str = "después") -> dict:
    """Diff línea por línea, como un diff de código: '-' lo que sale, '+' lo que entra, ' ' sin cambio."""
    lineas = [f"--- {etiqueta_antes}", f"+++ {etiqueta_despues}"]
    cambios = []
    ancho = max([len(x["concepto"]) for liq in (antes, despues)
                 for g in ("haberes_imponibles", "haberes_no_imponibles", "descuentos_legales")
                 for x in liq.get(g) or []] + [len("Total descuentos")]) + 2
    secciones = (("Haberes imponibles", "haberes_imponibles", lambda h: _linea_haber(h, ancho)),
                 ("Haberes no imponibles", "haberes_no_imponibles", lambda h: _linea_haber(h, ancho)),
                 ("Descuentos legales", "descuentos_legales", lambda d: _linea_descuento(d, ancho)))
    for titulo, grupo, formato in secciones:
        lineas.append(f"@@ {titulo} @@")
        a = {_clave(x): x for x in antes.get(grupo) or []}
        d = {_clave(x): x for x in despues.get(grupo) or []}
        for clave in list(a) + [c for c in d if c not in a]:
            viejo, nuevo = a.get(clave), d.get(clave)
            if viejo is not None and nuevo is not None and formato(viejo) == formato(nuevo):
                lineas.append(f"  {formato(nuevo)}")
                continue
            if viejo is not None:
                lineas.append(f"- {formato(viejo)}")
            if nuevo is not None:
                lineas.append(f"+ {formato(nuevo)}")
            cambios.append({"seccion": titulo, "concepto": (nuevo or viejo)["concepto"],
                            "antes": viejo["monto"] if viejo else None,
                            "despues": nuevo["monto"] if nuevo else None})
    lineas.append("@@ Totales @@")
    for etiqueta, campo in (("Total haberes", "total_haberes"), ("Total descuentos", "total_descuentos"),
                            ("Líquido a pagar", "liquido_a_pagar")):
        v_antes, v_despues = antes.get(campo, 0), despues.get(campo, 0)
        if v_antes == v_despues:
            lineas.append(f"  {etiqueta:<{ancho}}{_clp(v_despues):>12}")
        else:
            lineas.append(f"- {etiqueta:<{ancho}}{_clp(v_antes):>12}")
            lineas.append(f"+ {etiqueta:<{ancho}}{_clp(v_despues):>12}")
    liquido = despues.get("liquido_a_pagar", 0) - antes.get("liquido_a_pagar", 0)
    return {"texto": "\n".join(lineas), "cambios": cambios, "diferencia_liquido": liquido,
            "etiquetas": [etiqueta_antes, etiqueta_despues]}


_MOTIVOS_SIMPLES = {
    "Base limitada al tope imponible del periodo.":
        "la AFP y la salud se cobran solo hasta un sueldo máximo que fija la ley (el tope imponible). "
        "Antes se cobraban sobre el sueldo completo.",
    "Base tributable recalculada con las cotizaciones corregidas.":
        "al descontar menos AFP y salud, queda más sueldo sobre el que se paga impuesto.",
    "Recalculado con la ficha vigente y los parámetros del periodo.":
        "se volvió a calcular con el contrato vigente y los valores legales del mes.",
    "Resultado de los ajustes anteriores.": "",
}


def _motivo_simple(motivo: str | None) -> str:
    if not motivo:
        return ""
    if motivo in _MOTIVOS_SIMPLES:
        return _MOTIVOS_SIMPLES[motivo]
    if motivo.startswith("Contrato plazo fijo"):
        return "con contrato a plazo fijo, el seguro de cesantía lo paga solo el empleador."
    if motivo.startswith("25% de la remuneración"):
        return "la gratificación legal es un 25% del sueldo, con un máximo anual que fija la ley."
    if "atenciones registradas" in motivo:
        return f"el bono depende de cumplir la meta de atenciones ({motivo.rstrip('.')})."
    return motivo[:1].lower() + motivo[1:]


def _clave(linea: dict) -> str:
    return linea.get("codigo") or linea["concepto"]


def _linea_haber(haber: dict, ancho: int) -> str:
    return f"{haber['concepto']:<{ancho}}{_clp(haber['monto']):>12}"


def _linea_descuento(linea: dict, ancho: int) -> str:
    tasa = f" × {linea['tasa'] * 100:.2f}%".replace(".", ",") if linea.get("tasa") is not None else ""
    return f"{linea['concepto']:<{ancho}}{_clp(linea['monto']):>12}  (base {_clp(linea.get('base'))}{tasa})"


def _clp(n) -> str:
    if n is None:
        return "—"
    return ("-" if n < 0 else "") + f"${abs(int(n)):,}".replace(",", ".")


def _evento(accion: str, borrador: dict, extra: dict) -> dict:
    return {"accion": accion, "autor": borrador["autor"], "datos": {
        "borrador": borrador["id"], "version": borrador["version"],
        "liquido": borrador["propuesta"]["liquido_a_pagar"],
        "propuesta": copy.deepcopy(borrador["propuesta"]), **extra}}


def _autor(autor: str | None) -> str:
    return (str(autor or "").strip() or AUTOR_POR_DEFECTO)[:80]


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
