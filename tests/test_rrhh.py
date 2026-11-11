"""Conectores de RR.HH., ciclo de un caso y ficha vigente por contrato y anexos."""
from pathlib import Path

import pytest

from fuentes.buk import BukConector
from fuentes.contratos import guardar_anexo, guardar_contrato
from fuentes.excel import leer_liquidaciones, plantilla_bytes
from fuentes.liquidacion_pdf import leer_liquidaciones_pdf
from fuentes.muestras import pdf_septiembre, pdf_trabajador
from fuentes.pdf import extraer_texto, pdf_de_paginas
from fuentes.protocolo import ErrorCarga
from harness import almacen
from harness.datos import obtener_liquidacion, obtener_trabajador
from harness.ingest import cargar_documentos, trocear
from rrhh.bandeja import decidir, listar_casos, obtener_caso
from rrhh.servicio import procesar_anexo, procesar_excel, procesar_pdf_liquidacion

CLASE = Path(__file__).resolve().parent.parent / "data"


def _pdf(texto: str) -> bytes:
    return pdf_de_paginas([[texto]])


def test_el_area_no_pisa_la_ficha_y_las_solicitudes_se_cuentan_por_sector():
    from sqlalchemy import update

    from harness.almacen import completar_areas, fichas_base, motor, trabajadores
    from rrhh.solicitudes import abrir_desde_consulta, estadisticas

    ficha = dict(fichas_base()["W004"])
    afp = ficha["afp"]
    ficha.pop("area", None)
    with motor().begin() as cx:
        cx.execute(update(trabajadores).where(trabajadores.c.worker_id == "W004").values(ficha=ficha))
    assert completar_areas() == 1
    restaurada = fichas_base()["W004"]
    assert restaurada["area"] == "Admisión"
    assert restaurada["afp"] == afp
    assert completar_areas() == 0

    critico = {"severidad": "critico", "descripcion": "Sin tope imponible.", "monto_diferencia": 188820,
               "recomendacion": ""}
    abrir_desde_consulta("W003", "Solicito que recursos humanos revise mi liquidación.",
                         {"respuesta": "Hay una diferencia de tope.", "requiere_revision_rrhh": True,
                          "hallazgos": [critico]})
    abrir_desde_consulta("W002", "Quiero que un analista lo revise, no entiendo el turno.",
                         {"respuesta": "El turno está bien pagado.", "requiere_revision_rrhh": True, "hallazgos": []})
    propuesta = abrir_desde_consulta("W004", "Explícame mi liquidación.",
                                     {"respuesta": "Cesantía mal descontada.", "requiere_revision_rrhh": True,
                                      "hallazgos": [critico]})
    assert propuesta["estado"] == "propuesta"
    por_area = {fila["area"]: fila for fila in estadisticas()}
    assert por_area["Traumatología"]["diferencias"] == 1
    assert por_area["Traumatología"]["trabajadores"] == 1
    assert por_area["Urgencia"]["revisiones"] == 1
    assert por_area["Admisión"]["solicitudes"] == 0

    repetida = abrir_desde_consulta("W004", "¿Por qué me descuentan cesantía en septiembre?",
                                    {"respuesta": "Cesantía mal descontada.", "requiere_revision_rrhh": True,
                                     "hallazgos": [critico]})
    assert repetida["id"] == propuesta["id"] and len(repetida["mensajes"]) == 2


def test_las_liquidaciones_guardadas_abren_sus_casos_sin_volver_a_cargar():
    from rrhh.bandeja import abrir_casos_faltantes
    abiertos = set(abrir_casos_faltantes())
    assert {"W001-2026-09", "W003-2026-09", "W004-2026-09"} <= abiertos
    assert "W002-2026-09" not in {c["id"] for c in listar_casos()}
    assert abrir_casos_faltantes() == []


def test_la_plantilla_abre_el_caso_de_camila_y_la_decision_queda_registrada():
    antes = (CLASE / "liquidaciones.json").read_bytes()
    resumen = procesar_excel(plantilla_bytes())
    assert "W001-2026-09" in resumen
    caso = obtener_caso("W001-2026-09")
    assert caso["estado"] == "pendiente"
    assert any(l["codigo"] == "afp" and l["estado"] == "diferencia" for l in caso["lineas"])
    decidido = decidir("W001-2026-09", "corregir", "Se pagó ProVida; el contrato dice Habitat.")
    assert decidido["estado"] == "corregir"
    assert "Habitat" in obtener_caso("W001-2026-09")["nota"]
    assert (CLASE / "liquidaciones.json").read_bytes() == antes  # la carga inicial no se toca


def test_excel_sin_columnas_explica_el_error():
    from io import BytesIO

    from openpyxl import Workbook
    libro = Workbook()
    libro.active.append(["worker_id"])
    buf = BytesIO()
    libro.save(buf)
    with pytest.raises(ErrorCarga, match="Faltan columnas"):
        leer_liquidaciones(buf.getvalue())


