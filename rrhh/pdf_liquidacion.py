"""PDF de la liquidación corregida. Mientras es borrador lleva la marca BORRADOR en cada página."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

EMPRESA = "Clínica Traumatología Cóndor SpA (ficticia)"
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_AZUL = colors.HexColor("#1e2761")
_GRIS = colors.HexColor("#eef1f7")
_LINEA = colors.HexColor("#c9cfdd")


def clp(n: int | float | None) -> str:
    if n is None:
        return "—"
    return ("-" if n < 0 else "") + f"${abs(int(n)):,}".replace(",", ".")


def mes(periodo: str) -> str:
    anio, numero = periodo.split("-")
    return f"{_MESES[int(numero) - 1].capitalize()} {anio}"


def pdf_borrador(borrador: dict) -> bytes:
    salida = BytesIO()
    es_borrador = borrador["estado"] == "borrador"
    doc = SimpleDocTemplate(
        salida, pagesize=LETTER, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
        bottomMargin=18 * mm, title=f"Liquidación {borrador['worker_id']} {borrador['periodo']}",
        author=EMPRESA,
    )
    estilos = _estilos()
    liq = borrador["propuesta"]
    t = borrador["trabajador"]
    piezas = [
        Paragraph(EMPRESA, estilos["empresa"]),
        Paragraph("LIQUIDACIÓN DE SUELDO", estilos["titulo"]),
        Paragraph(f"{mes(borrador['periodo'])} · "
                  + ("Propuesta de rectificación — borrador" if es_borrador else "Liquidación rectificada"),
                  estilos["subtitulo"]),
        Spacer(1, 4 * mm),
        _ficha(borrador, estilos),
        Spacer(1, 5 * mm),
        _bloque("Haberes imponibles", [(h["concepto"], clp(h["monto"])) for h in liq["haberes_imponibles"]],
                estilos),
        Spacer(1, 3 * mm),
        _bloque("Haberes no imponibles",
                [(h["concepto"], clp(h["monto"])) for h in liq["haberes_no_imponibles"]] or [("—", clp(0))],
                estilos),
        Spacer(1, 3 * mm),
        _descuentos(liq, estilos),
        Spacer(1, 4 * mm),
        _totales(liq, estilos),
    ]
    if borrador.get("ajustes"):
        piezas += [Spacer(1, 6 * mm), Paragraph("Ajustes respecto de la liquidación emitida", estilos["seccion"]),
                   _tabla_ajustes(borrador["ajustes"], estilos)]
    if borrador.get("nota"):
        piezas += [Spacer(1, 4 * mm), Paragraph("Nota del analista", estilos["seccion"]),
                   Paragraph(_texto(borrador["nota"]), estilos["normal"])]
    params = borrador.get("parametros") or {}
    piezas += [
        Spacer(1, 10 * mm),
        _firmas(t.get("nombre") or borrador["worker_id"], estilos),
        Spacer(1, 6 * mm),
        Paragraph(
            f"Descuentos legales calculados por el motor de RRHH Intelligence con UF {clp(params.get('uf'))} y "
            f"tope imponible {clp(params.get('tope_afp_salud'))}. Parámetros verificados el "
            f"{params.get('verificados') or '—'}. Documento {borrador['id']} v{borrador.get('version', 1)}.",
            estilos["pie"]),
    ]
    marca = _marca_borrador if es_borrador else _sin_marca
    doc.build(piezas, onFirstPage=marca, onLaterPages=marca)
    return salida.getvalue()


def _estilos() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "empresa": ParagraphStyle("empresa", parent=base["Normal"], fontSize=9, textColor=colors.grey),
        "titulo": ParagraphStyle("titulo", parent=base["Title"], fontSize=17, textColor=_AZUL, alignment=0,
                                 spaceAfter=2),
        "subtitulo": ParagraphStyle("subtitulo", parent=base["Normal"], fontSize=10.5, textColor=_AZUL),
        "seccion": ParagraphStyle("seccion", parent=base["Heading4"], textColor=_AZUL, spaceBefore=0,
                                  spaceAfter=3),
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=9, leading=12),
        "celda": ParagraphStyle("celda", parent=base["Normal"], fontSize=8.5, leading=10.5),
        "derecha": ParagraphStyle("derecha", parent=base["Normal"], fontSize=9, alignment=TA_RIGHT),
        "pie": ParagraphStyle("pie", parent=base["Normal"], fontSize=7.5, textColor=colors.grey, leading=10),
    }


def _texto(valor: str) -> str:
    return str(valor).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ficha(borrador: dict, estilos: dict) -> Table:
    t = borrador["trabajador"]
    liq = borrador["propuesta"]
    contrato = (t.get("tipo_contrato") or "").replace("_", " ")
    filas = [
        ["Trabajador", t.get("nombre") or "—", "Código", borrador["worker_id"]],
        ["Cargo", t.get("cargo") or "—", "Área", t.get("area") or "—"],
        ["Contrato", contrato or "—", "Ingreso", t.get("fecha_inicio") or "—"],
        ["AFP", t.get("afp") or "—", "Salud", t.get("salud") or "—"],
        ["Período", mes(borrador["periodo"]), "Días trabajados", str(liq.get("dias_trabajados") or "—")],
    ]
    tabla = Table(filas, colWidths=[28 * mm, 62 * mm, 30 * mm, 60 * mm])
    tabla.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), _AZUL),
        ("TEXTCOLOR", (2, 0), (2, -1), _AZUL),
        ("BACKGROUND", (0, 0), (-1, -1), _GRIS),
        ("BOX", (0, 0), (-1, -1), 0.6, _LINEA),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tabla


def _bloque(titulo: str, filas: list[tuple[str, str]], estilos: dict) -> Table:
    datos = [[titulo, "Monto"]] + [list(f) for f in filas]
    tabla = Table(datos, colWidths=[140 * mm, 40 * mm])
    tabla.setStyle(_estilo_tabla(len(datos)))
    return tabla


def _descuentos(liq: dict, estilos: dict) -> Table:
    datos = [["Descuentos legales", "Base", "Tasa", "Monto"]]
    for d in liq["descuentos_legales"]:
        tasa = "—" if d.get("tasa") is None else f"{d['tasa'] * 100:.2f}%".replace(".", ",")
        datos.append([d["concepto"], clp(d.get("base")), tasa, clp(d["monto"])])
    tabla = Table(datos, colWidths=[80 * mm, 40 * mm, 20 * mm, 40 * mm])
    tabla.setStyle(_estilo_tabla(len(datos)))
    return tabla


def _totales(liq: dict, estilos: dict) -> Table:
    datos = [
        ["Total haberes", clp(liq["total_haberes"])],
        ["Total descuentos", clp(liq["total_descuentos"])],
        ["LÍQUIDO A PAGAR", clp(liq["liquido_a_pagar"])],
    ]
    tabla = Table(datos, colWidths=[140 * mm, 40 * mm])
    tabla.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, _LINEA),
        ("FONT", (0, 2), (-1, 2), "Helvetica-Bold", 12),
        ("BACKGROUND", (0, 2), (-1, 2), _AZUL),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tabla


def _tabla_ajustes(ajustes: list[dict], estilos: dict) -> Table:
    datos = [["Concepto", "Emitido", "Propuesto", "Diferencia", "Motivo"]]
    for a in ajustes:
        datos.append([
            Paragraph(_texto(a["concepto"]), estilos["celda"]), clp(a["emitido"]), clp(a["propuesto"]),
            clp(a["diferencia"]), Paragraph(_texto(a["motivo"]), estilos["celda"]),
        ])
    tabla = Table(datos, colWidths=[38 * mm, 24 * mm, 24 * mm, 24 * mm, 70 * mm], repeatRows=1)
    estilo = _estilo_tabla(len(datos))
    estilo.add("ALIGN", (1, 1), (3, -1), "RIGHT")
    estilo.add("ALIGN", (4, 0), (4, -1), "LEFT")
    estilo.add("VALIGN", (0, 0), (-1, -1), "TOP")
    tabla.setStyle(estilo)
    return tabla


def _firmas(nombre: str, estilos: dict) -> Table:
    tabla = Table([["", "", ""], ["Recursos Humanos", "", f"Recibí conforme: {nombre}"]],
                  colWidths=[70 * mm, 40 * mm, 70 * mm], rowHeights=[14 * mm, 6 * mm])
    tabla.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (0, 0), 0.6, colors.grey),
        ("LINEBELOW", (2, 0), (2, 0), 0.6, colors.grey),
        ("FONT", (0, 1), (-1, 1), "Helvetica", 8),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.grey),
        ("ALIGN", (0, 1), (-1, 1), "CENTER"),
    ]))
    return tabla


def _estilo_tabla(filas: int) -> TableStyle:
    estilo = TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), _AZUL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, _AZUL),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])
    for fila in range(2, filas, 2):
        estilo.add("BACKGROUND", (0, fila), (-1, fila), _GRIS)
    return estilo


def _marca_borrador(lienzo, doc) -> None:
    lienzo.saveState()
    lienzo.setFont("Helvetica-Bold", 90)
    lienzo.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
    lienzo.translate(LETTER[0] / 2, LETTER[1] / 2)
    lienzo.rotate(40)
    lienzo.drawCentredString(0, 0, "BORRADOR")
    lienzo.restoreState()
    _numero(lienzo, doc)


def _sin_marca(lienzo, doc) -> None:
    _numero(lienzo, doc)


def _numero(lienzo, doc) -> None:
    lienzo.saveState()
    lienzo.setFont("Helvetica", 7.5)
    lienzo.setFillColor(colors.grey)
    lienzo.drawRightString(LETTER[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
    lienzo.restoreState()
