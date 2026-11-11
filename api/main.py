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

from api.deps import Analista
from fuentes import listar
from fuentes.buk import ErrorBuk
from fuentes.contratos import contratos_vigentes
from fuentes.excel import plantilla_bytes
from fuentes.lectura_contrato import proponer_desde_pdf
from fuentes.muestras import listar_muestras, obtener_muestra
from fuentes.protocolo import ErrorCarga
from harness import almacen, datos
from harness.auth import emitir_token, verificar_password
from harness.config import Settings
from harness.ingest import asegurar_indice, estado_indice
from harness.llm_factory import crear_embeddings, descripcion
from harness.runtime import ejecutar
from rrhh import buk, recalculo
from rrhh.bandeja import abrir_casos_faltantes, decidir, listar_bandeja, listar_casos, obtener_caso
from rrhh.pdf_contrato import pdf_de_contrato
from rrhh.pdf_liquidacion import pdf_borrador
from rrhh.solicitudes import (
    abrir_desde_consulta,
    enviar as enviar_solicitud,
    estadisticas as estadisticas_solicitudes,
    listar_solicitudes,
    obtener_solicitud,
    responder as responder_solicitud,
)
from rrhh.servicio import (
    explicar_caso,
    procesar_anexo,
    procesar_contrato,
    procesar_documento_compartido,
    procesar_excel,
    procesar_pdf_liquidacion,
)


@asynccontextmanager
async def _inicio(_app: FastAPI):
    almacen.motor()  # crea las tablas y siembra la base vacía
    almacen.completar_areas()
    almacen.asegurar_analistas()
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


class NuevoBorrador(BaseModel):
    worker_id: str = Field(min_length=1)
    periodo: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    autor: str = ""  # se ignora: el autor es el analista autenticado


class Haber(BaseModel):
    concepto: str
    monto: int


class AjusteBorrador(BaseModel):
    haberes_imponibles: list[Haber]
    haberes_no_imponibles: list[Haber] = []
    nota: str = ""
    autor: str = ""


class Emision(BaseModel):
    nota: str = Field(min_length=1)
    version: int = Field(ge=1, description="La versión que el analista revisó en el diff.")
    autor: str = ""


