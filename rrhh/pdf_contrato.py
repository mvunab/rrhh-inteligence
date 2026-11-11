"""PDF del contrato de trabajo, armado desde el texto que ya está en la base."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

EMPRESA = "Clínica Traumatología Cóndor SpA (ficticia)"
_AZUL = colors.HexColor("#1e2761")


def pdf_de_contrato(markdown: str, worker_id: str) -> bytes:
    salida = BytesIO()
    doc = SimpleDocTemplate(
        salida, pagesize=LETTER, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
        bottomMargin=16 * mm, title=f"Contrato {worker_id}", author=EMPRESA,
    )
    estilos = _estilos()
    piezas = [Paragraph(EMPRESA, estilos["empresa"]), Spacer(1, 2 * mm)]
    for tipo, texto in _bloques(markdown):
        if tipo == "titulo":
            piezas.append(Paragraph(_xml(texto), estilos["titulo"]))
        elif tipo == "nota":
            piezas.append(Paragraph(_xml(texto), estilos["nota"]))
        elif tipo == "seccion":
            piezas.append(Spacer(1, 3 * mm))
            piezas.append(Paragraph(_xml(texto), estilos["seccion"]))
        else:
            piezas.append(Paragraph(_xml(texto), estilos["normal"]))
            piezas.append(Spacer(1, 1.5 * mm))
    piezas += [
        Spacer(1, 8 * mm),
        Paragraph(
            "Documento ficticio, generado para la vista del trabajador a partir del contrato vigente. "
            f"{EMPRESA}.",
            estilos["pie"],
        ),
    ]
    doc.build(piezas)
    return salida.getvalue()


def _bloques(markdown: str) -> list[tuple[str, str]]:
    bloques: list[tuple[str, str]] = []
    parrafo: list[str] = []

    def cerrar() -> None:
        texto = " ".join(linea.strip() for linea in parrafo).strip()
        parrafo.clear()
        if texto:
            bloques.append(("parrafo", texto))

    for linea in markdown.splitlines():
        if linea.startswith("# "):
            cerrar()
            bloques.append(("titulo", linea[2:].strip()))
        elif linea.startswith("## "):
            cerrar()
            bloques.append(("seccion", linea[3:].strip()))
        elif linea.startswith("> "):
            cerrar()
            bloques.append(("nota", linea[2:].strip()))
        elif not linea.strip():
            cerrar()
        else:
            parrafo.append(linea)
    cerrar()
    return bloques


def _xml(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _estilos() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "empresa": ParagraphStyle("empresa", parent=base["Normal"], fontSize=9, textColor=colors.grey),
        "titulo": ParagraphStyle("titulo", parent=base["Title"], fontSize=16, textColor=_AZUL,
                                 alignment=0, spaceAfter=4),
        "nota": ParagraphStyle("nota", parent=base["Italic"], fontSize=9, textColor=colors.grey,
                               spaceAfter=6),
        "seccion": ParagraphStyle("seccion", parent=base["Heading4"], textColor=_AZUL,
                                  spaceBefore=2, spaceAfter=3),
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=10, leading=14),
        "pie": ParagraphStyle("pie", parent=base["Normal"], fontSize=8, textColor=colors.grey, leading=10),
    }
