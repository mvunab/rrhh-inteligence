"""Cliente HTTP de la API. Lo usan la app del trabajador y el centro de RR.HH.; ninguna abre el motor."""
from __future__ import annotations

import json
import os

import httpx

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_cliente_fijo: httpx.Client | None = None


class ErrorApi(Exception):
    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


def base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")


def usar_cliente(cliente: httpx.Client | None) -> None:
    """Fija el cliente HTTP (los tests pasan el TestClient de la API). None vuelve a API_BASE_URL."""
    global _cliente_fijo
    _cliente_fijo = cliente


def _detalle(respuesta: httpx.Response) -> str:
    try:
        cuerpo = respuesta.json()
    except Exception:  # noqa: BLE001
        cuerpo = {}
    detalle = cuerpo.get("detail") if isinstance(cuerpo, dict) else None
    if isinstance(detalle, list):
        return "; ".join(str(item.get("msg", item)) for item in detalle)
    return str(detalle or respuesta.text or respuesta.status_code)


def _pedir(metodo: str, ruta: str, *, timeout: float = 30, **kwargs) -> httpx.Response:
    try:
        if _cliente_fijo is not None:
            respuesta = _cliente_fijo.request(metodo, ruta, timeout=timeout, **kwargs)
        else:
            respuesta = httpx.request(metodo, f"{base_url()}{ruta}", timeout=timeout, **kwargs)
    except httpx.HTTPError as e:
        raise ErrorApi(f"La API no responde en {base_url()}: {e}") from e
    if respuesta.status_code >= 400:
        raise ErrorApi(_detalle(respuesta))
    return respuesta


# ------------------------------------------------------------------ servicio
def conectores() -> list[dict]:
    return _pedir("GET", "/conectores").json()


# ------------------------------------------------------------------ agente e índice
def config_agente() -> dict:
    return _pedir("GET", "/agente/config").json()


def vista_agente(ajustes: dict | None = None) -> dict:
    return _pedir("POST", "/agente/vista", json=ajustes or {}).json()


def reconstruir_indice(ajustes: dict | None = None) -> dict:
    return _pedir("POST", "/indice/reconstruir", json=ajustes or {}, timeout=300).json()


# ------------------------------------------------------------------ trabajador
def trabajadores() -> list[dict]:
    return _pedir("GET", "/trabajadores").json()


def trabajador(worker_id: str, periodo: str | None = None) -> dict:
    """Ficha vigente al cierre del periodo (sin periodo, hoy) y los periodos con liquidación."""
    params = {"periodo": periodo} if periodo else None
    return _pedir("GET", f"/trabajadores/{worker_id}", params=params).json()


def liquidacion(worker_id: str, periodo: str | None = None) -> dict:
    params = {"periodo": periodo} if periodo else None
    return _pedir("GET", f"/trabajadores/{worker_id}/liquidacion", params=params).json()


def consultar(worker_id: str, pregunta: str, ajustes: dict | None = None) -> dict:
    return _pedir("POST", f"/trabajadores/{worker_id}/consultas",
                  json={"pregunta": pregunta, "ajustes": ajustes or {}}, timeout=300).json()


def solicitudes_trabajador(worker_id: str) -> list[dict]:
    return _pedir("GET", f"/trabajadores/{worker_id}/solicitudes").json()


def enviar_solicitud(worker_id: str, solicitud_id: str) -> dict:
    return _pedir("POST", f"/trabajadores/{worker_id}/solicitudes/{solicitud_id}/envio").json()


# ------------------------------------------------------------------ RR.HH.
def bandeja() -> list[dict]:
    return _pedir("GET", "/bandeja").json()


def casos() -> list[dict]:
    return _pedir("GET", "/casos").json()


def caso(caso_id: str) -> dict:
    return _pedir("GET", f"/casos/{caso_id}").json()


def decidir(caso_id: str, estado: str, nota: str) -> dict:
    return _pedir("POST", f"/casos/{caso_id}/decision", json={"estado": estado, "nota": nota}).json()


def explicar(caso_id: str) -> dict:
    return _pedir("POST", f"/casos/{caso_id}/explicacion", timeout=300).json()


def solicitudes() -> list[dict]:
    return _pedir("GET", "/solicitudes").json()


def estadisticas_solicitudes() -> list[dict]:
    return _pedir("GET", "/estadisticas/solicitudes").json()


def solicitud(solicitud_id: str) -> dict:
    return _pedir("GET", f"/solicitudes/{solicitud_id}").json()


def responder_solicitud(solicitud_id: str, respuesta: str) -> dict:
    return _pedir("POST", f"/solicitudes/{solicitud_id}/respuesta", json={"respuesta": respuesta}).json()


def borradores() -> list[dict]:
    return _pedir("GET", "/borradores").json()


def generar_borrador(worker_id: str, periodo: str) -> dict:
    return _pedir("POST", "/borradores", json={"worker_id": worker_id, "periodo": periodo}).json()


def ajustar_borrador(borrador_id: str, haberes_imponibles: list[dict], haberes_no_imponibles: list[dict],
                     nota: str = "") -> dict:
    return _pedir("PUT", f"/borradores/{borrador_id}", json={
        "haberes_imponibles": haberes_imponibles, "haberes_no_imponibles": haberes_no_imponibles, "nota": nota,
    }).json()


def pdf_borrador(borrador_id: str) -> bytes:
    return _pedir("GET", f"/borradores/{borrador_id}/pdf").content


def emitir_borrador(borrador_id: str, nota: str) -> dict:
    return _pedir("POST", f"/borradores/{borrador_id}/emision", json={"nota": nota}).json()


def plantilla() -> bytes:
    return _pedir("GET", "/plantilla/liquidaciones.xlsx").content


def muestras() -> list[dict]:
    return _pedir("GET", "/muestras").json()


def muestra(muestra_id: str) -> bytes:
    return _pedir("GET", f"/muestras/{muestra_id}").content


def liquidaciones() -> list[dict]:
    return _pedir("GET", "/liquidaciones").json()


def contratos() -> list[dict]:
    return _pedir("GET", "/contratos").json()


def cargar_excel(nombre: str, contenido: bytes) -> dict:
    return _pedir("POST", "/cargas/excel", files={"archivo": (nombre, contenido, XLSX)}).json()


def cargar_pdf_liquidacion(nombre: str, contenido: bytes) -> dict:
    return _pedir("POST", "/cargas/pdf-liquidacion", files={"archivo": (nombre, contenido, "application/pdf")}).json()


def cargar_contrato(worker_id: str, nombre: str, contenido: bytes, vigente_desde: str | None = None,
                    cambios: dict | None = None) -> dict:
    return _cargar_documento("/cargas/pdf", worker_id, nombre, contenido, vigente_desde, cambios)


def cargar_anexo(worker_id: str, nombre: str, contenido: bytes, vigente_desde: str | None = None,
                 descripcion: str = "", cambios: dict | None = None) -> dict:
    return _cargar_documento("/cargas/anexo", worker_id, nombre, contenido, vigente_desde, cambios,
                             descripcion=descripcion)


def _cargar_documento(ruta: str, worker_id: str, nombre: str, contenido: bytes,
                      vigente_desde: str | None, cambios: dict | None, **extra: str) -> dict:
    datos = {"worker_id": worker_id, "cambios": json.dumps(cambios or {}), **extra}
    if vigente_desde:
        datos["vigente_desde"] = vigente_desde
    return _pedir("POST", ruta, data=datos, files={"archivo": (nombre, contenido, "application/pdf")}).json()
