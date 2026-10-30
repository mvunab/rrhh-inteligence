"""Recuperacion con filtro de metadata: el control de acceso vive AQUI, no en el prompt."""
from __future__ import annotations

from langchain_chroma import Chroma
from langchain_core.documents import Document

from .ingest import TODOS_LOS_TRABAJADORES


def filtro_para(worker_id: str) -> dict:
    """Un trabajador ve SUS documentos y los compartidos (reglamento, politicas, normativa)."""
    return {"$or": [{"worker_id": worker_id}, {"worker_id": TODOS_LOS_TRABAJADORES}]}


# ------------------------------------------------------------------ PASO 8: consulta con filtro
def buscar(indice: Chroma, consulta: str, worker_id: str, k: int = 4) -> list[tuple[Document, float]]:
    """Devuelve (documento, relevancia) ordenados; relevancia = 1 - distancia coseno."""
    return indice.similarity_search_with_relevance_scores(
        consulta, k=k, filter=filtro_para(worker_id))
