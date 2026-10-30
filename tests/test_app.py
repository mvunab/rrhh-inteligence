"""Prueba headless de la interfaz Streamlit (streamlit.testing), 100% offline con el mock.

La app habla con la API; aquí la API corre en el mismo proceso (TestClient).
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import cliente
from api.main import app as api

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "mock")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    with TestClient(api) as http:
        cliente.usar_cliente(http)
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        assert not at.exception, at.exception
        yield at
    cliente.usar_cliente(None)


def _texto(at) -> str:
    partes = [m.value for m in at.markdown] + [w.value for w in at.warning] + [e.value for e in at.error] \
             + [i.value for i in at.info] + [s.value for s in at.success]
    return "\n".join(partes)


def test_la_app_carga_con_la_liquidacion_de_la_primera_trabajadora(app):
    assert app.title[0].value.endswith("Asistente de liquidaciones")
    assert any("Líquido a pagar" in m.label for m in app.metric)
    assert any("$1.076.360" in m.value for m in app.metric)  # Camila, septiembre


def test_pregunta_rapida_muestra_hallazgo_de_afp(app):
    next(b for b in app.button if b.key == "rapida_0").click()
    app.run()
    assert not app.exception, app.exception
    texto = _texto(app)
    assert "Requiere revisión de RR.HH." in texto
    assert "ProVida" in texto and "Habitat" in texto


def test_guardrail_en_la_interfaz(app):
    next(b for b in app.button if b.key == "rapida_4").click()
    app.run()
    texto = _texto(app)
    assert "Fuera de alcance" in texto and "700.000" not in texto


def test_la_ventana_de_configuracion_aplica_el_agente_y_la_base_rag(app):
    app.sidebar.button(key="abrir_config").click().run()
    assert not app.exception, app.exception
    assert any(s.value == "Agente" for s in app.subheader)
    assert any(s.value == "Base RAG" for s in app.subheader)
    next(n for n in app.number_input if n.key == "dlg_k").set_value(7).run()
    next(n for n in app.number_input if n.key == "dlg_max_pasos").set_value(12).run()
    next(t for t in app.text_input if t.key == "dlg_collection").set_value("curso_cinf110").run()
    next(b for b in app.button if b.key == "aplicar_config").click().run()
    assert not app.exception, app.exception
    texto = _texto(app)
    assert "Configuración aplicada." in texto
    assert "RAG: curso_cinf110 · k=7" in texto
    assert app.session_state["cfg_ui"]["max_pasos"] == 12
    assert app.session_state["cfg_ui"]["k"] == 7


def test_cambiar_de_trabajador_cambia_la_liquidacion(app):
    app.sidebar.selectbox[0].set_value("W002").run()
    assert any("$882.745" in m.value for m in app.metric)  # Tomas
    next(b for b in app.button if b.key == "rapida_0").click()
    app.run()
    assert "Sin diferencias que revisar" in _texto(app)
