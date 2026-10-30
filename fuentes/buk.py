"""Conector Buk. La interfaz está lista; no hay credenciales ni llamadas HTTP."""
from __future__ import annotations

from .protocolo import ErrorCarga, ResultadoCarga


class BukConector:
    nombre = "Buk"
    disponible = False
    detalle = "Preparado para un sistema externo. Sin credenciales ni llamadas."

    def cargar(self, contenido: bytes = b"", **opciones) -> ResultadoCarga:
        raise ErrorCarga("Buk no está configurado.")
