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
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "mock")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    with TestClient(app) as cliente:
        yield cliente


def _pdf(texto: str) -> bytes:
    return pdf_de_paginas([[texto]])


def test_salud_trabajadores_y_buk_sin_llamada(api):
    assert api.get("/salud").json()["ok"] is True
    assert "W001" in {t["worker_id"] for t in api.get("/trabajadores").json()}
    buk = api.post("/cargas/buk")
    assert buk.status_code == 503
    assert "configurado" in buk.json()["detail"]
    conectores = {c["nombre"]: c["disponible"] for c in api.get("/conectores").json()}
    assert conectores == {"Excel": True, "PDF liquidación": True, "PDF": True, "Buk": False}


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
