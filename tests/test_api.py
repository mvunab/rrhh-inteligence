"""La API es el punto de anclaje: datos, cargas, casos, agente e índice pasan por aquí."""
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from fuentes.excel import plantilla_bytes
from fuentes.pdf import pdf_de_paginas
from harness.runtime import ResultadoEjecucion
from harness.schemas import InformeLiquidacion

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from tests.conftest import autenticar_api

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "mock")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    with TestClient(app) as cliente:
        autenticar_api(cliente)
        yield cliente


def _pdf(texto: str) -> bytes:
    return pdf_de_paginas([[texto]])


def test_cada_trabajador_tiene_el_pdf_de_su_contrato(api):
    from io import BytesIO

    from pypdf import PdfReader

    for worker_id, nombre in (("W001", "Camila"), ("W002", "Tomás"), ("W003", "Valentina"), ("W004", "Diego")):
        res = api.get(f"/trabajadores/{worker_id}/contrato.pdf")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/pdf"
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(res.content)).pages)
        assert nombre in texto
        assert "CLÁUSULA" in texto
    assert api.get("/trabajadores/W999/contrato.pdf").status_code == 404


def test_documentos_contrato_incluye_texto_y_anexos(api):
    docs = api.get("/trabajadores/W001/documentos-contrato").json()
    assert docs
    assert docs[0]["tipo"] == "contrato"
    assert "Camila" in docs[0]["contenido"] or "CLÁUSULA" in docs[0]["contenido"]
    assert all("contenido" in d for d in docs)
    assert api.get("/trabajadores/W999/documentos-contrato").status_code == 404


def test_leer_contrato_propone_sin_persistir_y_confirmar_aplica(api):
    antes = api.get("/trabajadores/W001/documentos-contrato").json()
    texto = (
        "El empleador pagara al trabajador un sueldo base mensual de $1.200.000. "
        "El trabajador declara estar afiliado a la AFP ProVida y al sistema de salud Fonasa. "
        "El presente contrato es de duracion indefinida. "
        "Se pacta un bono de productividad mensual de $200.000 condicionado a la meta de 130 atenciones."
    )
    lectura = api.post(
        "/cargas/contrato/leer",
        data={"worker_id": "W001", "vigente_desde": "2026-11-01"},
        files={"archivo": ("c.pdf", _pdf(texto), "application/pdf")},
    )
    assert lectura.status_code == 200, lectura.text
    cuerpo = lectura.json()
    assert cuerpo["cambios_sugeridos"]["sueldo_base"] == 1_200_000
    assert cuerpo["cambios_sugeridos"]["afp"] == "ProVida"
    assert cuerpo["preview_descuentos"]["propuesta"]["imponible"] > 0
    assert api.get("/trabajadores/W001/documentos-contrato").json() == antes

    confirmado = api.post(
        "/cargas/pdf",
        data={
            "worker_id": "W001",
            "vigente_desde": "2026-11-01",
            "cambios": json.dumps(cuerpo["cambios_sugeridos"]),
        },
        files={"archivo": ("c.pdf", _pdf(texto), "application/pdf")},
    )
    assert confirmado.status_code == 200, confirmado.text
    vigente = {c["worker_id"]: c for c in confirmado.json()["contratos"]}["W001"]
    assert vigente["ficha"]["sueldo_base"] == 1_200_000
    assert vigente["ficha"]["afp"] == "ProVida"
    assert vigente["origen"] == "cargado"
    docs = api.get("/trabajadores/W001/documentos-contrato").json()
    assert any(d["tipo"] == "contrato" and d["origen"] == "cargado" for d in docs)


