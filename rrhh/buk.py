"""Sincronización con Buk: vincula o da de alta trabajadores, actualiza su ficha y trae liquidaciones.

Buk es la fuente de la ficha (AFP, salud, contrato, sueldo base). Lo que Buk no informa
(colación, movilización, bono, asignación de turno) se conserva. Solo se lee de Buk; no se escribe.
"""
from __future__ import annotations

from datetime import date

from fuentes.buk import BukConector, ClienteBuk, ficha_desde_empleado
from harness import almacen

from .bandeja import recalcular_trabajador, sincronizar_casos

# Lo que Buk actualiza en una ficha que ya existe. La jornada de Buk es solo horas: no pisa el texto pactado.
CAMPOS_ACTUALIZABLES = (
    "nombre", "cargo", "area", "tipo_contrato", "fecha_inicio", "fecha_termino", "afp", "salud", "sueldo_base",
)
_CAMPOS_DEL_CALCULO = ("afp", "tipo_contrato", "salud")
EVENTOS_DE_TRABAJADOR = (
    "employee_create", "employee_update", "employee_plan_update", "job_hire", "job_movement", "job_termination",
)
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre")


def sincronizar(periodo: str, conector: BukConector | None = None) -> dict:
    conector = conector or BukConector()
    resultado = conector.cargar(periodo=periodo)
    asignaciones = {
        liq["buk"]["employee_id"]: {h["concepto"]: h["monto"] for h in liq["haberes_no_imponibles"]}
        for liq in resultado.liquidaciones
    }
    ids: dict[int, str] = {}
    altas, actualizados = [], []
    for ficha in resultado.trabajadores:
        res = _sincronizar_ficha(ficha, asignaciones.get(ficha["buk_id"], {}))
        ids[ficha["buk_id"]] = res["worker_id"]
        if res["alta"]:
            altas.append({"worker_id": res["worker_id"], "nombre": ficha["nombre"]})
        elif res["cambios"]:
            actualizados.append({"worker_id": res["worker_id"], "nombre": ficha["nombre"], "cambios": res["cambios"]})

    liquidaciones = []
    for liq in resultado.liquidaciones:
        liq["worker_id"] = ids[liq["buk"]["employee_id"]]
        liquidaciones.append(liq)
    if liquidaciones:
        almacen.guardar_liquidaciones(liquidaciones, "buk", autor="Buk")
    casos = sincronizar_casos(liquidaciones) if liquidaciones else []

    return {
        "periodo": periodo,
        "modo": conector.modo,
        "trabajadores": len(resultado.trabajadores),
        "liquidaciones": len(liquidaciones),
        "altas": altas,
        "actualizados": actualizados,
        "casos": casos,
        "resumen": _resumen(periodo, conector.modo, len(resultado.trabajadores), liquidaciones, altas,
                            actualizados, casos),
    }


def aplicar_evento(evento: dict, cliente: ClienteBuk | None = None) -> dict:
    """Webhook de Buk. Solo trae el employee_id: la ficha completa se pide a la API."""
    datos = evento.get("data", evento) if isinstance(evento, dict) else {}
    tipo = datos.get("event_type")
    if tipo not in EVENTOS_DE_TRABAJADOR or not datos.get("employee_id"):
        return {"procesado": False, "event_type": tipo, "motivo": "El evento no cambia la ficha de un trabajador."}
    cliente = cliente or ClienteBuk.desde_entorno()
    ficha = ficha_desde_empleado(cliente.empleado(datos["employee_id"]))
    res = _sincronizar_ficha(ficha, {})
    return {"procesado": True, "event_type": tipo, **res}


# ------------------------------------------------------------------ fichas
def _resolver(ficha: dict, fichas: dict[str, dict]) -> str | None:
    """worker_id del trabajador de Buk: por id de Buk, por código de ficha o por RUT."""
    for wid, actual in fichas.items():
        if actual.get("buk_id") == ficha["buk_id"]:
            return wid
    if ficha["code_sheet"] in fichas:
        return ficha["code_sheet"]
    if ficha.get("rut"):
        for wid, actual in fichas.items():
            if actual.get("rut") == ficha["rut"]:
                return wid
    return None


def _sincronizar_ficha(ficha: dict, asignaciones: dict[str, int]) -> dict:
    fichas = almacen.fichas_base()
    worker_id = _resolver(ficha, fichas)
    if worker_id is None:
        return _alta(ficha, asignaciones)
    actual = dict(fichas[worker_id])
    cambios = {campo: [actual.get(campo), ficha[campo]] for campo in CAMPOS_ACTUALIZABLES
               if ficha.get(campo) not in (None, "") and actual.get(campo) != ficha[campo]}
    if "fecha_termino" in actual and ficha["fecha_termino"] is None and actual["fecha_termino"]:
        cambios["fecha_termino"] = [actual["fecha_termino"], None]  # Buk quitó el término: renovación
    vinculo = {"buk_id": ficha["buk_id"], "rut": ficha.get("rut")}
    if cambios or any(actual.get(k) != v for k, v in vinculo.items()):
        actual.update({campo: nuevo for campo, (_, nuevo) in cambios.items()}, **vinculo)
        almacen.guardar_ficha(worker_id, actual)
    if any(campo in cambios for campo in _CAMPOS_DEL_CALCULO):
        recalcular_trabajador(worker_id)
    return {"worker_id": worker_id, "alta": False, "cambios": cambios}


