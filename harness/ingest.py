"""Ingesta: documentos Markdown -> chunks con metadata -> indice Chroma persistente.

Los comentarios "PASO n" son los mismos pasos de la guia para alumnos (docs/guia_alumnos.md).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from . import almacen
from .almacen import TODOS_LOS_TRABAJADORES, metadata_de_nombre
from .config import Settings


# ------------------------------------------------------------------ PASO 5: cargar documentos
def _metadata_de_archivo(ruta: Path) -> dict:
    """Metadata que viaja con cada documento: de donde viene y a quien pertenece."""
    doc_type, worker_id = metadata_de_nombre(ruta.name)
    return {"source": ruta.name, "doc_type": doc_type, "worker_id": worker_id}


def _fuentes(docs_dir: Path | None = None) -> list[tuple[str, str, dict]]:
    """(nombre, contenido, metadata) de cada documento.

    Sin directorio se lee el corpus del almacén: los documentos base y los que cargó RR.HH.
    Con un directorio explícito se leen sus archivos .md (útil para probar la ingesta aislada).
    """
    if docs_dir is not None:
        return [(r.name, r.read_text(encoding="utf-8"), _metadata_de_archivo(r))
                for r in sorted(docs_dir.rglob("*.md"))]
    return [(d["nombre"], d["contenido"],
             {"source": d["nombre"], "doc_type": d["doc_type"], "worker_id": d["worker_id"]})
            for d in almacen.corpus()]


def cargar_documentos(docs_dir: Path | None = None) -> list[Document]:
    return [Document(page_content=contenido, metadata=metadata)
            for _, contenido, metadata in _fuentes(docs_dir)]


# ------------------------------------------------------------------ PASO 6: chunking por clausula
def trocear(documentos: list[Document], chunk_size: int = 700, chunk_overlap: int = 100) -> list[Document]:
    """Un chunk por clausula/seccion (respeta la estructura), y parte solo las muy largas.

    Cada chunk lleva su titulo y seccion como encabezado de contexto: mejora la recuperacion
    porque el texto de una clausula suelta casi nunca dice de que contrato es.
    """
    por_encabezado = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "titulo"), ("##", "seccion")], strip_headers=True)
    partidor = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chunks: list[Document] = []
    for doc in documentos:
        n = 0
        for parte in por_encabezado.split_text(doc.page_content):
            if "seccion" not in parte.metadata:  # introduccion/aviso sin seccion: se descarta
                continue
            for texto in partidor.split_text(parte.page_content):
                n += 1
                meta = {**doc.metadata, "titulo": parte.metadata.get("titulo", ""),
                        "seccion": parte.metadata["seccion"], "chunk_id": f"{doc.metadata['source']}#{n:02d}"}
                contexto = f"{meta['titulo']} · {meta['seccion']}"
                chunks.append(Document(page_content=f"{contexto}\n{texto}", metadata=meta))
    return chunks


# ------------------------------------------------------------------ PASO 7: indice en Chroma
def _firma(settings: Settings, docs_dir: Path | None = None) -> str:
    """Huella del indice: si cambian los documentos o el modelo de embeddings, hay que reindexar."""
    h = hashlib.sha1(f"{settings.embeddings_provider}|{settings.embedding_model}".encode())
    for nombre, contenido, _ in _fuentes(docs_dir):
        h.update(nombre.encode())
        h.update(contenido.encode())
    return h.hexdigest()[:16]


def construir_indice(embeddings: Embeddings, settings: Settings, docs_dir: Path | None = None) -> Chroma:
    """(Re)construye la coleccion desde cero y la persiste en disco."""
    chunks = trocear(cargar_documentos(docs_dir))
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    try:
        client.delete_collection(settings.collection)
    except Exception:  # la coleccion no existia
        pass
    return Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        ids=[c.metadata["chunk_id"] for c in chunks],
        client=client,
        collection_name=settings.collection,
        collection_metadata={"hnsw:space": "cosine", "firma": _firma(settings, docs_dir)},
    )


def abrir_indice(embeddings: Embeddings, settings: Settings) -> Chroma:
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return Chroma(client=client, collection_name=settings.collection, embedding_function=embeddings)


def estado_indice(settings: Settings, docs_dir: Path | None = None) -> dict:
    """Estado de la coleccion persistida: si existe y si coincide con los documentos actuales."""
    firma = _firma(settings, docs_dir)
    info = {"existe": False, "fragmentos": 0, "al_dia": False, "documentos": len(_fuentes(docs_dir))}
    try:
        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        col = client.get_collection(settings.collection)
    except Exception:
        return info
    n = col.count()
    return {**info, "existe": n > 0, "fragmentos": n,
            "al_dia": (col.metadata or {}).get("firma") == firma and n > 0}


def asegurar_indice(embeddings: Embeddings, settings: Settings, docs_dir: Path | None = None,
                    forzar: bool = False) -> Chroma:
    """Reusa el indice persistido si su huella coincide; si no, lo reconstruye."""
    if not forzar:
        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        try:
            col = client.get_collection(settings.collection)
            if (col.metadata or {}).get("firma") == _firma(settings, docs_dir) and col.count() > 0:
                return abrir_indice(embeddings, settings)
        except Exception:  # no existe aun
            pass
    return construir_indice(embeddings, settings, docs_dir)


if __name__ == "__main__":  # python -m harness.ingest
    from .llm_factory import crear_embeddings

    cfg = Settings()
    idx = construir_indice(crear_embeddings(cfg), cfg)
    print(f"Indice listo: {idx._collection.count()} chunks en {cfg.chroma_dir}")
