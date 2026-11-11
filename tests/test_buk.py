"""Conector Buk contra la instancia de demostración: mismo cliente HTTP, mismo formato de la API."""
import json
import shutil
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

import fuentes.buk_demo as demo
from api.main import app
from fuentes.buk import ClienteBuk, ErrorBuk, ficha_desde_empleado, liquidacion_desde_buk
from harness.datos import obtener_liquidacion, obtener_trabajador
from rrhh import buk


@pytest.fixture(autouse=True)
def _sin_token(monkeypatch):
    monkeypatch.delenv("BUK_TOKEN", raising=False)


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from tests.conftest import autenticar_api

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "mock")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    with TestClient(app) as cliente:
        autenticar_api(cliente)
        yield cliente


def _empleado(employee_id: int) -> dict:
    return next(e for e in json.loads((demo.DIR_DEMO / "employees.json").read_text()) if e["id"] == employee_id)


def _settlement(employee_id: int) -> dict:
    return next(s for s in json.loads((demo.DIR_DEMO / "payroll_2026-10.json").read_text())
                if s["employee_id"] == employee_id)


def test_el_cliente_recorre_todas_las_paginas(monkeypatch):
    pedidas = []
    original = demo._responder

    def contar(request):
        pedidas.append(str(request.url))
        return original(request)

    monkeypatch.setattr(demo, "_responder", contar)
    cliente = demo.cliente_demo()
    cliente.tamano_pagina = 2
    empleados = cliente.empleados()
    assert [e["id"] for e in empleados] == [1201, 1202, 1203, 1204, 1205]
    assert len(pedidas) == 3
    assert "status=activo" in pedidas[-1] and "page=3" in pedidas[-1]


def test_un_token_rechazado_se_informa():
    http = httpx.Client(base_url=demo.BASE_DEMO, transport=httpx.MockTransport(demo._responder),
                        headers={"auth_token": "otro"})
    with pytest.raises(ErrorBuk, match="rechazó el token"):
        ClienteBuk(http).empleados()


def test_ficha_y_liquidacion_se_traducen_desde_buk():
    ficha = ficha_desde_empleado(_empleado(1204))
    assert ficha["code_sheet"] == "W004"
    assert (ficha["afp"], ficha["salud"], ficha["tipo_contrato"]) == ("Uno", "Fonasa", "plazo_fijo")
    assert ficha["fecha_termino"] == "2026-12-31"
    liq = liquidacion_desde_buk(_settlement(1204))
    assert liq["periodo"] == "2026-10"
    descuentos = {d["codigo"]: d for d in liq["descuentos_legales"]}
    assert descuentos["afp"]["institucion"] == "Uno"
    assert descuentos["afp"]["monto"] == 81065  # cotización obligatoria + comisión, dos líneas en Buk
    assert descuentos["seguro_cesantia"]["monto"] == 4650
    assert liq["liquido_a_pagar"] == _settlement(1204)["liquid_reach"]


def test_un_plazo_fijo_sin_linea_de_cesantia_queda_en_cero():
    s = _settlement(1204)
    s["lines_settlement"] = [l for l in s["lines_settlement"] if l["code"] != "afc"]
    descuentos = {d["codigo"]: d for d in liquidacion_desde_buk(s)["descuentos_legales"]}
    assert descuentos["seguro_cesantia"]["monto"] == 0


def test_sincronizar_da_de_alta_y_abre_los_casos(api):
    res = api.post("/cargas/buk", json={"periodo": "2026-10"})
    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["modo"] == "demo"
    assert (cuerpo["trabajadores"], cuerpo["liquidaciones"]) == (5, 5)
    assert cuerpo["altas"] == [{"worker_id": "W005", "nombre": "Javiera Muñoz Tapia"}]
    assert cuerpo["actualizados"] == []
    assert sorted(cuerpo["casos"]) == ["W004-2026-10", "W005-2026-10"]

    javiera = obtener_trabajador("W005")
    assert (javiera["afp"], javiera["colacion"], javiera["buk_id"]) == ("Capital", 45000, 1205)
    assert obtener_trabajador("W001")["rut"] == "16234871-K"
    assert obtener_liquidacion("W005", "2026-10")["descuentos_legales"][0]["institucion"] == "Modelo"
    caso = api.get("/casos/W005-2026-10").json()
    assert "Modelo" in next(l for l in caso["lineas"] if l["codigo"] == "afp")["causa_probable"]

    pdf = api.get("/trabajadores/W005/contrato.pdf")
    assert pdf.status_code == 200
    texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf.content)).pages)
    assert "Javiera" in texto and "Capital" in texto

    otra = api.post("/cargas/buk", json={"periodo": "2026-10"}).json()
    assert otra["altas"] == []
    assert len(api.get("/trabajadores").json()) == 5


def test_el_mismo_error_en_dos_meses_queda_agrupado(api):
    api.post("/cargas/buk", json={"periodo": "2026-10"})
    filas = {f["id"]: f for f in api.get("/bandeja").json()}
    grupo = filas["W004-2026-10"]["grupo"]
    assert grupo == filas["W004-2026-09"]["grupo"]
    assert grupo["periodos"] == ["2026-09", "2026-10"]
    assert grupo["casos"] == ["W004-2026-09", "W004-2026-10"]
    assert grupo["conceptos"] == ["Seguro de cesantía"]
    assert grupo["diferencia_total"] == 9300
    assert filas["W005-2026-10"]["grupo"] is None


def test_un_mes_sin_liquidaciones_solo_sincroniza_fichas(api):
    cuerpo = api.post("/cargas/buk", json={"periodo": "2026-11"}).json()
    assert cuerpo["liquidaciones"] == 0
    assert "no hay liquidaciones de noviembre 2026" in cuerpo["resumen"]


def test_un_cambio_de_afp_en_buk_actualiza_la_ficha(monkeypatch, tmp_path):
    copia = tmp_path / "buk_demo"
    shutil.copytree(demo.DIR_DEMO, copia)
    empleados = json.loads((copia / "employees.json").read_text())
    empleados[2]["pension_fund"] = "provida"
    (copia / "employees.json").write_text(json.dumps(empleados))
    monkeypatch.setattr(demo, "DIR_DEMO", copia)

    res = buk.sincronizar("2026-11")
    assert res["actualizados"] == [{"worker_id": "W003", "nombre": "Valentina Cortés Vera",
                                    "cambios": {"afp": ["Cuprum", "ProVida"]}}]
    assert obtener_trabajador("W003")["afp"] == "ProVida"


def test_el_webhook_pide_la_ficha_a_buk(api):
    alta = api.post("/webhooks/buk", json={"data": {"employee_id": 1205, "event_type": "employee_create",
                                                    "date": "2026-10-30T10:00:00-03:00"}})
    assert alta.status_code == 202
    assert alta.json()["alta"] is True and alta.json()["worker_id"] == "W005"
    otro = api.post("/webhooks/buk", json={"data": {"area_id": 3, "event_type": "area_create"}})
    assert otro.json()["procesado"] is False
