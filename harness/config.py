"""Configuracion del proyecto, leida desde variables de entorno (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

try:  # python-dotenv es opcional: en Docker las variables llegan por env_file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = DATA_DIR / "documentos"
AGENT_DIR = ROOT / "agent"

def _env(nombre: str, defecto: str) -> str:
    return os.environ.get(nombre, defecto)


@dataclass(frozen=True)
class Settings:
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "ollama"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "llama3.1:8b"))
    embeddings_provider: str = field(default_factory=lambda: _env("EMBEDDINGS_PROVIDER", "ollama"))
    embedding_model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "nomic-embed-text-v2-moe"))
    ollama_base_url: str = field(
        default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434"))
    unab_base_url: str = field(
        default_factory=lambda: _env("UNAB_BASE_URL", "https://quotas.devhub.cl/api/v1"))
    unab_api_key: str = field(default_factory=lambda: _env("UNAB_API_KEY", ""))
    chroma_dir: Path = field(default_factory=lambda: Path(_env("CHROMA_DIR", str(ROOT / "chroma_db"))))
    collection: str = field(default_factory=lambda: _env("CHROMA_COLLECTION", "liquidaciones"))
    k: int = field(default_factory=lambda: int(_env("RETRIEVER_K", "4")))
    temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0")))
    max_pasos: int = field(default_factory=lambda: int(_env("AGENT_MAX_STEPS", "8")))

    def con(self, **cambios) -> "Settings":
        return replace(self, **cambios)

    @classmethod
    def modo_mock(cls) -> "Settings":
        """Todo offline: LLM y embeddings simulados (para tests y demos sin red)."""
        return cls().con(llm_provider="mock", embeddings_provider="mock")