class CargaBuk(BaseModel):
    periodo: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class RespuestaAnalista(BaseModel):
    respuesta: str = Field(min_length=1)

    @field_validator("respuesta")
    @classmethod
    def respuesta_con_texto(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("La respuesta para el trabajador no puede ir vacía.")
        return limpio


class Login(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class PerfilActualizar(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    cargo: str | None = Field(None, max_length=120)
    area: str | None = Field(None, max_length=120)
    telefono: str | None = Field(None, max_length=40)


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


# ------------------------------------------------------------------ autenticación analistas
@app.post("/auth/login")
def login(cuerpo: Login) -> dict:
    fila = almacen.obtener_analista_por_email(cuerpo.email)
    if fila is None or not verificar_password(cuerpo.password, fila["password_hash"]):
        raise HTTPException(401, "Correo o contraseña incorrectos.")
    token = emitir_token(fila["id"])
    perfil = {k: v for k, v in fila.items() if k != "password_hash"}
    return {"token": token, "analista": perfil}


@app.post("/auth/logout")
def logout(_analista: Analista) -> dict:
    return {"ok": True}


@app.get("/auth/me")
def yo(analista: Analista) -> dict:
    return analista


@app.put("/auth/me")
def actualizar_yo(cuerpo: PerfilActualizar, analista: Analista) -> dict:
    return almacen.actualizar_analista(
        analista["id"],
        nombre=cuerpo.nombre,
        cargo=cuerpo.cargo,
        area=cuerpo.area,
        telefono=cuerpo.telefono,
    )


@app.put("/auth/me/avatar")
async def avatar_yo(analista: Analista, archivo: UploadFile = File(...)) -> dict:
    tipo = (archivo.content_type or "").lower()
    if tipo not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(400, "El avatar debe ser PNG, JPEG o WebP.")
    bruto = await archivo.read()
    if len(bruto) > 400_000:
        raise HTTPException(400, "El avatar no puede superar los 400 KB.")
    import base64
    data_url = f"data:{tipo};base64,{base64.b64encode(bruto).decode('ascii')}"
    return almacen.actualizar_analista(analista["id"], avatar=data_url)


@app.get("/conectores")
def conectores(_analista: Analista) -> list[dict]:
    return [{"nombre": c.nombre, "disponible": c.disponible, "detalle": c.detalle, "modo": getattr(c, "modo", None)}
            for c in listar()]


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
        {"worker_id": wid, "nombre": t["nombre"], "cargo": t["cargo"], "area": t.get("area") or "Sin área"}
        for wid, t in datos.cargar_trabajadores().items()
    ]


@app.get("/trabajadores/{worker_id}")
def trabajador(worker_id: str, periodo: str | None = None) -> dict:
    ficha = datos.obtener_trabajador(worker_id, periodo)
    if ficha is None:
        raise HTTPException(404, "No existe el trabajador.")
    return {"ficha": ficha, "periodos": datos.periodos_disponibles(worker_id)}


@app.get("/trabajadores/{worker_id}/contrato.pdf")
def pdf_contrato(worker_id: str) -> Response:
    if datos.obtener_trabajador(worker_id) is None:
        raise HTTPException(404, "No existe el trabajador.")
    texto = almacen.contenido_contrato(worker_id)
    if not texto:
        raise HTTPException(404, "Este trabajador no tiene contrato.")
    return Response(
        content=pdf_de_contrato(texto, worker_id), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="contrato_{worker_id}.pdf"'},
    )


@app.get("/trabajadores/{worker_id}/documentos-contrato")
def documentos_contrato(worker_id: str, _analista: Analista) -> list[dict]:
    """Contrato y anexos con el texto que ve el agente. Orden: contrato primero, luego anexos por fecha."""
    if datos.obtener_trabajador(worker_id) is None:
        raise HTTPException(404, "No existe el trabajador.")
    return almacen.documentos_de_contrato(worker_id, con_contenido=True)


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
    informe = res.informe.model_dump() if res.informe else None
    solicitud = abrir_desde_consulta(worker_id, cuerpo.pregunta, informe)
    return {
        "ok": res.ok,
        "informe": informe,
        "solicitud": solicitud,
        "crudo": res.crudo,
        "traza": res.traza,
        "errores": res.errores,
        "advertencias": res.advertencias,
        "reparado": res.reparado,
    }


@app.get("/trabajadores/{worker_id}/solicitudes")
def solicitudes_del_trabajador(worker_id: str) -> list[dict]:
    if datos.obtener_trabajador(worker_id) is None:
        raise HTTPException(404, "No existe el trabajador.")
    return listar_solicitudes(worker_id)


@app.post("/trabajadores/{worker_id}/solicitudes/{solicitud_id}/envio")
def envio_de_solicitud(worker_id: str, solicitud_id: str) -> dict:
    """El trabajador acepta la invitación del agente a pedir revisión."""
    try:
        return enviar_solicitud(worker_id, solicitud_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


# ------------------------------------------------------------------ RR.HH.: solicitudes de los mensajes
@app.get("/estadisticas/solicitudes")
def estadisticas(_analista: Analista) -> list[dict]:
    return estadisticas_solicitudes()


@app.get("/solicitudes")
def solicitudes(_analista: Analista) -> list[dict]:
    return listar_solicitudes()


@app.get("/solicitudes/{solicitud_id}")
def solicitud(solicitud_id: str, _analista: Analista) -> dict:
    encontrada = obtener_solicitud(solicitud_id)
    if encontrada is None:
        raise HTTPException(404, "No existe la solicitud.")
    return encontrada


@app.post("/solicitudes/{solicitud_id}/respuesta")
def respuesta_de_analista(solicitud_id: str, cuerpo: RespuestaAnalista, analista: Analista) -> dict:
    try:
        return responder_solicitud(solicitud_id, cuerpo.respuesta, analista["nombre"])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ RR.HH.: casos
@app.get("/bandeja")
def bandeja(_analista: Analista) -> list[dict]:
    """Una fila por liquidación en revisión: diferencias de cálculo y pedidos de revisión humana."""
    return listar_bandeja()


@app.get("/casos")
def casos(_analista: Analista) -> list[dict]:
    return listar_casos()


@app.get("/casos/{caso_id}")
def caso(caso_id: str, _analista: Analista) -> dict:
    encontrado = obtener_caso(caso_id)
    if encontrado is None:
        raise HTTPException(404, "No existe el caso.")
    return encontrado


@app.post("/casos/{caso_id}/decision")
def decision(caso_id: str, cuerpo: Decision, _analista: Analista) -> dict:
    try:
        return decidir(caso_id, cuerpo.estado, cuerpo.nota)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/casos/{caso_id}/explicacion")
def explicacion(caso_id: str, _analista: Analista) -> dict:
    try:
        return explicar_caso(caso_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# ------------------------------------------------------------------ RR.HH.: recálculo y borradores
@app.get("/borradores")
def borradores(_analista: Analista) -> list[dict]:
    return recalculo.listar()


@app.post("/borradores", status_code=201)
def nuevo_borrador(cuerpo: NuevoBorrador, analista: Analista) -> dict:
    """Recalcula la liquidación emitida y guarda la propuesta como borrador."""
    try:
        return recalculo.generar(cuerpo.worker_id, cuerpo.periodo, analista["nombre"])
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


def _borrador_o_404(borrador_id: str) -> dict:
    encontrado = recalculo.obtener(borrador_id)
    if encontrado is None:
        raise HTTPException(404, "No existe el borrador.")
    return encontrado


@app.get("/borradores/{borrador_id}")
def borrador(borrador_id: str, _analista: Analista) -> dict:
    return _borrador_o_404(borrador_id)


@app.put("/borradores/{borrador_id}")
def ajustar_borrador(borrador_id: str, cuerpo: AjusteBorrador, analista: Analista) -> dict:
    try:
        return recalculo.ajustar(
            borrador_id,
            [h.model_dump() for h in cuerpo.haberes_imponibles],
            [h.model_dump() for h in cuerpo.haberes_no_imponibles],
            cuerpo.nota,
            analista["nombre"],
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/borradores/{borrador_id}/pdf")
def pdf_de_borrador(borrador_id: str, _analista: Analista) -> Response:
    encontrado = _borrador_o_404(borrador_id)
    archivo = f"liquidacion_{encontrado['worker_id']}_{encontrado['periodo']}_{encontrado['estado']}.pdf"
    return Response(content=pdf_borrador(encontrado), media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={archivo}"})


@app.post("/borradores/{borrador_id}/emision")
def emitir_borrador(borrador_id: str, cuerpo: Emision, analista: Analista) -> dict:
    """La propuesta reemplaza a la liquidación vigente y el caso queda como corregido."""
    try:
        return recalculo.emitir(borrador_id, cuerpo.nota, cuerpo.version, analista["nombre"])
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/borradores/{borrador_id}/historial")
def historial_de_borrador(borrador_id: str, _analista: Analista) -> list[dict]:
    """Bitácora de la liquidación del periodo. Solo se agregan eventos; nada se borra."""
    try:
        return recalculo.historial(borrador_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/borradores/{borrador_id}/diff")
def diff_de_borrador(borrador_id: str, _analista: Analista, base: str = "emitida") -> dict:
    """Diff de la versión actual contra la liquidación emitida o contra una versión anterior (base=2)."""
    try:
        return recalculo.comparar(borrador_id, base)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ RR.HH.: datos
@app.get("/liquidaciones")
def liquidaciones(_analista: Analista) -> list[dict]:
    """Liquidaciones en el almacén. El periodo sale del documento; origen base es la carga inicial."""
    return almacen.resumen_liquidaciones()


@app.get("/contratos")
def contratos(_analista: Analista) -> list[dict]:
    return contratos_vigentes()


@app.get("/documentos-compartidos")
def docs_compartidos(_analista: Analista) -> list[dict]:
    return almacen.documentos_compartidos()


@app.get("/plantilla/liquidaciones.xlsx")
def plantilla(_analista: Analista) -> Response:
    return Response(
        content=plantilla_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_liquidaciones.xlsx"},
    )


@app.get("/muestras")
def muestras(_analista: Analista) -> list[dict]:
    return listar_muestras()


@app.get("/muestras/{muestra_id}")
def muestra(muestra_id: str, _analista: Analista) -> Response:
    try:
        contenido, media, archivo = obtener_muestra(muestra_id)
    except ErrorCarga as e:
        raise HTTPException(404, str(e)) from e
    return Response(content=contenido, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename={archivo}"})


# ------------------------------------------------------------------ RR.HH.: cargas
@app.post("/cargas/excel")
async def carga_excel(_analista: Analista, archivo: UploadFile = File(...)) -> dict:
    try:
        resumen = procesar_excel(await archivo.read())
    except ErrorCarga as e:
        raise _error_carga(e) from e
    return {"resumen": resumen, "casos": listar_casos()}


@app.post("/cargas/pdf-liquidacion")
async def carga_pdf_liquidacion(_analista: Analista, archivo: UploadFile = File(...)) -> dict:
    try:
        resumen = procesar_pdf_liquidacion(await archivo.read())
    except ErrorCarga as e:
        raise _error_carga(e) from e
    return {"resumen": resumen, "casos": listar_casos()}


@app.post("/cargas/contrato/leer")
async def leer_contrato(
    _analista: Analista,
    worker_id: str = Form(...),
    vigente_desde: str | None = Form(None),
    archivo: UploadFile = File(...),
) -> dict:
    """Propone campos de ficha desde el PDF. No guarda el documento ni cambia la ficha."""
    try:
        return proponer_desde_pdf(await archivo.read(), worker_id, "contrato", vigente_desde)
    except ErrorCarga as e:
        raise _error_carga(e) from e


@app.post("/cargas/anexo/leer")
async def leer_anexo(
    _analista: Analista,
    worker_id: str = Form(...),
    vigente_desde: str | None = Form(None),
    descripcion: str = Form(""),
    archivo: UploadFile = File(...),
) -> dict:
    """Propone campos de ficha desde el anexo. No guarda el documento ni cambia la ficha."""
    try:
        return proponer_desde_pdf(
            await archivo.read(), worker_id, "anexo", vigente_desde, descripcion)
    except ErrorCarga as e:
        raise _error_carga(e) from e


@app.post("/cargas/pdf")
async def carga_contrato(
    _analista: Analista,
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
    _analista: Analista,
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


@app.post("/cargas/documento-compartido")
async def carga_documento_compartido(
    _analista: Analista,
    doc_type: str = Form("otro"),
    descripcion: str = Form(""),
    archivo: UploadFile = File(...),
) -> dict:
    try:
        resumen = procesar_documento_compartido(
            await archivo.read(), archivo.filename or "documento.md", doc_type, descripcion)
    except ErrorCarga as e:
        raise _error_carga(e) from e
    return {"resumen": resumen, "documentos": almacen.documentos_compartidos()}


@app.post("/cargas/buk")
def carga_buk(cuerpo: CargaBuk, _analista: Analista) -> dict:
    """Trae de Buk los trabajadores activos y las liquidaciones del mes, y abre los casos."""
    try:
        return buk.sincronizar(cuerpo.periodo)
    except ErrorBuk as e:
        raise HTTPException(502, str(e)) from e
    except ErrorCarga as e:
        raise _error_carga(e) from e


@app.post("/webhooks/buk", status_code=202)
def webhook_buk(evento: dict) -> dict:
    """Aviso de Buk (alta, cambio o término de un trabajador). Se vuelve a pedir su ficha."""
    try:
        return buk.aplicar_evento(evento)
    except ErrorBuk as e:
        raise HTTPException(502, str(e)) from e
    except ErrorCarga as e:
        raise _error_carga(e) from e
