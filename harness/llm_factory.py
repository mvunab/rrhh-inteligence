"""Fabrica de LLM y embeddings: ollama (local) | unab (API compatible con OpenAI) | mock (offline)."""
from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from .config import Settings
from .fakes import FakeDeterministicEmbeddings, MockLiquidacionChatModel


class PrefixedEmbeddings(Embeddings):
    """Agrega los prefijos que los modelos nomic esperan ('search_document:' / 'search_query:').

    Sin estos prefijos la calidad de la recuperacion baja. Es un detalle que los tutoriales omiten.
    """

    def __init__(self, base: Embeddings, doc_prefix: str, query_prefix: str) -> None:
        self.base, self.doc_prefix, self.query_prefix = base, doc_prefix, query_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.base.embed_documents([self.doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.base.embed_query(self.query_prefix + text)


def crear_llm(settings: Settings) -> BaseChatModel:
    prov = settings.llm_provider
    if prov == "mock":
        return MockLiquidacionChatModel()
    if prov == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=settings.llm_model, base_url=settings.ollama_base_url,
                          temperature=settings.temperature)
    if prov == "unab":
        from langchain_openai import ChatOpenAI

        if not settings.unab_api_key:
            raise RuntimeError("Falta UNAB_API_KEY en el entorno (.env).")
        return ChatOpenAI(model=settings.llm_model, base_url=settings.unab_base_url,
                          api_key=settings.unab_api_key, temperature=settings.temperature)
    raise ValueError(f"LLM_PROVIDER desconocido: {prov!r} (usa ollama | unab | mock)")


def crear_embeddings(settings: Settings) -> Embeddings:
    prov = settings.embeddings_provider
    if prov == "mock":
        return FakeDeterministicEmbeddings()
    if prov == "ollama":
        from langchain_ollama import OllamaEmbeddings

        base = OllamaEmbeddings(model=settings.embedding_model, base_url=settings.ollama_base_url)
        if "nomic" in settings.embedding_model:
            return PrefixedEmbeddings(base, "search_document: ", "search_query: ")
        return base
    raise ValueError(f"EMBEDDINGS_PROVIDER desconocido: {prov!r} (usa ollama | mock)")


def descripcion(settings: Settings) -> dict[str, str]:
    llm = "simulado (mock)" if settings.llm_provider == "mock" else f"{settings.llm_provider} · {settings.llm_model}"
    emb = ("simulados (mock)" if settings.embeddings_provider == "mock"
           else f"{settings.embeddings_provider} · {settings.embedding_model}")
    return {"llm": llm, "embeddings": emb}
