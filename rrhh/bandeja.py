"""Bandeja de casos de RR.HH. Los casos viven en el almacén, junto a las liquidaciones."""
from __future__ import annotations

from datetime import datetime, timezone

from harness import almacen
from harness.calculos import cargar_parametros, comparar_con_liquidacion
from harness.datos import obtener_trabajador

ESTADOS_DECISION = ("mantener", "corregir", "derivar")
_UMBRAL_CRITICO = 50_000


def sincronizar_casos(liquidaciones: list[dict]) -> list[str]:
    """Abre o actualiza un caso por cada liquidación con diferencias.

    Compara contra la ficha vigente en el periodo de cada liquidación. Si un caso abierto deja de
    tener diferencias (por ejemplo, porque llegó un anexo), se actualiza y queda marcado así.
    """
    params = cargar_parametros()
    abiertos = []
    for liq in liquidaciones:
        trabajador = obtener_trabajador(liq["worker_id"], liq["periodo"])
        if trabajador is None:
            from fuentes.protocolo import ErrorCarga
            raise ErrorCarga(f"No existe el trabajador {liq['worker_id']} en los datos de la clínica.")
        diag = comparar_con_liquidacion(params, trabajador, liq)
        caso_id = f"{liq['worker_id']}-{liq['periodo']}"
        previo = almacen.obtener_caso(caso_id)
        if not diag["hay_diferencias"] and previo is None:
            continue
        resumen = _resumen(diag)
        ahora = _ahora()
        if previo is None:
            caso = {
                "id": caso_id, "worker_id": liq["worker_id"], "periodo": liq["periodo"],
                "estado": "pendiente", "nota": "", "creado": ahora, "actualizado": ahora,
                "informe": None, "reabierto": False, **resumen,
            }
        else:
            caso = previo
            cambio = previo.get("lineas") != resumen["lineas"]
            caso.update(resumen)
            caso["actualizado"] = ahora
            if cambio and caso["estado"] != "pendiente" and resumen["hay_diferencias"]:
                caso["estado"] = "pendiente"
                caso["reabierto"] = True
        almacen.guardar_caso(caso)
        if resumen["hay_diferencias"]:
            abiertos.append(caso_id)
    return abiertos


def recalcular_trabajador(worker_id: str, desde: str | None = None) -> list[str]:
    """Vuelve a comparar las liquidaciones del trabajador desde una fecha (un contrato o anexo nuevo)."""
    periodo_desde = (desde or "")[:7]
    liqs = [l for l in almacen.listar_liquidaciones(worker_id) if l["periodo"] >= periodo_desde]
    sincronizar_casos(liqs)
    return [f"{l['worker_id']}-{l['periodo']}" for l in liqs]


def abrir_casos_faltantes() -> list[str]:
    """Abre un caso por cada liquidación guardada que todavía no tiene uno.

    La bandeja sale de los datos. No hace falta volver a cargar un archivo de ejemplo.
    """
    existentes = {c["id"] for c in almacen.listar_casos()}
    faltan = [liq for liq in almacen.listar_liquidaciones()
              if f"{liq['worker_id']}-{liq['periodo']}" not in existentes]
    return sincronizar_casos(faltan) if faltan else []


def listar_casos() -> list[dict]:
    orden = {"pendiente": 0, "corregir": 1, "derivar": 2, "mantener": 3}
    return sorted(
        almacen.listar_casos(),
        key=lambda c: (not c.get("hay_diferencias", True), orden.get(c["estado"], 9),
                       c["severidad"] != "critico", c["id"]),
    )


def listar_bandeja() -> list[dict]:
    """Una fila por liquidación en revisión. Junta el caso del motor y las solicitudes del trabajador,
    para que la misma liquidación no aparezca dos veces."""
    from rrhh.solicitudes import listar_solicitudes

    fichas = almacen.fichas_base()
    filas: dict[str, dict] = {}
    for caso in almacen.listar_casos():
        if caso.get("hay_diferencias") or caso["estado"] != "pendiente":
            filas[caso["id"]] = _fila_bandeja(caso["worker_id"], caso["periodo"], fichas) | {"caso": caso}
    for solicitud in listar_solicitudes():
        clave = f"{solicitud['worker_id']}-{solicitud['periodo']}"
        if clave not in filas:
            caso = almacen.obtener_caso(clave)
            filas[clave] = _fila_bandeja(solicitud["worker_id"], solicitud["periodo"], fichas) | {"caso": caso}
        filas[clave]["solicitudes"].append(solicitud)
    return sorted((_resumir(f) for f in filas.values()),
                  key=lambda f: (f["estado"] != "pendiente", f["tipo"] != "diferencia", -abs(f["diferencia_total"]),
                                 f["id"]))


