"""Contrato común de los orígenes de liquidaciones y contratos."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ErrorCarga(Exception):
    """El archivo o el conector no se puede usar. El mensaje es para RR.HH."""


@dataclass
class ResultadoCarga:
    origen: str
    resumen: str
    liquidaciones: list[dict] = field(default_factory=list)
    documento: dict | None = None
    trabajadores: list[dict] = field(default_factory=list)


class Conector(Protocol):
    nombre: str
    disponible: bool
    detalle: str

    def cargar(self, contenido: bytes, **opciones) -> ResultadoCarga:
        """Lee el origen. Si el archivo o el sistema externo no sirven, lanza ErrorCarga."""
