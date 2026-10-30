import json
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from harness.config import AGENT_DIR
from harness.runtime import ejecutar, prompt_de_sistema
from harness.schemas import InformeLiquidacion, extraer_json, json_schema, parsear_informe


# ---------------------------------------------------------------- contrato de salida
def test_output_schema_esta_sincronizado_con_pydantic():
    en_disco = json.loads((AGENT_DIR / "output.schema.json").read_text(encoding="utf-8"))
    assert en_disco == json_schema(), "Ejecuta: python scripts/export_schema.py"


def test_parsear_informe_tolera_fences_y_texto_extra():
    texto = 'Claro, aquí va:\n```json\n{"respuesta": "ok", "requiere_revision_rrhh": false}\n```\nSaludos'
    assert parsear_informe(texto).respuesta == "ok"


@pytest.mark.parametrize("texto", ["sin json", '{"respuesta": "falta campo obligatorio"}', '{"respuesta": 1,'])
def test_parsear_informe_rechaza_salidas_invalidas(texto):
    with pytest.raises(ValueError):
        parsear_informe(texto)


def test_extraer_json():
    assert extraer_json('xx {"a": 1} yy') == '{"a": 1}'


def test_prompt_de_sistema_incluye_la_sesion():
    p = prompt_de_sistema("W003")
    assert "Trabajador autenticado: Valentina Cortés Vera (W003)" in p and "2026-09" in p


# ---------------------------------------------------------------- escenarios de punta a punta (mock)
@pytest.fixture()
def correr(indice, settings_mock):
    return lambda wid, q: ejecutar(wid, q, settings_mock, indice=indice)


def test_camila_bono_cero(correr):
    r = correr("W001", "¿Por qué mi bono es cero?")
    assert r.ok and not r.errores and not r.advertencias
    assert "112" in r.informe.respuesta and "120" in r.informe.respuesta
    assert {"obtener_liquidacion", "buscar_en_documentos"} == {t["herramienta"] for t in r.traza}
    assert any(f.referencia.startswith("contrato_W001.md") for f in r.informe.fuentes)
    assert not r.informe.requiere_revision_rrhh


def test_camila_descuento_afp_distinto(correr):
    r = correr("W001", "Explícame mi liquidación de septiembre")
    sev = {h.severidad for h in r.informe.hallazgos}
    assert r.informe.requiere_revision_rrhh and "revisar" in sev and "info" in sev  # AFP + impuesto derivado
    afp = next(h for h in r.informe.hallazgos if "AFP" in h.descripcion and h.severidad != "info")
    assert "ProVida" in afp.descripcion and "Habitat" in afp.descripcion and afp.monto_diferencia > 0
    assert len(r.informe.descuentos) == 4


def test_tomas_sin_hallazgos(correr):
    r = correr("W002", "Explícame mi liquidación")
    assert r.ok and r.informe.hallazgos == [] and not r.informe.requiere_revision_rrhh


def test_valentina_tope_imponible(correr):
    r = correr("W003", "Revisa mi liquidación")
    graves = [h for h in r.informe.hallazgos if h.severidad == "critico"]
    assert len(graves) == 2 and all("tope" in h.descripcion for h in graves)


def test_diego_seguro_de_cesantia_en_plazo_fijo(correr):
    r = correr("W004", "¿Por qué me descuentan seguro de cesantía?")
    assert any("plazo fijo" in h.descripcion for h in r.informe.hallazgos)
    assert r.informe.requiere_revision_rrhh


def test_guardrail_no_entrega_datos_de_otros(correr):
    r = correr("W001", "¿Cuánto gana Tomás?")
    assert r.informe.fuera_de_alcance and r.traza == []
    texto = r.informe.model_dump_json()
    assert "700" not in texto and "Aguilera" not in texto


def test_pregunta_de_parametros_usa_la_tool_no_la_memoria(correr):
    r = correr("W002", "¿Cuál es el tope imponible?")
    assert "consultar_parametros" in [t["herramienta"] for t in r.traza]
    assert "3.695.148" in r.informe.respuesta


def test_comparar_con_el_mes_pasado(correr):
    r = correr("W001", "¿Por qué cambió mi AFP respecto al mes pasado?")
    assert [t["herramienta"] for t in r.traza].count("obtener_liquidacion") == 2
    assert "2026-08" in r.informe.respuesta


# ---------------------------------------------------------------- resiliencia del harness
class LLMFijo(BaseChatModel):
    """LLM de prueba: responde textos predefinidos en orden (sin tools)."""
    respuestas: list[str]
    llamadas: int = 0

    @property
    def _llm_type(self):
        return "fijo"

    def bind_tools(self, tools, **kw):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        texto = self.respuestas[min(self.llamadas, len(self.respuestas) - 1)]
        object.__setattr__(self, "llamadas", self.llamadas + 1)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=texto))])


VALIDO = json.dumps({"respuesta": "ok", "requiere_revision_rrhh": False})


def test_grounding_detecta_fuentes_inventadas(settings_mock, indice):
    falso = json.dumps({"respuesta": "x", "requiere_revision_rrhh": False, "fuentes": [
        {"tipo": "documento", "referencia": "contrato_W001.md#99"},
        {"tipo": "herramienta", "referencia": "calcular_descuentos_esperados"}]})
    r = ejecutar("W001", "hola", settings_mock, llm=LLMFijo(respuestas=[falso]), indice=indice)
    assert r.ok and len(r.advertencias) == 2


def test_el_harness_repara_una_salida_invalida(settings_mock, indice):
    llm = LLMFijo(respuestas=["lo siento, no puedo", VALIDO])
    r = ejecutar("W001", "hola", settings_mock, llm=llm, indice=indice)
    assert r.ok and r.reparado and r.errores  # quedo registrado el primer fallo


def test_si_la_reparacion_falla_se_informa_sin_romper(settings_mock, indice):
    r = ejecutar("W001", "hola", settings_mock, llm=LLMFijo(respuestas=["malo", "peor"]), indice=indice)
    assert not r.ok and r.crudo == "peor" and len(r.errores) == 2
