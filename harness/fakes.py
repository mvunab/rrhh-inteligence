"""Modelos simulados para trabajar SIN red ni Ollama (tests, demos sin wifi).

* FakeDeterministicEmbeddings: embeddings por hashing de palabras (bolsa de palabras).
  No entiende sinonimos como un modelo real, pero permite probar chunking, filtros de
  metadata y recuperacion de forma determinista.
* MockLiquidacionChatModel: un "agente guionado" que decide las tools segun palabras
  clave de la pregunta y arma el informe a partir de lo que devolvieron las tools.

Leccion de la Semana 9 aplicada: para decidir el siguiente paso el mock mira SOLO los
mensajes del turno actual (los posteriores al ultimo HumanMessage), nunca todo el historial.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import uuid
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .datos import cargar_trabajadores
from .schemas import Fuente, Hallazgo, InformeLiquidacion, LineaDescuento

STOPWORDS = set(
    "a al algo como con cual cuales cuando de del el ella ellos en es esta este esto la las le les lo "
    "los mas me mi mis muy no o para pero por que se si sin sobre su sus te tu tus un una uno y ya "
    "son fue ser hay he han ha mes".split()
)


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def tokenizar(texto: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", normalizar(texto))
    salida = []
    for t in toks:
        if t in STOPWORDS or len(t) < 2:
            continue
        if len(t) > 4 and t.endswith("es"):
            t = t[:-2]
        elif len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        salida.append(t)
    return salida


class FakeDeterministicEmbeddings(Embeddings):
    """Embeddings de juguete: hashing de palabras a un vector normalizado."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _vec(self, texto: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in tokenizar(texto):
            h = hashlib.md5(tok.encode()).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            signo = 1.0 if h[4] % 2 == 0 else -1.0
            v[idx] += signo
        norma = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norma for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# ---------------------------------------------------------------- modelo de chat simulado
def _fmt(n: int | float) -> str:
    return f"${int(n):,}".replace(",", ".")


def _json(texto: str) -> dict:
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return {}


def _fragmentos(texto: str) -> list[tuple[str, str]]:
    """Parsea la salida de buscar_en_documentos: [(id_chunk, contenido), ...]."""
    return [(m.group(1).strip(), m.group(2).strip())
            for m in re.finditer(r"\[fuente: ([^\]]+)\]\n(.*?)(?=\n---|\Z)", texto, re.DOTALL)]


