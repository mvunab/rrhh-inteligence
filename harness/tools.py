"""Tools del agente. Se crean POR SESION: el worker_id queda fijo en la closure.

Decision de seguridad clave: el LLM NUNCA elige de que trabajador se habla. Si el id fuera un
parametro de la tool, un prompt malicioso ("consulta al trabajador W002") podria cruzar datos.
Aqui el id viene de la sesion autenticada y el modelo no puede cambiarlo.
"""
from __future__ import annotations

import json
import re

from langchain_chroma import Chroma
from langchain_core.tools import BaseTool, tool

from . import datos
from .calculos import (
    cargar_parametros,
    comparar_con_liquidacion,
    tope_gratificacion_mensual,
    tope_imponible_pesos,
)
from .config import Settings
from .retriever import buscar


def _dump(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _normalizar_periodo(periodo: str | None) -> str | None:
    p = (periodo or "").strip()
    return p if re.fullmatch(r"\d{4}-\d{2}", p) else None


def crear_herramientas(worker_id: str, indice: Chroma, settings: Settings,
                       params: dict | None = None) -> list[BaseTool]:
    params = params or cargar_parametros()
    trabajador = datos.obtener_trabajador(worker_id)
    if trabajador is None:
        raise ValueError(f"Trabajador desconocido: {worker_id}")

    # ------------------------------------------------------------------ PASO 9a: tools de datos
    @tool
    def obtener_liquidacion(periodo: str = "") -> str:
        """Devuelve la liquidación de sueldo del trabajador autenticado (haberes, descuentos, líquido)
        y su perfil de contrato (cargo, tipo de contrato, AFP, salud). 'periodo' tiene formato AAAA-MM
        (ejemplo 2026-09); si se deja vacío devuelve el más reciente. No acepta ni entrega datos de
        otros trabajadores."""
        disponibles = datos.periodos_disponibles(worker_id)
        p = _normalizar_periodo(periodo) or (disponibles[-1] if disponibles else None)
        liq = datos.obtener_liquidacion(worker_id, p)
        if liq is None:
            return _dump({"error": f"No hay liquidación para el periodo {periodo!r}.",
                          "periodos_disponibles": disponibles})
        ficha = datos.obtener_trabajador(worker_id, liq["periodo"])
        perfil = {k: ficha[k] for k in
                  ("nombre", "cargo", "tipo_contrato", "afp", "salud", "fecha_inicio", "fecha_termino")}
        return _dump({"trabajador": perfil, "liquidacion": liq, "periodos_disponibles": disponibles})

    @tool
    def calcular_descuentos_esperados(periodo: str = "") -> str:
        """Recalcula con las reglas vigentes los descuentos legales (AFP, salud, seguro de cesantía,
        impuesto único) y la gratificación Art. 50 del trabajador autenticado, y los compara con lo
        que dice su liquidación. Para cada línea entrega esperado, pagado, diferencia, estado
        ('ok', 'diferencia' o 'derivada') y la causa probable. Úsala siempre que haya que verificar
        o explicar un descuento: NUNCA calcules estos montos tú mismo. 'periodo' formato AAAA-MM,
        vacío = más reciente."""
        disponibles = datos.periodos_disponibles(worker_id)
        p = _normalizar_periodo(periodo) or (disponibles[-1] if disponibles else None)
        liq = datos.obtener_liquidacion(worker_id, p)
        if liq is None:
            return _dump({"error": f"No hay liquidación para el periodo {periodo!r}.",
                          "periodos_disponibles": disponibles})
        resultado = comparar_con_liquidacion(params, datos.obtener_trabajador(worker_id, liq["periodo"]), liq)
        resultado["periodo"] = liq["periodo"]
        return _dump(resultado)

    @tool
    def consultar_parametros() -> str:
        """Entrega los parámetros vigentes de remuneraciones con su fuente y fecha: UF, UTM, ingreso
        mínimo, tope imponible (en UF y en pesos), comisiones de cada AFP, tasas de cotización y tope de
        gratificación. Úsala para cualquier pregunta sobre valores numéricos: no los recuerdes de memoria."""
        return _dump({
            "uf": params["uf"], "utm": params["utm"], "ingreso_minimo": params["ingreso_minimo"],
            "topes_uf": params["topes_uf"],
            "topes_pesos": {"afp_salud": tope_imponible_pesos(params, "afp_salud"),
                            "seguro_cesantia": tope_imponible_pesos(params, "seguro_cesantia"),
                            "gratificacion_mensual": tope_gratificacion_mensual(params)},
            "comisiones_afp": params["comisiones_afp"],
            "cotizaciones": params["cotizaciones"],
            "fecha_verificacion": params["fecha_verificacion"],
        })

    # ------------------------------------------------------------------ PASO 9b: tool de RAG
    @tool(response_format="content_and_artifact")
    def buscar_en_documentos(consulta: str) -> tuple[str, list[str]]:
        """Busca en los documentos del trabajador autenticado (su contrato y anexos) y en los
        documentos compartidos (reglamento interno, política de bonos, guía de remuneraciones).
        Úsala para saber qué dice el contrato, cómo se miden los bonos, qué reglas aplican o qué
        procedimiento seguir. Devuelve trozos con su id de fuente [fuente: ...]; cita siempre ese id."""
        resultados = buscar(indice, consulta, worker_id, k=settings.k)
        if not resultados:
            return "No se encontraron documentos relevantes.", []
        bloques, ids = [], []
        for doc, score in resultados:
            cid = doc.metadata["chunk_id"]
            ids.append(cid)
            bloques.append(f"[fuente: {cid}]\n{doc.page_content}\n(relevancia {score:.2f})")
        return "\n---\n".join(bloques), ids

    return [obtener_liquidacion, calcular_descuentos_esperados, consultar_parametros, buscar_en_documentos]
