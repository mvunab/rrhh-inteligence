"""Contrato de salida del agente (agent/output.schema.json se genera desde aqui)."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class Fuente(BaseModel):
    tipo: Literal["documento", "herramienta"] = Field(
        description="'documento' si viene de un trozo recuperado de Chroma; 'herramienta' si viene de una tool.")
    referencia: str = Field(
        description="Para documento: el id del trozo (ej. contrato_W001.md#06). Para herramienta: su nombre.")
    detalle: str = Field(default="", description="Frase corta de que dato salio de esa fuente.")


class LineaDescuento(BaseModel):
    concepto: str
    monto: int = Field(description="Monto en pesos chilenos, tal como aparece en la liquidacion.")
    explicacion: str = Field(description="Por que se descuenta, en lenguaje simple para el trabajador.")
    fuente: str = Field(default="", description="Referencia a la fuente que respalda la explicacion.")


class Hallazgo(BaseModel):
    severidad: Literal["info", "revisar", "critico"]
    descripcion: str
    monto_diferencia: int | None = Field(
        default=None, description="Pagado menos esperado, en pesos (positivo = se descuento de mas).")
    recomendacion: str = ""


class InformeLiquidacion(BaseModel):
    respuesta: str = Field(description="Respuesta directa a la pregunta, en espanol claro.")
    descuentos: list[LineaDescuento] = Field(default_factory=list)
    hallazgos: list[Hallazgo] = Field(default_factory=list)
    fuentes: list[Fuente] = Field(default_factory=list)
    requiere_revision_rrhh: bool = Field(
        description="True si hay diferencias que Recursos Humanos deberia revisar.")
    fuera_de_alcance: bool = Field(
        default=False,
        description="True si la pregunta no es sobre la liquidacion del trabajador autenticado.")


def extraer_json(texto: str) -> str:
    """Saca el objeto JSON de la respuesta del modelo (tolera ```json ... ``` y texto extra)."""
    limpio = re.sub(r"```(?:json)?", "", texto).strip()
    ini, fin = limpio.find("{"), limpio.rfind("}")
    if ini == -1 or fin == -1 or fin < ini:
        raise ValueError("La respuesta no contiene un objeto JSON.")
    return limpio[ini : fin + 1]


def parsear_informe(texto: str) -> InformeLiquidacion:
    """Valida el texto del modelo contra el contrato. Lanza ValueError si no cumple."""
    try:
        return InformeLiquidacion.model_validate_json(extraer_json(texto))
    except ValidationError as e:  # normalizamos a ValueError para que el harness reintente
        raise ValueError(str(e)) from e
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido: {e}") from e


def json_schema() -> dict:
    return InformeLiquidacion.model_json_schema()
