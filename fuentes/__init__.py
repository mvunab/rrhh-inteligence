"""Orígenes de datos de RR.HH.: Excel, PDF y Buk (preparado)."""
from .buk import BukConector
from .excel import ExcelConector
from .liquidacion_pdf import LiquidacionPdfConector
from .contratos import PdfConector
from .protocolo import Conector, ErrorCarga, ResultadoCarga

__all__ = [
    "BukConector", "Conector", "ErrorCarga", "ExcelConector", "LiquidacionPdfConector",
    "PdfConector", "ResultadoCarga", "listar",
]


def listar() -> list[Conector]:
    return [ExcelConector(), LiquidacionPdfConector(), PdfConector(), BukConector()]
