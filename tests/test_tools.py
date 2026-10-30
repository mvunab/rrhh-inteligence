import json

import pytest

from harness.tools import crear_herramientas


@pytest.fixture()
def herramientas(indice, settings_mock):
    def _crear(wid):
        return {t.name: t for t in crear_herramientas(wid, indice, settings_mock)}
    return _crear


def test_ninguna_tool_recibe_el_id_del_trabajador(herramientas):
    for t in herramientas("W001").values():
        assert "worker_id" not in t.args, f"{t.name} expone worker_id al LLM"


def test_obtener_liquidacion_solo_entrega_los_datos_propios(herramientas):
    r = json.loads(herramientas("W001")["obtener_liquidacion"].invoke({}))
    assert r["trabajador"]["nombre"].startswith("Camila")
    assert r["liquidacion"]["worker_id"] == "W001" and r["liquidacion"]["periodo"] == "2026-09"
    assert "Tomás" not in json.dumps(r, ensure_ascii=False)


def test_periodo_invalido_o_inexistente(herramientas):
    r = json.loads(herramientas("W001")["obtener_liquidacion"].invoke({"periodo": "2030-01"}))
    assert "error" in r and r["periodos_disponibles"] == ["2026-08", "2026-09"]
    # un formato raro cae al periodo mas reciente
    r2 = json.loads(herramientas("W001")["obtener_liquidacion"].invoke({"periodo": "septiembre"}))
    assert r2["liquidacion"]["periodo"] == "2026-09"


def test_calcular_descuentos_esperados(herramientas, errores_sembrados):
    for wid in ("W001", "W002", "W003", "W004"):
        r = json.loads(herramientas(wid)["calcular_descuentos_esperados"].invoke({}))
        con_dif = sorted(f["codigo"] for f in r["lineas"] if f["estado"] == "diferencia")
        assert con_dif == sorted(errores_sembrados[wid]["lineas_con_diferencia"])
        assert r["periodo"] == "2026-09"


def test_consultar_parametros(herramientas):
    p = json.loads(herramientas("W002")["consultar_parametros"].invoke({}))
    assert p["topes_pesos"]["afp_salud"] == 3_695_148
    assert p["uf"]["fuente"] and p["fecha_verificacion"]


def test_buscar_en_documentos_devuelve_contenido_y_artefacto(herramientas):
    msg = herramientas("W001")["buscar_en_documentos"].invoke(
        {"name": "buscar_en_documentos", "args": {"consulta": "bono de productividad"},
         "id": "x", "type": "tool_call"})
    assert "[fuente: " in msg.content and msg.artifact
    assert all(not a.startswith("contrato_W002") for a in msg.artifact)
