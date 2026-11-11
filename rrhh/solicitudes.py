"""Solicitudes que un analista debe ver: el agente marcó revisión, o el trabajador la pidió en el mensaje."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from harness import almacen

_PEDIDO = re.compile(
    r"\b(solicitud|solicito|solicitar)\b"
    r"|\b(rr\.?\s*hh|recursos humanos)\b.{0,48}\b(revis\w*|vean|mira[rn]?)\b"
    r"|\b(revis\w*|vean|mira[rn]?)\b.{0,48}\b(rr\.?\s*hh|recursos humanos|una persona|un analista)\b"
    r"|\bhablar con (un |una )?(persona|analista|rr\.?\s*hh|recursos humanos)\b"
    r"|\bque (un |una )?(analista|persona) (lo |la )?revis",
    re.IGNORECASE | re.DOTALL,
)
_PERIODO = re.compile(r"\b(20\d{2})[-/](0[1-9]|1[0-2])\b")


def es_solicitud(pregunta: str) -> bool:
    """El pedido de una persona llega dentro del mensaje, no en un formulario aparte."""
    return _PEDIDO.search(pregunta or "") is not None


def abrir_desde_consulta(worker_id: str, pregunta: str, informe: dict | None) -> dict | None:
    """Si el trabajador pide revisión, la solicitud llega al analista. Si solo la marca el agente,
    queda como propuesta: el trabajador decide si la envía."""
    motivos = []
    if es_solicitud(pregunta):
        motivos.append("trabajador")
    if informe and informe.get("requiere_revision_rrhh"):
        motivos.append("agente")
    if not motivos:
        return None
    ficha = almacen.fichas_base().get(worker_id) or {}
    hallazgos = list((informe or {}).get("hallazgos") or [])
    periodo = _periodo(worker_id, pregunta)
    tipo = _tipo(worker_id, periodo, hallazgos)
    ahora = _ahora()
    estado = "pendiente" if "trabajador" in motivos else "propuesta"
    previa = _abierta_del_dia(worker_id, periodo, tipo, ahora)
    if previa is not None:
        return almacen.guardar_solicitud(_sumar(previa, pregunta, motivos, informe, hallazgos, estado, ahora))
    solicitud = {
        "id": f"S-{uuid4().hex[:8]}",
        "worker_id": worker_id,
        "area": ficha.get("area") or None,
        "tipo": tipo,
        "periodo": periodo,
        "pregunta": pregunta.strip(),
        "mensajes": [{"texto": pregunta.strip(), "creado": ahora, "agente": _resumen(informe, motivos)}],
        "motivos": motivos,
        "resumen": _resumen(informe, motivos),
        "hallazgos": hallazgos,
        "estado": estado,
        "respuesta": "",
        "creado": ahora,
        "respondido": None,
    }
    return almacen.guardar_solicitud(solicitud)


def _abierta_del_dia(worker_id: str, periodo: str | None, tipo: str, ahora: str) -> dict | None:
    """Misma persona, mismo día, misma liquidación y mismo tipo: es la misma solicitud."""
    for previa in almacen.listar_solicitudes(worker_id):
        if (previa["estado"] in ("propuesta", "pendiente")
                and _dia(previa["creado"]) == _dia(ahora)
                and _periodo_de(previa) == periodo
                and _tipo_de(previa) == tipo):
            return previa
    return None


def _sumar(previa: dict, pregunta: str, motivos: list[str], informe: dict | None, hallazgos: list[dict],
           estado: str, ahora: str) -> dict:
    mensajes = _mensajes(previa)
    unidos = [m for m in ("trabajador", "agente") if m in set(previa.get("motivos") or []) | set(motivos)]
    if pregunta.strip() not in {m["texto"] for m in mensajes}:
        mensajes.append({"texto": pregunta.strip(), "creado": ahora, "agente": _resumen(informe, unidos)})
    previa.update(
        mensajes=mensajes,
        motivos=unidos,
        resumen=_resumen(informe, unidos),
        hallazgos=hallazgos or previa.get("hallazgos") or [],
        actualizado=ahora,
    )
    if previa["estado"] == "propuesta" and estado == "pendiente":
        previa.update(estado="pendiente", creado=ahora)
    return previa


def enviar(worker_id: str, solicitud_id: str) -> dict:
    """El trabajador acepta la invitación del agente y la solicitud pasa a la bandeja del analista."""
    solicitud = almacen.obtener_solicitud(solicitud_id)
    if solicitud is None or solicitud["worker_id"] != worker_id:
        raise LookupError(f"No existe la solicitud {solicitud_id}.")
    if solicitud["estado"] != "propuesta":
        raise ValueError("La solicitud ya fue enviada a RR.HH.")
    solicitud.update(estado="pendiente", motivos=["trabajador", "agente"], creado=_ahora())
    return almacen.guardar_solicitud(solicitud)


def listar_solicitudes(worker_id: str | None = None) -> list[dict]:
    fichas = almacen.fichas_base()
    orden = {"pendiente": 0, "respondida": 1}
    visibles = [_visible(s, fichas) for s in _enviadas(worker_id)]
    return sorted(visibles, key=lambda s: (orden.get(s["estado"], 9), s["creado"]), reverse=False)


def _enviadas(worker_id: str | None = None) -> list[dict]:
    return [s for s in almacen.listar_solicitudes(worker_id) if s["estado"] != "propuesta"]


def obtener_solicitud(solicitud_id: str) -> dict | None:
    solicitud = almacen.obtener_solicitud(solicitud_id)
    if solicitud is None:
        return None
    return _visible(solicitud, almacen.fichas_base())


def estadisticas() -> list[dict]:
    """Conteo de dudas y reclamos por área. Sirve para ver qué sector concentra consultas."""
    fichas = almacen.fichas_base()
    filas: dict[str, dict] = {}
    for ficha in fichas.values():
        area = ficha.get("area") or "Sin área"
        filas.setdefault(area, _fila(area))["trabajadores"] += 1
    for solicitud in _enviadas():
        area = _area_de(solicitud, fichas)
        fila = filas.setdefault(area, _fila(area))
        fila["solicitudes"] += 1
        fila["pendientes"] += solicitud["estado"] == "pendiente"
        if _tipo_de(solicitud) == "diferencia":
            fila["diferencias"] += 1
        else:
            fila["revisiones"] += 1
    return sorted(filas.values(), key=lambda f: (-f["solicitudes"], f["area"]))


def responder(solicitud_id: str, texto: str, autor: str = "") -> dict:
    if not str(texto).strip():
        raise ValueError("La respuesta para el trabajador no puede ir vacía.")
    solicitud = almacen.obtener_solicitud(solicitud_id)
    if solicitud is None or solicitud["estado"] == "propuesta":
        raise ValueError(f"No existe la solicitud {solicitud_id}.")
    solicitud.update(
        estado="respondida",
        respuesta=str(texto).strip(),
        respondido=_ahora(),
        respondido_por=(autor or "").strip() or None,
    )
    return almacen.guardar_solicitud(solicitud)


def _visible(solicitud: dict, fichas: dict) -> dict:
    visible = dict(solicitud)
    visible["area"] = _area_de(solicitud, fichas)
    visible["periodo"] = _periodo_de(solicitud)
    visible["tipo"] = _tipo_de(solicitud)
    visible["mensajes"] = _mensajes(solicitud)
    return visible


def _mensajes(solicitud: dict) -> list[dict]:
    """Lo que escribió el trabajador y lo que le contestó el agente, mensaje por mensaje. Las
    solicitudes antiguas solo guardaban la última respuesta del agente."""
    mensajes = [dict(m) for m in solicitud.get("mensajes")
                or [{"texto": solicitud["pregunta"], "creado": solicitud["creado"]}]]
    if not mensajes[-1].get("agente"):
        mensajes[-1]["agente"] = solicitud.get("resumen") or ""
    return mensajes


def _area_de(solicitud: dict, fichas: dict) -> str:
    if solicitud.get("area"):
        return solicitud["area"]
    return (fichas.get(solicitud["worker_id"]) or {}).get("area") or "Sin área"


def _tipo(worker_id: str, periodo: str | None, hallazgos: list[dict]) -> str:
    """Diferencia: el agente o el motor encontraron un monto mal calculado. Revisión: el trabajador
    solo pide que una persona lo mire."""
    if any(h.get("severidad") in ("revisar", "critico") for h in hallazgos):
        return "diferencia"
    caso = almacen.obtener_caso(f"{worker_id}-{periodo}") if periodo else None
    if caso and caso.get("hay_diferencias"):
        return "diferencia"
    return "revision"


def _tipo_de(solicitud: dict) -> str:
    return _tipo(solicitud["worker_id"], _periodo_de(solicitud), solicitud.get("hallazgos") or [])


def _fila(area: str) -> dict:
    return {"area": area, "trabajadores": 0, "solicitudes": 0, "diferencias": 0, "revisiones": 0,
            "pendientes": 0}


def _resumen(informe: dict | None, motivos: list[str]) -> str:
    if informe and str(informe.get("respuesta") or "").strip():
        texto = str(informe["respuesta"]).strip()
    elif "trabajador" in motivos:
        texto = "El trabajador pidió que una persona revise su caso. El agente no alcanzó a armar la respuesta."
    else:
        texto = "El agente marcó el caso para revisión y no dejó una respuesta."
    hallazgos = (informe or {}).get("hallazgos") or []
    if not hallazgos:
        return texto
    lineas = "\n".join(f"- {h.get('severidad', 'revisar')}: {h.get('descripcion', '')}" for h in hallazgos)
    return f"{texto}\n\nHallazgos:\n{lineas}"


def _periodo(worker_id: str, pregunta: str) -> str | None:
    """La liquidación de la que habla: 2026-09 o "septiembre" en el mensaje; si no, la más reciente,
    que es la que el agente revisa por defecto."""
    periodos = sorted({l["periodo"] for l in almacen.listar_liquidaciones(worker_id)})
    hallado = _PERIODO.search(pregunta or "")
    if hallado:
        return f"{hallado.group(1)}-{hallado.group(2)}"
    texto = (pregunta or "").lower()
    for numero, nombre in enumerate(_MESES, start=1):
        if re.search(rf"\b{nombre}\b", texto):
            del_mes = [p for p in periodos if p.endswith(f"-{numero:02d}")]
            if del_mes:
                return del_mes[-1]
    return periodos[-1] if periodos else None


def _periodo_de(solicitud: dict) -> str | None:
    return solicitud.get("periodo") or _periodo(solicitud["worker_id"], solicitud.get("pregunta") or "")


_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def _dia(instante: str) -> str:
    """Fecha local de Chile: dos mensajes de la misma tarde son el mismo día aunque cambie el día UTC."""
    return datetime.fromisoformat(instante).astimezone(_CHILE).date().isoformat()


_CHILE = ZoneInfo("America/Santiago")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
