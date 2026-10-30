"""API de anclaje. Las dos interfaces y los orígenes hablan con este proceso, no con el motor.

Es el único proceso que abre el almacén (PostgreSQL) y el índice de Chroma.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import fields
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from fuentes import listar
from fuentes.buk import BukConector
from fuentes.contratos import contratos_vigentes
from fuentes.excel import plantilla_bytes
from fuentes.muestras import listar_muestras, obtener_muestra
from fuentes.protocolo import ErrorCarga
from harness import almacen, datos
from harness.config import Settings
from harness.ingest import asegurar_indice, estado_indice
from harness.llm_factory import crear_embeddings, descripcion
from harness.runtime import ejecutar
from rrhh.bandeja import abrir_casos_faltantes, decidir, listar_casos, obtener_caso
from rrhh.servicio import (
    explicar_caso,
    procesar_anexo,
    procesar_contrato,
    procesar_excel,
    procesar_pdf_liquidacion,
)


@asynccontextmanager
async def _inicio(_app: FastAPI):
    almacen.motor()  # crea las tablas y siembra la base vacía
    abrir_casos_faltantes()
    yield


app = FastAPI(title="Liquidaciones", version="0.2.0", lifespan=_inicio)


# ------------------------------------------------------------------ modelos
class Decision(BaseModel):
    estado: Literal["mantener", "corregir", "derivar"]
    nota: str = Field(min_length=1)

    @field_validator("nota")
    @classmethod
    def nota_con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("La decisión necesita una nota.")
        return limpio


class Ajustes(BaseModel):
    """Lo que la ventana de configuración cambia para una sesión. Vacío = valor del servidor."""
    llm_provider: Literal["ollama", "unab", "mock"] | None = None
    llm_model: str | None = None
    temperature: float | None = Field(None, ge=0, le=2)
    max_pasos: int | None = Field(None, ge=1, le=30)
    ollama_base_url: str | None = None
    unab_base_url: str | None = None
    unab_api_key: str | None = None
    embeddings_provider: Literal["ollama", "mock"] | None = None
    embedding_model: str | None = None
    chroma_dir: str | None = None
    collection: str | None = None
    k: int | None = Field(None, ge=1, le=20)

    def settings(self) -> Settings:
        cambios = {k: v for k, v in self.model_dump().items() if v is not None and v != ""}
        if "chroma_dir" in cambios:
            cambios["chroma_dir"] = Path(cambios["chroma_dir"])
        return Settings().con(**cambios)


class Consulta(BaseModel):
    pregunta: str = Field(min_length=1)
    ajustes: Ajustes = Ajustes()


def _error_carga(e: ErrorCarga) -> HTTPException:
    return HTTPException(400, str(e))


def _cambios(texto: str) -> dict:
    if not texto.strip():
        return {}
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError as e:
        raise HTTPException(400, "Los cambios deben venir como un objeto JSON.") from e
    if not isinstance(valor, dict):
        raise HTTPException(400, "Los cambios deben venir como un objeto JSON.")
    return valor


# ------------------------------------------------------------------ servicio
@app.get("/salud")
def salud() -> dict:
    return {"ok": True, "servicio": "liquidaciones"}


@app.get("/conectores")
def conectores() -> list[dict]:
    return [{"nombre": c.nombre, "disponible": c.disponible, "detalle": c.detalle} for c in listar()]


# ------------------------------------------------------------------ agente e índice
@app.get("/agente/config")
def config_agente() -> dict:
    """Configuración del servidor. La API key no sale de aquí."""
    s = Settings()
    valores = {f.name: getattr(s, f.name) for f in fields(s) if f.name != "unab_api_key"}
    valores["chroma_dir"] = str(s.chroma_dir)
    return {**valores, "unab_api_key_configurada": bool(s.unab_api_key), "descripcion": descripcion(s)}


@app.post("/agente/vista")
def vista_agente(ajustes: Ajustes) -> dict:
    s = ajustes.settings()
    return {"descripcion": descripcion(s), "collection": s.collection, "k": s.k, "indice": estado_indice(s)}


@app.post("/indice/reconstruir")
def reconstruir_indice(ajustes: Ajustes) -> dict:
    s = ajustes.settings()
    try:
        asegurar_indice(crear_embeddings(s), s, forzar=True)
    except Exception as e:  # noqa: BLE001 - p. ej. Ollama apagado
        raise HTTPException(502, f"No se pudo reconstruir el índice: {type(e).__name__}: {e}") from e
    return estado_indice(s)


# ------------------------------------------------------------------ trabajador
@app.get("/trabajadores")
def trabajadores() -> list[dict]:
    return [
        {"worker_id": wid, "nombre": t["nombre"], "cargo": t["cargo"]}
        for wid, t in datos.cargar_trabajadores().items()
    ]


@app.get("/trabajadores/{worker_id}")
def trabajador(worker_id: str, periodo: str | None = None) -> dict:
    ficha = datos.obtener_trabajador(worker_id, periodo)
    if ficha is None:
        raise HTTPException(404, "No existe el trabajador.")
    return {"ficha": ficha, "periodos": datos.periodos_disponibles(worker_id)}


@app.get("/trabajadores/{worker_id}/liquidacion")
def liquidacion(worker_id: str, periodo: str | None = None) -> dict:
    liq = datos.obtener_liquidacion(worker_id, periodo)
    if liq is None:
        raise HTTPException(404, "No hay liquidación para ese trabajador.")
    return liq


@app.post("/trabajadores/{worker_id}/consultas")
def consulta(worker_id: str, cuerpo: Consulta) -> dict:
    if datos.obtener_trabajador(worker_id) is None:
        raise HTTPException(404, "No existe el trabajador.")
    try:
        res = ejecutar(worker_id, cuerpo.pregunta, cuerpo.ajustes.settings())
    except Exception as e:  # noqa: BLE001 - proveedor caído, modelo inexistente, etc.
        raise HTTPException(502, f"No se pudo ejecutar el agente: {type(e).__name__}: {e}") from e
    return {
        "ok": res.ok,
        "informe": res.informe.model_dump() if res.informe else None,
        "crudo": res.crudo,
        "traza": res.traza,
        "errores": res.errores,
        "advertencias": res.advertencias,
        "reparado": res.reparado,
    }


# ------------------------------------------------------------------ RR.HH.: casos
@app.get("/casos")
def casos() -> list[dict]:
    return listar_casos()


@app.get("/casos/{caso_id}")
def caso(caso_id: str) -> dict:
    encontrado = obtener_caso(caso_id)
    if encontrado is None:
        raise HTTPException(404, "No existe el caso.")
    return encontrado


@app.post("/casos/{caso_id}/decision")
def decision(caso_id: str, cuerpo: Decision) -> dict:
    try:
        return decidir(caso_id, cuerpo.estado, cuerpo.nota)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/casos/{caso_id}/explicacion")
def explicacion(caso_id: str) -> dict:
    try:
        return explicar_caso(caso_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# ------------------------------------------------------------------ RR.HH.: datos
@app.get("/liquidaciones")
def liquidaciones() -> list[dict]:
    """Liquidaciones en el almacén. El periodo sale del documento; origen base es la carga inicial."""
    return almacen.resumen_liquidaciones()


@app.get("/contratos")
def contratos() -> list[dict]:
    return contratos_vigentes()


@app.get("/plantilla/liquidaciones.xlsx")
def plantilla() -> Response:
    return Response(
        content=plantilla_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_liquidaciones.xlsx"},
    )


@app.get("/muestras")
def muestras() -> list[dict]:
    return listar_muestras()


@app.get("/muestras/{muestra_id}")
def muestra(muestra_id: str) -> Response:
    try:
        contenido, media, archivo = obtener_muestra(muestra_id)
    except ErrorCarga as e:
        raise HTTPException(404, str(e)) from e
    return Response(content=contenido, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename={archivo}"})


# ------------------------------------------------------------------ RR.HH.: cargas
@app.post("/cargas/excel")
async def carga_excel(archivo: UploadFile = File(...)) -> dict:
    try:
        resumen = procesar_excel(await archivo.read())
    except ErrorCarga as e:
        raise _error_carga(e) from e
    return {"resumen": resumen, "casos": listar_casos()}


@app.post("/cargas/pdf-liquidacion")
async def carga_pdf_liquidacion(archivo: UploadFile = File(...)) -> dict:
    try:
        resumen = procesar_pdf_liquidacion(await archivo.read())
    except ErrorCarga as e:
        raise _error_carga(e) from e
    return {"resumen": resumen, "casos": listar_casos()}


@app.post("/cargas/pdf")
async def carga_contrato(
    worker_id: str = Form(...),
    vigente_desde: str | None = Form(None),
    cambios: str = Form(""),
    archivo: UploadFile = File(...),
) -> dict:
    try:
        resumen = procesar_contrato(await archivo.read(), worker_id, vigente_desde, _cambios(cambios))
    except ErrorCarga as e:
        raise _error_carga(e) from e
    return {"resumen": resumen, "contratos": contratos_vigentes()}


@app.post("/cargas/anexo")
async def carga_anexo(
    worker_id: str = Form(...),
    vigente_desde: str | None = Form(None),
    descripcion: str = Form(""),
    cambios: str = Form(""),
    archivo: UploadFile = File(...),
) -> dict:
    try:
        resumen = procesar_anexo(await archivo.read(), worker_id, vigente_desde, descripcion, _cambios(cambios))
    except ErrorCarga as e:
        raise _error_carga(e) from e
    return {"resumen": resumen, "contratos": contratos_vigentes()}


@app.post("/cargas/buk")
def carga_buk() -> dict:
    try:
        BukConector().cargar()
    except ErrorCarga as e:
        raise HTTPException(503, str(e)) from e
    return {"resumen": "Buk cargó datos."}