def test_leer_anexo_propone_afp_sin_guardar(api):
    antes = len(api.get("/trabajadores/W001/documentos-contrato").json())
    texto = "Anexo: el trabajador pasa a la AFP Modelo a contar de esta fecha."
    r = api.post(
        "/cargas/anexo/leer",
        data={"worker_id": "W001", "vigente_desde": "2026-10-15", "descripcion": "cambio AFP"},
        files={"archivo": ("a.pdf", _pdf(texto), "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cambios_sugeridos"]["afp"] == "Modelo"
    assert len(api.get("/trabajadores/W001/documentos-contrato").json()) == antes
    assert api.get("/trabajadores/W001").json()["ficha"]["afp"] == "Habitat"


def test_salud_trabajadores_y_conectores(api, monkeypatch):
    monkeypatch.delenv("BUK_TOKEN", raising=False)
    assert api.get("/salud").json()["ok"] is True
    assert "W001" in {t["worker_id"] for t in api.get("/trabajadores").json()}
    conectores = {c["nombre"]: (c["disponible"], c["modo"]) for c in api.get("/conectores").json()}
    assert conectores == {"Excel": (True, None), "PDF liquidación": (True, None), "PDF": (True, None),
                          "Buk": (True, "demo")}


def test_login_y_perfil_del_analista(api):
    yo = api.get("/auth/me").json()
    assert yo["email"] == "analista@clinica.local"
    assert yo["nombre"] == "Paula Soto"
    actualizado = api.put("/auth/me", json={"cargo": "Jefa de remuneraciones", "area": "RR.HH."}).json()
    assert actualizado["cargo"] == "Jefa de remuneraciones"
    with TestClient(app) as crudo:
        assert crudo.get("/bandeja").status_code == 401
        assert crudo.post("/auth/login", json={"email": "analista@clinica.local", "password": "mal"}).status_code == 401
    assert api.post("/cargas/buk", json={"periodo": "2026-13"}).status_code == 422


def test_excel_abre_caso_y_la_decision_queda_en_la_base(api):
    carga = api.post("/cargas/excel", files={"archivo": ("plantilla.xlsx", plantilla_bytes(), XLSX)})
    assert carga.status_code == 200
    assert "W001-2026-09" in carga.json()["resumen"]
    decision = api.post("/casos/W001-2026-09/decision",
                        json={"estado": "corregir", "nota": "Se pagó ProVida; el contrato dice Habitat."})
    assert decision.status_code == 200
    assert api.get("/casos/W001-2026-09").json()["nota"].startswith("Se pagó")
    assert api.post("/casos/W001-2026-09/decision", json={"estado": "mantener", "nota": "  "}).status_code == 422


def test_la_muestra_pdf_de_septiembre_abre_los_casos(api):
    archivo = api.get("/muestras/septiembre.pdf")
    assert archivo.content.startswith(b"%PDF")
    carga = api.post("/cargas/pdf-liquidacion", files={"archivo": ("sep.pdf", archivo.content, "application/pdf")})
    ids = {c["id"] for c in carga.json()["casos"]}
    assert {"W001-2026-09", "W003-2026-09", "W004-2026-09"} <= ids
    assert "W002-2026-09" not in ids


def test_la_base_trae_la_carga_inicial_y_marca_el_origen(api):
    liqs = api.get("/liquidaciones").json()
    assert {(l["worker_id"], l["periodo"]) for l in liqs} >= {("W001", "2026-08"), ("W001", "2026-09")}
    assert {l["origen"] for l in liqs} == {"base"}
    api.post("/cargas/excel", files={"archivo": ("p.xlsx", plantilla_bytes(), XLSX)})
    origen = {(l["worker_id"], l["periodo"]): l["origen"] for l in api.get("/liquidaciones").json()}
    assert origen[("W001", "2026-09")] == "excel"
    assert origen[("W001", "2026-08")] == "base"


def test_el_contrato_cargado_es_el_vigente_y_lleva_fecha(api):
    base = {c["worker_id"]: c for c in api.get("/contratos").json()}["W001"]
    assert base["origen"] == "base"
    assert base["vigente_desde"] == "2023-03-01"
    cargado = api.post("/cargas/pdf", data={"worker_id": "W001", "vigente_desde": "2026-10-01"},
                       files={"archivo": ("c.pdf", _pdf("Contrato nuevo"), "application/pdf")})
    assert cargado.status_code == 200
    assert "2026-10-01" in cargado.json()["resumen"]
    vigente = {c["worker_id"]: c for c in api.get("/contratos").json()}["W001"]
    assert (vigente["origen"], vigente["vigente_desde"]) == ("cargado", "2026-10-01")
    mala = api.post("/cargas/pdf", data={"worker_id": "W001", "vigente_desde": "1 de octubre"},
                    files={"archivo": ("c.pdf", _pdf("x"), "application/pdf")})
    assert mala.status_code == 400


def test_un_anexo_con_cambios_mueve_la_ficha_y_el_caso(api):
    api.post("/cargas/excel", files={"archivo": ("p.xlsx", plantilla_bytes(), XLSX)})
    r = api.post("/cargas/anexo",
                 data={"worker_id": "W001", "vigente_desde": "2026-09-01", "descripcion": "cambio de AFP",
                       "cambios": json.dumps({"afp": "ProVida"})},
                 files={"archivo": ("a.pdf", _pdf("Cambio a ProVida"), "application/pdf")})
    assert r.status_code == 200, r.text
    camila = {c["worker_id"]: c for c in r.json()["contratos"]}["W001"]
    assert camila["ficha"]["afp"] == "ProVida"
    assert camila["anexos"][0]["cambios"] == {"afp": "ProVida"}
    assert api.get("/trabajadores/W001", params={"periodo": "2026-08"}).json()["ficha"]["afp"] == "Habitat"
    assert api.get("/casos/W001-2026-09").json()["hay_diferencias"] is False

    otro = api.post("/cargas/anexo", data={"worker_id": "W001", "vigente_desde": "2026-09-01"},
                    files={"archivo": ("b.pdf", _pdf("Otro"), "application/pdf")})
    assert "anexo_W001_2026-09-01_2.md" in otro.json()["resumen"]
    malo = api.post("/cargas/anexo", data={"worker_id": "W001", "cambios": json.dumps({"afp": ""}) + "x"},
                    files={"archivo": ("x.pdf", _pdf("x"), "application/pdf")})
    assert malo.status_code == 400


def test_el_agente_invita_y_solo_llega_al_analista_si_el_trabajador_la_envia(api):
    res = api.post("/trabajadores/W001/consultas", json={"pregunta": "Explícame mi liquidación de 2026-09."})
    assert res.status_code == 200, res.text
    propuesta = res.json()["solicitud"]
    assert propuesta["estado"] == "propuesta"
    assert propuesta["periodo"] == "2026-09"
    assert propuesta["resumen"]
    assert api.get("/solicitudes").json() == []
    assert api.get("/trabajadores/W001/solicitudes").json() == []
    assert api.post(f"/trabajadores/W002/solicitudes/{propuesta['id']}/envio").status_code == 404

    enviada = api.post(f"/trabajadores/W001/solicitudes/{propuesta['id']}/envio")
    assert enviada.status_code == 200, enviada.text
    solicitud = enviada.json()
    assert solicitud["estado"] == "pendiente"
    assert solicitud["motivos"] == ["trabajador", "agente"]
    assert api.post(f"/trabajadores/W001/solicitudes/{propuesta['id']}/envio").status_code == 409
    listada = api.get("/solicitudes").json()[0]
    assert listada["id"] == solicitud["id"] and listada["tipo"] == "diferencia"

    vacia = api.post(f"/solicitudes/{solicitud['id']}/respuesta", json={"respuesta": "  "})
    assert vacia.status_code == 422
    enviada = api.post(f"/solicitudes/{solicitud['id']}/respuesta",
                       json={"respuesta": "La AFP del contrato es Habitat. Lo corregimos en octubre."})
    assert enviada.status_code == 200
    vista = api.get("/trabajadores/W001/solicitudes").json()[0]
    assert vista["estado"] == "respondida"
    assert "Habitat" in vista["respuesta"]


def test_el_pedido_en_el_mensaje_abre_solicitud_aunque_el_agente_no_la_marque(api, monkeypatch):
    from harness.runtime import ResultadoEjecucion
    from harness.schemas import InformeLiquidacion

    def falso(*_args, **_kwargs):
        informe = InformeLiquidacion(respuesta="Tu liquidación de septiembre cuadra con el contrato.",
                                     requiere_revision_rrhh=False, fuera_de_alcance=False)
        return ResultadoEjecucion(informe=informe, crudo="{}")

    monkeypatch.setattr("api.main.ejecutar", falso)
    res = api.post("/trabajadores/W002/consultas",
                   json={"pregunta": "Solicito que recursos humanos revise mi liquidación."})
    solicitud = res.json()["solicitud"]
    assert solicitud["motivos"] == ["trabajador"]
    assert solicitud["estado"] == "pendiente"
    assert "cuadra" in solicitud["resumen"]
    assert api.get("/solicitudes").json()[0]["tipo"] == "revision"
    assert api.post("/trabajadores/W002/consultas", json={"pregunta": "¿Cuánto es mi colación?"}).json()["solicitud"] is None

    otra = api.post("/trabajadores/W002/consultas",
                    json={"pregunta": "Quiero hablar con una persona de RR.HH. sobre septiembre."}).json()["solicitud"]
    assert otra["id"] == solicitud["id"]
    assert [m["texto"] for m in otra["mensajes"]] == [
        "Solicito que recursos humanos revise mi liquidación.",
        "Quiero hablar con una persona de RR.HH. sobre septiembre."]
    assert all("cuadra" in m["agente"] for m in otra["mensajes"])
    assert len(api.get("/solicitudes").json()) == 1


def test_la_bandeja_junta_la_diferencia_del_sistema_y_el_pedido_del_trabajador(api, monkeypatch):
    from harness.runtime import ResultadoEjecucion
    from harness.schemas import InformeLiquidacion

    def falso(*_args, **_kwargs):
        informe = InformeLiquidacion(respuesta="Tu liquidación cuadra.", requiere_revision_rrhh=False,
                                     fuera_de_alcance=False)
        return ResultadoEjecucion(informe=informe, crudo="{}")

    monkeypatch.setattr("api.main.ejecutar", falso)
    antes = {i["id"]: i for i in api.get("/bandeja").json()}
    assert antes["W003-2026-09"]["tipo"] == "diferencia" and antes["W003-2026-09"]["origen"] == ["sistema"]
    assert "W002-2026-09" not in antes

    api.post("/trabajadores/W003/consultas", json={"pregunta": "Solicito que RR.HH. revise mi liquidación."})
    api.post("/trabajadores/W002/consultas", json={"pregunta": "Solicito que RR.HH. revise mi liquidación."})
    despues = {i["id"]: i for i in api.get("/bandeja").json()}
    assert len(despues) == len(antes) + 1
    valentina = despues["W003-2026-09"]
    assert valentina["tipo"] == "diferencia" and valentina["origen"] == ["trabajador", "sistema"]
    assert len(valentina["solicitudes"]) == 1 and valentina["caso_id"] == "W003-2026-09"
    assert despues["W002-2026-09"]["tipo"] == "revision" and despues["W002-2026-09"]["diferencia_total"] == 0


def test_el_recalculo_propone_ajusta_y_emite_la_liquidacion_corregida(api):
    from io import BytesIO

    from pypdf import PdfReader

    assert api.post("/borradores", json={"worker_id": "W003", "periodo": "2026-13"}).status_code == 422
    assert api.post("/borradores", json={"worker_id": "W003", "periodo": "2025-01"}).status_code == 404
    creado = api.post("/borradores", json={"worker_id": "W003", "periodo": "2026-09"})
    assert creado.status_code == 201, creado.text
    borrador = creado.json()
    assert borrador["estado"] == "borrador"
    afp = next(d for d in borrador["propuesta"]["descuentos_legales"] if d["codigo"] == "afp")
    assert afp["base"] == borrador["parametros"]["tope_afp_salud"]
    conceptos = {a["concepto"]: a for a in borrador["ajustes"]}
    assert "tope imponible" in conceptos["AFP Cuprum"]["motivo"]
    assert conceptos["Líquido a pagar"]["diferencia"] > 0
    assert api.get("/liquidaciones").json()  # la emitida no cambia todavía
    assert api.get("/trabajadores/W003/liquidacion", params={"periodo": "2026-09"}).json()["liquido_a_pagar"] \
        == borrador["original"]["liquido_a_pagar"]

    pdf = api.get(f"/borradores/{borrador['id']}/pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    texto = "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert "LIQUIDACIÓN DE SUELDO" in texto and "BORRADOR" in texto and "Valentina" in texto

    imponibles = borrador["propuesta"]["haberes_imponibles"] + [{"concepto": "Bono especial", "monto": 100000}]
    negativo = api.put(f"/borradores/{borrador['id']}", json={
        "haberes_imponibles": [{"concepto": "Sueldo base", "monto": -1}]})
    assert negativo.status_code == 400
    ajustado = api.put(f"/borradores/{borrador['id']}", json={
        "haberes_imponibles": imponibles,
        "haberes_no_imponibles": borrador["propuesta"]["haberes_no_imponibles"],
        "nota": "Bono especial aprobado por jefatura.",
        "autor": "Paula Soto",
    }).json()
    especial = next(a for a in ajustado["ajustes"] if a["concepto"] == "Bono especial")
    assert especial["motivo"] == "Bono especial aprobado por jefatura." and especial["propuesto"] == 100000
    assert "tope imponible" in next(a for a in ajustado["ajustes"] if a["concepto"] == "AFP Cuprum")["motivo"]
    assert ajustado["version"] == borrador["version"] + 1 and ajustado["autor"] == "Paula Soto"

    diff = api.get(f"/borradores/{borrador['id']}/diff").json()
    assert diff["texto"].startswith("--- Liquidación emitida\n+++ Propuesta v2")
    assert any(l.startswith("+ Bono especial") for l in diff["texto"].splitlines())
    assert any(l.startswith("- AFP Cuprum") for l in diff["texto"].splitlines())
    assert any(l.startswith("  Sueldo base") for l in diff["texto"].splitlines())
    simple = diff["en_simple"]
    assert simple["titular"].startswith("Valentina recibiría") and "más" in simple["titular"]
    afp = next(p for p in simple["puntos"] if "AFP Cuprum" in p["texto"] and "baja" in p["texto"])
    assert afp["favorece_al_trabajador"] is True and "sueldo máximo" in afp["por_que"]
    especial = next(p for p in simple["puntos"] if "Bono especial" in p["texto"])
    assert especial["texto"].startswith("Se agrega") and "jefatura" in especial["por_que"]
    entre_versiones = api.get(f"/borradores/{borrador['id']}/diff", params={"base": "1"}).json()
    assert [c["concepto"] for c in entre_versiones["cambios"] if c["seccion"].startswith("Haberes")] == ["Bono especial"]
    assert api.get(f"/borradores/{borrador['id']}/diff", params={"base": "9"}).status_code == 404

    assert api.post(f"/borradores/{borrador['id']}/emision", json={"nota": "", "version": 2}).status_code == 422
    vieja = api.post(f"/borradores/{borrador['id']}/emision", json={"nota": "Tope.", "version": 1})
    assert vieja.status_code == 409 and "v2" in vieja.json()["detail"]
    emitido = api.post(f"/borradores/{borrador['id']}/emision",
                       json={"nota": "Se aplica tope imponible.", "version": 2, "autor": "Paula Soto"})
    assert emitido.status_code == 200, emitido.text
    assert emitido.json()["estado"] == "emitida"

    eventos = api.get(f"/borradores/{borrador['id']}/historial").json()
    assert [e["accion"] for e in eventos] == ["propuesta_generada", "propuesta_ajustada",
                                              "liquidacion_reemplazada", "liquidacion_emitida"]
    reemplazo = eventos[2]
    assert reemplazo["autor"] == "Paula Soto" and reemplazo["datos"]["version"] == 2
    assert reemplazo["datos"]["anterior"]["liquido_a_pagar"] == borrador["original"]["liquido_a_pagar"]
    assert eventos[3]["datos"]["liquido_anterior"] == borrador["original"]["liquido_a_pagar"]
    vigente = api.get("/trabajadores/W003/liquidacion", params={"periodo": "2026-09"}).json()
    assert vigente["liquido_a_pagar"] == ajustado["propuesta"]["liquido_a_pagar"]
    caso = api.get("/casos/W003-2026-09").json()
    assert caso["estado"] == "corregir" and caso["hay_diferencias"] is False
    origen = next(l for l in api.get("/liquidaciones").json() if l["worker_id"] == "W003" and l["periodo"] == "2026-09")
    assert origen["origen"] == "rectificada"
    assert api.post(f"/borradores/{borrador['id']}/emision", json={"nota": "otra vez", "version": 2}).status_code == 409
    texto = "\n".join(p.extract_text() for p in PdfReader(BytesIO(api.get(f"/borradores/{borrador['id']}/pdf").content)).pages)
    assert "BORRADOR" not in texto and "Liquidación rectificada" in texto


def test_el_recalculo_quita_la_cesantia_en_plazo_fijo(api):
    borrador = api.post("/borradores", json={"worker_id": "W004", "periodo": "2026-09"}).json()
    cesantia = next(a for a in borrador["ajustes"] if a["concepto"] == "Seguro de cesantía")
    assert cesantia["propuesto"] == 0 and "plazo fijo" in cesantia["motivo"]


def test_el_trabajador_consulta_al_agente_por_la_api(api):
    perfil = api.get("/trabajadores/W001").json()
    assert perfil["periodos"] == ["2026-08", "2026-09"]
    res = api.post("/trabajadores/W001/consultas", json={"pregunta": "Explícame mi liquidación de septiembre."})
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["ok"] is True
    assert cuerpo["informe"]["requiere_revision_rrhh"] is True
    assert any(p["herramienta"] == "calcular_descuentos_esperados" for p in cuerpo["traza"])
    assert api.post("/trabajadores/W999/consultas", json={"pregunta": "hola"}).status_code == 404


def test_config_e_indice_por_la_api_sin_exponer_la_clave(api, monkeypatch):
    monkeypatch.setenv("UNAB_API_KEY", "secreta")
    config = api.get("/agente/config").json()
    assert "unab_api_key" not in config
    assert config["unab_api_key_configurada"] is True
    vista = api.post("/agente/vista", json={"collection": "curso", "k": 7}).json()
    assert (vista["collection"], vista["k"]) == ("curso", 7)
    reconstruido = api.post("/indice/reconstruir", json={"collection": "curso"}).json()
    assert reconstruido["al_dia"] is True and reconstruido["fragmentos"] > 0


def test_la_explicacion_guarda_el_informe_sin_modelo(api, monkeypatch):
    api.post("/cargas/excel", files={"archivo": ("p.xlsx", plantilla_bytes(), XLSX)})

    def falso(*_args, **_kwargs):
        informe = InformeLiquidacion(respuesta="Diferencia de AFP.", requiere_revision_rrhh=True,
                                     fuera_de_alcance=False)
        return ResultadoEjecucion(informe=informe, crudo="{}")

    monkeypatch.setattr("rrhh.servicio.ejecutar", falso)
    respuesta = api.post("/casos/W001-2026-09/explicacion")
    assert respuesta.status_code == 200
    assert respuesta.json()["informe"]["respuesta"] == "Diferencia de AFP."
    assert respuesta.json()["estado"] == "pendiente"