class MockLiquidacionChatModel(BaseChatModel):
    """Chat model determinista que imita a un agente que usa las tools del caso."""

    @property
    def _llm_type(self) -> str:
        return "mock-liquidaciones"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "MockLiquidacionChatModel":
        return self

    # --- planificacion ------------------------------------------------------------
    def _plan(self, pregunta: str, sistema: str) -> tuple[str, list[tuple[str, dict]]]:
        q = normalizar(pregunta)
        m = re.search(r"Trabajador autenticado: (.+?) \((W\d+)\)", sistema)
        propio = m.group(2) if m else ""
        for wid, t in cargar_trabajadores().items():
            if wid != propio and normalizar(t["nombre"].split()[0]) in q:
                return "fuera", []
        if re.search(r"companer|colega|jefe|jefa|otro trabajador|otra persona|de otro", q):
            return "fuera", []
        if re.search(r"bono|productividad", q):
            return "bono", [("obtener_liquidacion", {}),
                            ("buscar_en_documentos", {"consulta": "bono de productividad meta de atenciones"})]
        if re.search(r"\buf\b|\butm\b|tope|parametro|valor vigente|ingreso minimo", q):
            return "parametros", [("consultar_parametros", {}),
                                  ("buscar_en_documentos", {"consulta": "tope imponible"})]
        if re.search(r"cesantia", q):
            return "cesantia", [("obtener_liquidacion", {}), ("calcular_descuentos_esperados", {}),
                                ("buscar_en_documentos",
                                 {"consulta": "seguro de cesantía plazo fijo indefinido trabajador"})]
        if re.search(r"mes pasado|agosto|anterior|subio|bajo|aumento", q):
            return "comparar", [("obtener_liquidacion", {}), ("obtener_liquidacion", {"periodo": "2026-08"}),
                                ("calcular_descuentos_esperados", {}),
                                ("buscar_en_documentos", {"consulta": pregunta})]
        if re.search(r"liquidacion|descuent|afp|salud|impuesto|explic|revis|correct|error|liquido|sueldo", q):
            return "explicar", [("obtener_liquidacion", {}), ("calcular_descuentos_esperados", {}),
                                ("buscar_en_documentos", {"consulta": pregunta})]
        return "general", [("buscar_en_documentos", {"consulta": pregunta})]

    # --- generacion ---------------------------------------------------------------
    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        sistema = next((m.content for m in messages if isinstance(m, SystemMessage)), "")
        idx = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        pregunta = str(messages[idx].content)
        turno = messages[idx + 1 :]  # SOLO el turno actual
        llamadas = [tc for m in turno if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
        resultados = [(m.name or "", str(m.content)) for m in turno if isinstance(m, ToolMessage)]

        intencion, plan = self._plan(pregunta, str(sistema))
        if len(llamadas) < len(plan):
            nombre, args = plan[len(llamadas)]
            msg = AIMessage(content="", tool_calls=[
                {"name": nombre, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}])
        else:
            informe = self._componer(intencion, pregunta, resultados)
            msg = AIMessage(content=informe.model_dump_json())
        return ChatResult(generations=[ChatGeneration(message=msg)])

    # --- composicion del informe final ----------------------------------------------
    def _componer(self, intencion: str, pregunta: str, resultados: list[tuple[str, str]]) -> InformeLiquidacion:
        if intencion == "fuera":
            return InformeLiquidacion(
                respuesta=("Solo puedo ayudarte con tu propia liquidación de sueldo. No tengo acceso a "
                           "información de remuneraciones de otras personas, y el Reglamento Interno lo "
                           "prohíbe. Si quieres, te explico tus descuentos."),
                fuera_de_alcance=True, requiere_revision_rrhh=False)

        por_tool: dict[str, list[str]] = {}
        for nombre, contenido in resultados:
            por_tool.setdefault(nombre, []).append(contenido)

        liqs = [_json(c) for c in por_tool.get("obtener_liquidacion", [])]
        liq_data = liqs[0] if liqs else {}
        liq = liq_data.get("liquidacion", {})
        trab = liq_data.get("trabajador", {})
        calc = _json((por_tool.get("calcular_descuentos_esperados") or [""])[0])
        docs = _fragmentos((por_tool.get("buscar_en_documentos") or [""])[0])

        fuentes = [Fuente(tipo="herramienta", referencia=n, detalle="datos calculados o consultados")
                   for n in por_tool if n != "buscar_en_documentos"]
        fuentes += [Fuente(tipo="documento", referencia=cid, detalle=txt.splitlines()[0][:80])
                    for cid, txt in docs[:2]]

        descuentos: list[LineaDescuento] = []
        hallazgos: list[Hallazgo] = []
        filas = {f["codigo"]: f for f in calc.get("lineas", [])}

        if liq and intencion in {"explicar", "cesantia", "comparar"}:
            for d in liq["descuentos_legales"]:
                f = filas.get(d["codigo"], {})
                descuentos.append(LineaDescuento(
                    concepto=d["concepto"], monto=d["monto"],
                    explicacion=self._explicar_linea(d, trab, f), fuente="obtener_liquidacion"))
            for f in calc.get("lineas", []):
                if f["estado"] == "diferencia":
                    sev = "critico" if abs(f["diferencia"]) >= 50_000 else "revisar"
                    hallazgos.append(Hallazgo(
                        severidad=sev,
                        descripcion=f"{f.get('concepto_pagado') or f['concepto']}: se descontó {_fmt(f['pagado'])} y el cálculo esperado es "
                                    f"{_fmt(f['esperado'])}. {f.get('causa_probable') or ''}".strip(),
                        monto_diferencia=f["diferencia"],
                        recomendacion="Puedes enviar la solicitud de revisión a RR.HH. con el botón de abajo. "
                                      "El plazo es de 5 días hábiles desde la entrega de la liquidación."))
                elif f["estado"] == "derivada":
                    hallazgos.append(Hallazgo(
                        severidad="info",
                        descripcion=f"{f['concepto']}: difiere en {_fmt(abs(f['diferencia']))} solo como "
                                    "efecto de la cotización mal descontada.",
                        monto_diferencia=f["diferencia"]))
            g = calc.get("gratificacion", {})
            if g.get("estado") == "diferencia":
                hallazgos.append(Hallazgo(
                    severidad="revisar", descripcion="La gratificación pagada difiere de la esperada.",
                    monto_diferencia=g["diferencia"],
                    recomendacion="Puedes enviar la solicitud de revisión a RR.HH. con el botón de abajo."))

        revisar = any(h.severidad != "info" for h in hallazgos)

        if intencion == "bono":
            atenciones = (liq.get("datos_variables") or {}).get("atenciones_mes")
            bono = next((h for h in liq.get("haberes_imponibles", [])
                         if "bono" in h["concepto"].lower()), None)
            texto_docs = " ".join(t for _, t in docs)
            meta = re.search(r"meta de (\d+) atenciones", texto_docs)
            if bono is None:
                respuesta = ("Tu contrato no tiene un bono de productividad. En tu liquidación solo "
                             "aparecen los haberes pactados.")
            elif bono["monto"] == 0 and atenciones is not None and meta:
                respuesta = (f"Tu bono de productividad de este mes es $0 porque tu anexo exige "
                             f"{meta.group(1)} atenciones en el mes y el sistema registró {atenciones}. "
                             "El bono no es proporcional: si no se llega a la meta, no se paga. Si crees que "
                             "faltan atenciones por registrar, puedes pedir una revisión en 5 días hábiles.")
                hallazgos.append(Hallazgo(
                    severidad="info", descripcion=f"Meta no alcanzada: {atenciones} de {meta.group(1)} atenciones.",
                    recomendacion="Pedir revisión de registros si faltan atenciones cerradas."))
            else:
                respuesta = f"Tu bono de este mes fue {_fmt(bono['monto'])}, según tu anexo de contrato."
            return InformeLiquidacion(respuesta=respuesta, hallazgos=hallazgos, fuentes=fuentes,
                                      requiere_revision_rrhh=False)

        if intencion == "parametros":
            p = _json((por_tool.get("consultar_parametros") or [""])[0])
            respuesta = (f"Valores de referencia: UF {_fmt(p['uf']['valor'])} ({p['uf']['fecha']}), "
                         f"UTM {_fmt(p['utm']['valor'])}, tope imponible AFP/salud "
                         f"{p['topes_uf']['afp_salud']} UF = {_fmt(p['topes_pesos']['afp_salud'])}, "
                         f"ingreso mínimo {_fmt(p['ingreso_minimo']['valor'])}. "
                         "Estos valores se consultan con la tool, no se recuerdan, porque cambian.") \
                if p else "No pude consultar los parámetros."
            return InformeLiquidacion(respuesta=respuesta, fuentes=fuentes, requiere_revision_rrhh=False)

        if intencion == "general":
            respuesta = (docs[0][1].split("\n", 1)[-1][:400] if docs
                         else "No encontré información sobre eso en los documentos disponibles.")
            return InformeLiquidacion(respuesta=respuesta, fuentes=fuentes, requiere_revision_rrhh=False)

        # explicar / cesantia / comparar
        if not liq:
            return InformeLiquidacion(respuesta="No pude obtener tu liquidación.", requiere_revision_rrhh=False)
        respuesta = (f"Tu líquido a pagar de {liq['periodo']} es {_fmt(liq['liquido_a_pagar'])}: "
                     f"{_fmt(liq['total_haberes'])} de haberes menos {_fmt(liq['total_descuentos'])} de descuentos.")
        if intencion == "cesantia":
            sc = next((d for d in descuentos if "cesant" in d.concepto.lower()), None)
            if sc:
                respuesta = f"Seguro de cesantía: {sc.explicacion}"
        if intencion == "comparar" and len(liqs) > 1:
            ant = liqs[1].get("liquidacion", {})
            afp_a = next((d["monto"] for d in ant.get("descuentos_legales", []) if d["codigo"] == "afp"), None)
            afp_h = next((d["monto"] for d in liq["descuentos_legales"] if d["codigo"] == "afp"), None)
            if afp_a is not None and afp_h is not None:
                respuesta += (f" Comparado con {ant['periodo']}: AFP {_fmt(afp_a)} → {_fmt(afp_h)} y líquido "
                              f"{_fmt(ant['liquido_a_pagar'])} → {_fmt(liq['liquido_a_pagar'])}.")
        if revisar:
            respuesta += " Encontré diferencias que conviene que Recursos Humanos revise."
        else:
            respuesta += " Los descuentos coinciden con el cálculo esperado."
        return InformeLiquidacion(respuesta=respuesta, descuentos=descuentos, hallazgos=hallazgos,
                                  fuentes=fuentes, requiere_revision_rrhh=revisar)

    @staticmethod
    def _explicar_linea(d: dict, trab: dict, fila: dict) -> str:
        cod, base, tasa = d["codigo"], d.get("base"), d.get("tasa")
        if cod == "afp":
            txt = (f"10% para tu ahorro previsional más la comisión de la AFP {d.get('institucion', '')} "
                   f"({(tasa or 0) * 100:.2f}% en total) sobre una base de {_fmt(base)}.")
        elif cod == "salud":
            txt = f"7% de la base imponible ({_fmt(base)}) para tu salud ({trab.get('salud', 'Fonasa')})."
        elif cod == "seguro_cesantia":
            if d["monto"] == 0:
                txt = "No aplica: en un contrato a plazo fijo el trabajador no cotiza seguro de cesantía."
            elif fila.get("estado") == "diferencia":
                txt = f"Se descontó el {(tasa or 0) * 100:.1f}% de la base ({_fmt(base)}).".replace(".", ",", 1)
            else:
                txt = (f"{(tasa or 0) * 100:.1f}% de la base ({_fmt(base)}) por tu contrato "
                       f"{trab.get('tipo_contrato', '').replace('_', ' ')}.").replace(".", ",", 1)
        elif cod == "impuesto_unico":
            txt = ("No pagas impuesto: tu renta tributable no supera el mínimo exento."
                   if d["monto"] == 0 else
                   f"Impuesto sobre tu renta tributable de {_fmt(base)} (después de cotizaciones), según la tabla del SII.")
        else:
            txt = "Descuento legal."
        if fila.get("estado") == "diferencia":
            txt += f" ⚠ Difiere del cálculo esperado ({_fmt(fila['esperado'])})."
            if fila.get("causa_probable"):
                txt += " " + fila["causa_probable"]
        return txt
