from pathlib import Path

import pytest

from harness import ingest
from harness.config import DOCS_DIR, Settings
from harness.ingest import TODOS_LOS_TRABAJADORES, asegurar_indice, cargar_documentos, trocear
from harness.llm_factory import crear_embeddings
from harness.retriever import buscar, filtro_para


@pytest.fixture(scope="module")
def chunks():
    return trocear(cargar_documentos())


def test_se_cargan_todos_los_documentos():
    docs = cargar_documentos()
    assert len(docs) == 7  # 4 contratos + reglamento + politica + normativa
    assert {d.metadata["doc_type"] for d in docs} == {"contrato", "reglamento", "politica", "normativa"}


def test_chunking_respeta_clausulas(chunks):
    contrato = [c for c in chunks if c.metadata["source"] == "contrato_W001.md"]
    secciones = [c.metadata["seccion"] for c in contrato]
    assert len(contrato) == 11                       # 10 clausulas + anexo
    assert any(s.startswith("ANEXO") for s in secciones)
    assert all(c.page_content.startswith("Contrato de trabajo de Camila") for c in contrato)  # contexto


def test_metadata_y_ids_unicos(chunks):
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        assert {"source", "doc_type", "worker_id", "seccion", "chunk_id"} <= set(c.metadata)
        if c.metadata["doc_type"] == "contrato":
            assert c.metadata["worker_id"] in {"W001", "W002", "W003", "W004"}
        else:
            assert c.metadata["worker_id"] == TODOS_LOS_TRABAJADORES


def test_el_indice_se_persiste_y_se_reutiliza(tmp_path, monkeypatch):
    cfg = Settings.modo_mock().con(chroma_dir=tmp_path)
    emb = crear_embeddings(cfg)
    idx = asegurar_indice(emb, cfg)
    n = idx._collection.count()
    assert n > 40
    info = ingest.estado_indice(cfg)
    assert info["existe"] and info["al_dia"] and info["fragmentos"] == n and info["documentos"] == 7
    # segunda llamada: NO debe reconstruir
    monkeypatch.setattr(ingest, "construir_indice", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconstruyo")))
    assert asegurar_indice(emb, cfg)._collection.count() == n


def test_cambiar_el_modelo_de_embeddings_fuerza_reindexar(tmp_path):
    base = Settings.modo_mock().con(chroma_dir=tmp_path)
    asegurar_indice(crear_embeddings(base), base)
    otro = base.con(embedding_model="otro-modelo")
    assert ingest._firma(base, DOCS_DIR) != ingest._firma(otro, DOCS_DIR)


# ---------------------------------------------------------------- recuperacion y privacidad
@pytest.mark.parametrize("wid", ["W001", "W002", "W003", "W004"])
@pytest.mark.parametrize("consulta", [
    "contrato de Camila Rojas bono productividad", "sueldo base de Tomás Aguilera",
    "contrato de Valentina Cortés", "Diego Fuentes plazo fijo", "remuneración"])
def test_un_trabajador_nunca_recupera_documentos_ajenos(indice, wid, consulta):
    for doc, _ in buscar(indice, consulta, wid, k=10):
        assert doc.metadata["worker_id"] in {wid, TODOS_LOS_TRABAJADORES}


def test_recupera_el_anexo_de_bono_de_camila(indice):
    ids = [d.metadata["chunk_id"] for d, _ in buscar(indice, "bono de productividad meta de atenciones", "W001", k=4)]
    assert any(i.startswith("contrato_W001.md") for i in ids)
    assert any(i.startswith("politica_bonos.md") for i in ids)


def test_tomas_no_ve_el_bono_de_camila(indice):
    ids = [d.metadata["chunk_id"] for d, _ in buscar(indice, "bono de productividad meta de atenciones", "W002", k=10)]
    assert not any(i.startswith("contrato_W001") for i in ids)


def test_recupera_la_clausula_de_plazo_fijo_de_diego(indice):
    docs = [d for d, _ in buscar(indice, "seguro de cesantía contrato a plazo fijo trabajador no cotiza", "W004", k=4)]
    assert any(d.metadata["source"] == "contrato_W004.md" and d.metadata["seccion"].startswith("CLÁUSULA OCTAVA") for d in docs)


def test_filtro():
    assert filtro_para("W001") == {"$or": [{"worker_id": "W001"}, {"worker_id": "ALL"}]}
