import json
import os
import shutil
from pathlib import Path

import pytest

from harness import almacen
from harness.calculos import cargar_parametros
from harness.config import Settings
from harness.ingest import construir_indice
from harness.llm_factory import crear_embeddings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _base_sembrada(tmp_path_factory):
    """Una base SQLite sembrada con data/, igual a la carga inicial de PostgreSQL."""
    ruta = tmp_path_factory.mktemp("base") / "plantilla.db"
    anterior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{ruta}"
    almacen.motor().dispose()
    yield ruta
    if anterior is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = anterior


@pytest.fixture(autouse=True)
def base(_base_sembrada, tmp_path, monkeypatch):
    """Cada test trabaja sobre su copia: lo que carga o decide no llega al siguiente."""
    copia = tmp_path / "base.db"
    shutil.copy(_base_sembrada, copia)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{copia}")
    yield copia
    almacen.motor().dispose()


def autenticar_api(cliente):
    """Login del analista demo; deja el Bearer en el TestClient."""
    from harness.auth import email_demo, password_demo

    almacen.asegurar_analistas()
    res = cliente.post("/auth/login", json={"email": email_demo(), "password": password_demo()})
    assert res.status_code == 200, res.text
    cliente.headers["Authorization"] = f"Bearer {res.json()['token']}"
    return res.json()["analista"]


@pytest.fixture(scope="session")
def params():
    return cargar_parametros()


@pytest.fixture(scope="session")
def errores_sembrados():
    return json.loads((FIXTURES / "errores_sembrados.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def settings_mock(tmp_path_factory):
    return Settings.modo_mock().con(chroma_dir=tmp_path_factory.mktemp("chroma"))


@pytest.fixture(scope="session")
def indice(settings_mock, _base_sembrada):
    """Indice Chroma real (persistente en un tmp) con embeddings simulados."""
    return construir_indice(crear_embeddings(settings_mock), settings_mock)