def _fila_bandeja(worker_id: str, periodo: str | None, fichas: dict) -> dict:
    ficha = fichas.get(worker_id) or {}
    return {"id": f"{worker_id}-{periodo}", "worker_id": worker_id, "nombre": ficha.get("nombre", worker_id),
            "area": ficha.get("area") or "Sin área", "periodo": periodo, "solicitudes": []}


def _resumir(fila: dict) -> dict:
    caso, solicitudes = fila.pop("caso"), fila["solicitudes"]
    con_diferencia = bool(caso and caso.get("hay_diferencias"))
    origen = []
    if solicitudes:
        origen.append("trabajador")
    if con_diferencia:
        origen.append("sistema")
    pendiente = (any(s["estado"] == "pendiente" for s in solicitudes)
                 or bool(caso and con_diferencia and caso["estado"] == "pendiente"))
    return fila | {
        "caso_id": caso["id"] if caso else None,
        "tipo": "diferencia" if con_diferencia or any(s["tipo"] == "diferencia" for s in solicitudes)
                else "revision",
        "origen": origen,
        "estado": "pendiente" if pendiente else "resuelta",
        "severidad": caso["severidad"] if caso else "sin diferencias",
        "diferencia_total": caso["diferencia_total"] if con_diferencia else 0,
        "decision": caso["estado"] if caso and caso["estado"] != "pendiente" else None,
    }


def obtener_caso(caso_id: str) -> dict | None:
    return almacen.obtener_caso(caso_id)


def decidir(caso_id: str, estado: str, nota: str) -> dict:
    if estado not in ESTADOS_DECISION:
        raise ValueError("Decisión desconocida. Usa mantener, corregir o derivar.")
    if not str(nota).strip():
        raise ValueError("La decisión necesita una nota.")
    caso = almacen.obtener_caso(caso_id)
    if caso is None:
        raise ValueError(f"No existe el caso {caso_id}.")
    caso.update(estado=estado, nota=str(nota).strip(), reabierto=False, actualizado=_ahora())
    return almacen.guardar_caso(caso)


def guardar_informe(caso_id: str, informe: dict) -> dict:
    caso = almacen.obtener_caso(caso_id)
    if caso is None:
        raise ValueError(f"No existe el caso {caso_id}.")
    caso.update(informe=informe, actualizado=_ahora())
    return almacen.guardar_caso(caso)


def _resumen(diag: dict) -> dict:
    lineas = [{
        "codigo": fila["codigo"], "concepto": fila["concepto"], "esperado": fila["esperado"],
        "pagado": fila["pagado"], "diferencia": fila["diferencia"], "estado": fila["estado"],
        "causa_probable": fila["causa_probable"],
    } for fila in diag["lineas"]]
    grat = diag["gratificacion"]
    lineas.append({
        "codigo": "gratificacion", "concepto": grat["concepto"], "esperado": grat["esperado"],
        "pagado": grat["pagado"], "diferencia": grat["diferencia"], "estado": grat["estado"],
        "causa_probable": None,
    })
    diferencias = [abs(l["diferencia"]) for l in lineas if l["estado"] == "diferencia"]
    if not diferencias:
        severidad = "sin diferencias"
    elif any(d >= _UMBRAL_CRITICO for d in diferencias):
        severidad = "critico"
    else:
        severidad = "revisar"
    return {
        "lineas": lineas,
        "hay_diferencias": bool(diferencias),
        "diferencia_total": sum(l["diferencia"] for l in lineas if l["estado"] == "diferencia"),
        "severidad": severidad,
    }


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
