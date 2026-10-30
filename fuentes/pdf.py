"""PDF con texto: lectura con pypdf y generación de PDFs de prueba."""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from .protocolo import ErrorCarga


def pdf_de_paginas(paginas: list[list[str]]) -> bytes:
    """PDF de texto, una página por liquidación. pypdf puede leerlo; un escaneo no."""
    if not paginas:
        raise ErrorCarga("No hay páginas para el PDF.")
    flujos = []
    for lineas in paginas:
        ordenes = ["BT", "/F1 11 Tf", "14 TL", "72 760 Td"]
        for i, linea in enumerate(lineas):
            ordenes.append(f"({_escapar_pdf(linea)}) Tj")
            if i < len(lineas) - 1:
                ordenes.append("T*")
        ordenes.append("ET")
        flujos.append("\n".join(ordenes).encode("latin-1", errors="replace"))
    cantidad = len(flujos)
    fuente = 3 + cantidad * 2
    hijos = " ".join(f"{3 + i * 2} 0 R" for i in range(cantidad))
    objetos: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {cantidad} /Kids [{hijos}] >>".encode(),
    ]
    for i, flujo in enumerate(flujos):
        pagina = 3 + i * 2
        objetos.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {pagina + 1} 0 R "
            f"/Resources << /Font << /F1 {fuente} 0 R >> >> >>".encode()
        )
        objetos.append(f"<< /Length {len(flujo)} >>\nstream\n".encode() + flujo + b"\nendstream")
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    salida = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, cuerpo in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(offsets)}\n".encode()
    salida += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        salida += f"{off:010d} 00000 n \n".encode()
    salida += f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(salida)


def _escapar_pdf(linea: str) -> str:
    return linea.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def extraer_texto(contenido: bytes) -> str:
    try:
        lector = PdfReader(BytesIO(contenido))
        texto = "\n".join((pagina.extract_text() or "") for pagina in lector.pages)
    except Exception as e:  # noqa: BLE001
        raise ErrorCarga(f"No se pudo leer el PDF: {e}") from e
    texto = texto.strip()
    if not texto:
        raise ErrorCarga("El PDF no tiene texto extraíble. Hace falta un PDF con texto, no una imagen.")
    return texto