def _alta(ficha: dict, asignaciones: dict[str, int]) -> dict:
    worker_id = almacen.nuevo_worker_id()
    nueva = {k: v for k, v in ficha.items() if k != "code_sheet"}
    nueva.update({
        "jornada": ficha.get("jornada") or "Jornada informada en Buk",
        "colacion": _asignacion(asignaciones, "colaci"),
        "movilizacion": _asignacion(asignaciones, "moviliz"),
        "asignacion_turno": 0,
        "bono": None,
    })
    almacen.guardar_ficha(worker_id, nueva)
    inicio = date.fromisoformat(nueva["fecha_inicio"]) if nueva.get("fecha_inicio") else date.today()
    almacen.guardar_documento(
        f"contrato_{worker_id}.md", worker_id, "contrato", contrato_desde_buk(worker_id, nueva),
        vigente_desde=inicio, descripcion="Generado desde la ficha de Buk", origen="buk",
    )
    return {"worker_id": worker_id, "alta": True, "cambios": {}}


def _asignacion(asignaciones: dict[str, int], prefijo: str) -> int:
    return next((m for concepto, m in asignaciones.items() if prefijo in concepto.lower()), 0)


def _clp(n: int) -> str:
    return f"${n:,.0f}".replace(",", ".")


def contrato_desde_buk(worker_id: str, f: dict) -> str:
    """Contrato con la misma estructura que los de data/documentos/contratos, armado con los datos de Buk."""
    duracion = (
        f"El presente contrato es a plazo fijo, desde el {f['fecha_inicio']} hasta el {f['fecha_termino']}. "
        "En los contratos a plazo fijo el seguro de cesantía es de cargo exclusivo del empleador: "
        "el trabajador no cotiza seguro de cesantía."
        if f["tipo_contrato"] == "plazo_fijo" else
        f"El presente contrato es de duración indefinida, a partir del {f['fecha_inicio']}. El trabajador cotiza "
        "el 0,6% de su remuneración imponible al seguro de cesantía."
    )
    asignaciones = (
        f"El trabajador recibirá una asignación de colación de {_clp(f['colacion'])} mensuales y asignación de "
        f"movilización de {_clp(f['movilizacion'])} mensuales, ambas no imponibles ni tributables."
        if f["colacion"] or f["movilizacion"] else "No se pactan asignaciones no imponibles."
    )
    return f"""# Contrato de trabajo de {f['nombre']} ({worker_id})

> Documento ficticio con fines didácticos, generado desde la ficha de Buk (id {f['buk_id']}). Empleador: Clínica Traumatología Cóndor SpA (ficticia).

## CLÁUSULA PRIMERA: Partes y cargo

La Clínica Traumatología Cóndor SpA (ficticia), en adelante el empleador, contrata a {f['nombre']} (código {worker_id}, RUT {f.get('rut') or 'sin informar'}) para desempeñar el cargo de {f['cargo']} en el área de {f['area'] or 'sin área'}, a partir del {f['fecha_inicio']}.

## CLÁUSULA SEGUNDA: Jornada de trabajo

La jornada de trabajo será de {f['jornada']}.

## CLÁUSULA TERCERA: Remuneración base

El empleador pagará al trabajador un sueldo base mensual de {_clp(f['sueldo_base'])}, pagadero el último día hábil de cada mes, mediante transferencia bancaria.

## CLÁUSULA CUARTA: Gratificación legal

Las partes acuerdan pagar la gratificación legal por el sistema del artículo 50 del Código del Trabajo, en forma mensual: 25% de la remuneración mensual imponible (sin considerar la propia gratificación), con el tope de 4,75 ingresos mínimos mensuales al año, pagadero en doceavos.

## CLÁUSULA QUINTA: Asignaciones no imponibles

{asignaciones}

## CLÁUSULA SEXTA: Previsión y salud

El trabajador declara estar afiliado a la AFP {f['afp']} y al sistema de salud {f['salud']}. El empleador descontará de la remuneración las cotizaciones correspondientes a la AFP {f['afp']} y a {f['salud']}, y las enterará en las instituciones respectivas.

## CLÁUSULA SÉPTIMA: Duración del contrato

{duracion}

## CLÁUSULA OCTAVA: Reglamento Interno

El trabajador declara conocer el Reglamento Interno de Orden, Higiene y Seguridad y la Política de Bonos Variables vigentes, que forman parte de este contrato.
"""


def _resumen(periodo: str, modo: str, trabajadores: int, liquidaciones: list[dict], altas: list[dict],
             actualizados: list[dict], casos: list[str]) -> str:
    anio, mes = periodo.split("-")
    origen = "Buk (demostración)" if modo == "demo" else "Buk"
    if not liquidaciones:
        texto = f"{origen}: {trabajadores} trabajador(es); no hay liquidaciones de {_MESES[int(mes) - 1]} {anio}."
    else:
        texto = (f"{origen}: {trabajadores} trabajador(es) y {len(liquidaciones)} liquidación(es) de "
                 f"{_MESES[int(mes) - 1]} {anio}.")
    if altas:
        texto += " Alta: " + ", ".join(f"{a['worker_id']} {a['nombre']}" for a in altas) + "."
    if actualizados:
        texto += " Ficha actualizada: " + ", ".join(a["worker_id"] for a in actualizados) + "."
    if liquidaciones:
        texto += (f" Casos con diferencias: {', '.join(casos)}." if casos
                  else " Ninguna tiene diferencias que revisar.")
    return texto