def test_el_contrato_cargado_reemplaza_al_base_en_el_corpus():
    assert "Contrato de prueba" in extraer_texto(_pdf("Contrato de prueba"))
    nombre = guardar_contrato(_pdf("Sueldo base nuevo de 1.200.000"), "W004", "2026-10-01")
    assert nombre == "contrato_W004.md"
    contratos = [d for d in cargar_documentos() if d.metadata["source"] == "contrato_W004.md"]
    assert len(contratos) == 1
    assert contratos[0].page_content.startswith("# Contrato de trabajo (W004)")
    assert "1.200.000" in contratos[0].page_content


def test_el_pdf_de_septiembre_abre_los_tres_casos_sembrados():
    resumen = procesar_pdf_liquidacion(pdf_septiembre())
    for caso in ("W001-2026-09", "W003-2026-09", "W004-2026-09"):
        assert caso in resumen
    assert "W002-2026-09" not in {c["id"] for c in listar_casos()}


def test_el_pdf_acepta_montos_con_punto_de_miles():
    lineas = extraer_texto(pdf_trabajador("W001")).splitlines()
    lineas = [linea.replace("1000000", "$1.000.000") for linea in lineas]
    liquidaciones = leer_liquidaciones_pdf(pdf_de_paginas([lineas]))
    assert liquidaciones[0]["haberes_imponibles"][0]["monto"] == 1000000


def test_un_pdf_sin_campos_explica_que_falta():
    with pytest.raises(ErrorCarga, match="faltan datos"):
        leer_liquidaciones_pdf(_pdf("Contrato sin liquidacion"))


def test_los_anexos_entran_al_corpus_con_su_trabajador():
    guardar_anexo(_pdf("Bono de 200.000"), "W001", "2026-11-01", "bono")
    docs = cargar_documentos()
    anexo = next(d for d in docs if d.metadata["source"].startswith("anexo_W001_"))
    assert anexo.metadata == {"source": "anexo_W001_2026-11-01.md", "doc_type": "anexo", "worker_id": "W001"}
    assert any(c.metadata["source"].startswith("anexo_W001_") for c in trocear(docs))
    assert not any(d.metadata["source"].startswith("anexo_")
                   for d in cargar_documentos(CLASE / "documentos"))  # un directorio explícito es solo ese


def test_la_ficha_vigente_aplica_el_anexo_desde_su_fecha():
    guardar_anexo(_pdf("Cambio a AFP ProVida"), "W001", "2026-09-01", "cambio de AFP", {"afp": "ProVida"})
    assert obtener_trabajador("W001", "2026-08")["afp"] == "Habitat"
    vigente = obtener_trabajador("W001", "2026-09")
    assert vigente["afp"] == "ProVida"
    assert vigente["versiones"][-1]["documento"] == "anexo_W001_2026-09-01.md"


def test_un_anexo_que_corrige_la_afp_recalcula_el_caso():
    procesar_excel(plantilla_bytes())
    assert obtener_caso("W001-2026-09")["hay_diferencias"] is True
    resumen = procesar_anexo(_pdf("Cambio a AFP ProVida"), "W001", "2026-09-01", "cambio de AFP", {"afp": "ProVida"})
    assert "afp = ProVida" in resumen
    assert "W001-2026-09" in resumen
    lineas = {l["codigo"]: l for l in obtener_caso("W001-2026-09")["lineas"]}
    assert lineas["afp"]["estado"] == "ok"


def test_los_cambios_desconocidos_se_rechazan():
    with pytest.raises(ErrorCarga, match="no se puede cambiar"):
        guardar_anexo(_pdf("x"), "W001", "2026-09-01", "", {"nombre": "Otra"})
    with pytest.raises(ErrorCarga, match="indefinido o plazo_fijo"):
        guardar_anexo(_pdf("x"), "W001", "2026-09-01", "", {"tipo_contrato": "honorarios"})


def test_buk_pide_el_mes():
    with pytest.raises(ErrorCarga, match="AAAA-MM"):
        BukConector().cargar()


def test_una_carga_reemplaza_la_liquidacion_del_mismo_periodo():
    original = obtener_liquidacion("W001", "2026-09")
    alterada = {**original, "liquido_a_pagar": 1}
    almacen.guardar_liquidaciones([alterada], "excel")
    assert obtener_liquidacion("W001", "2026-09")["liquido_a_pagar"] == 1
    assert len([l for l in almacen.listar_liquidaciones("W001") if l["periodo"] == "2026-09"]) == 1


def test_decidir_exige_nota():
    procesar_excel(plantilla_bytes())
    with pytest.raises(ValueError, match="nota"):
        decidir("W001-2026-09", "mantener", "  ")
    assert obtener_caso("W001-2026-09")["estado"] == "pendiente"
