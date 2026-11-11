"""Conector Buk: trabajadores y liquidaciones desde la API REST de Buk Chile.

Con BUK_TOKEN se llama a la API de la empresa (BUK_BASE_URL). Sin token responde una instancia de
demostración con el mismo formato de la API (fuentes/buk_demo.py), por el mismo cliente HTTP.
"""
from __future__ import annotations

import os
import re
from datetime import date

import httpx

from harness.calculos import cargar_parametros, redondear, tope_imponible_pesos

from .protocolo import ErrorCarga, ResultadoCarga

BASE_POR_DEFECTO = "https://demo.buk.cl/api/v1/chile"
_MAX_PAGINAS = 200

AFP_BUK = {
    "uno": "Uno", "modelo": "Modelo", "planvital": "PlanVital", "habitat": "Habitat",
    "capital": "Capital", "cuprum": "Cuprum", "provida": "ProVida",
}
CAMPOS_FICHA_BUK = (
    "nombre", "rut", "cargo", "area", "tipo_contrato", "fecha_inicio", "fecha_termino",
    "afp", "salud", "sueldo_base", "jornada",
)


class ErrorBuk(ErrorCarga):
    """Buk no respondió o rechazó la llamada."""


def token() -> str:
    return os.environ.get("BUK_TOKEN", "").strip()


def base_url() -> str:
    return (os.environ.get("BUK_BASE_URL") or BASE_POR_DEFECTO).rstrip("/")


# ------------------------------------------------------------------ cliente HTTP
class ClienteBuk:
    """GET autenticado con el header auth_token. Sigue pagination.next hasta la última página."""

    tamano_pagina = 100  # el máximo que acepta Buk

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def desde_entorno(cls) -> "ClienteBuk":
        if not token():
            from .buk_demo import cliente_demo
            return cliente_demo()
        return cls(httpx.Client(base_url=base_url(), timeout=30,
                                headers={"auth_token": token(), "Accept": "application/json"}))

    def _get(self, ruta: str, params: dict | None = None) -> dict:
        try:
            respuesta = self._http.get(ruta, params=params)
        except httpx.HTTPError as e:
            raise ErrorBuk(f"No se pudo conectar con Buk: {type(e).__name__}.") from e
        if respuesta.status_code == 401:
            raise ErrorBuk("Buk rechazó el token. Revisa BUK_TOKEN.")
        if respuesta.status_code == 404:
            raise ErrorBuk(f"Buk no encontró {ruta}.")
        if respuesta.status_code >= 400:
            raise ErrorBuk(f"Buk respondió {respuesta.status_code} en {ruta}.")
        return respuesta.json()

    def _todas(self, ruta: str, params: dict) -> list[dict]:
        datos: list[dict] = []
        siguiente: str | None = ruta
        consulta: dict | None = {**params, "page_size": self.tamano_pagina}
        for _ in range(_MAX_PAGINAS):
            cuerpo = self._get(siguiente, consulta)
            datos.extend(cuerpo.get("data") or [])
            siguiente = (cuerpo.get("pagination") or {}).get("next")
            consulta = None  # el enlace next ya trae los parámetros
            if not siguiente:
                return datos
        raise ErrorBuk(f"{ruta} tiene más de {_MAX_PAGINAS} páginas.")

    def empleados(self) -> list[dict]:
        return self._todas("/employees", {"status": "activo"})

    def empleado(self, employee_id: int | str) -> dict:
        cuerpo = self._get(f"/employees/{employee_id}")
        return cuerpo.get("data", cuerpo)

    def liquidaciones(self, periodo: str) -> list[dict]:
        anio, mes = periodo.split("-")
        return self._todas("/payroll_detail/month", {"date": f"01-{mes}-{anio}"})


# ------------------------------------------------------------------ traducción
def _afp(texto: str | None) -> str:
    clave = re.sub(r"^afp\s*", "", (texto or "").strip().lower()).replace(" ", "")
    if clave not in AFP_BUK:
        raise ErrorCarga(f"Buk informa una AFP que no está en los parámetros: {texto!r}.")
    return AFP_BUK[clave]


def _salud(texto: str | None) -> str:
    limpio = (texto or "").strip()
    return "Fonasa" if limpio.lower() == "fonasa" else limpio.title()


def _tipo_contrato(texto: str | None) -> str:
    t = (texto or "").lower()
    if "indefinido" in t:
        return "indefinido"
    if "plazo" in t or "obra" in t or "faena" in t:
        return "plazo_fijo"  # en ambos el trabajador no cotiza seguro de cesantía
    raise ErrorCarga(f"Buk informa un tipo de contrato desconocido: {texto!r}.")


def _fecha(texto: str | None) -> str | None:
    if not texto:
        return None
    texto = str(texto)[:10]
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", texto)
    if m:
        texto = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError as e:
        raise ErrorCarga(f"Buk informa una fecha inválida: {texto!r}.") from e


def ficha_desde_empleado(empleado: dict) -> dict:
    """La ficha del trabajador según Buk. Solo los campos que Buk conoce; worker_id lo asigna el almacén."""
    trabajo = empleado.get("current_job") or {}
    rol = trabajo.get("role")
    if isinstance(rol, dict):
        rol = rol.get("name")
    nombre = empleado.get("full_name") or " ".join(
        p for p in (empleado.get("first_name"), empleado.get("surname"), empleado.get("second_surname")) if p)
    horas = trabajo.get("weekly_hours")
    return {
        "buk_id": empleado["id"],
        "code_sheet": (empleado.get("code_sheet") or "").strip(),
        "nombre": nombre,
        "rut": empleado.get("rut"),
        "cargo": rol or "",
        "area": trabajo.get("main_area_name") or "",
        "tipo_contrato": _tipo_contrato(trabajo.get("contract_type")),
        "fecha_inicio": _fecha(trabajo.get("start_date") or empleado.get("active_since")),
        "fecha_termino": _fecha(trabajo.get("end_date")),
        "afp": _afp(empleado.get("pension_fund")),
        "salud": _salud(empleado.get("health_company")),
        "sueldo_base": redondear(trabajo.get("base_wage") or 0),
        "jornada": f"{horas} horas semanales" if horas else None,
    }


def _clase(linea: dict) -> str:
    tipo = (linea.get("type") or "").lower()
    if tipo in ("haber", "income"):
        return "imponible" if linea.get("imponible") else "no_imponible"
    texto = " ".join(str(linea.get(k) or "") for k in ("subtype", "code", "name")).lower()
    if "cesant" in texto or "afc" in texto:
        return "seguro_cesantia"
    if "impuesto" in texto:
        return "impuesto_unico"
    if "salud" in texto or "fonasa" in texto or "isapre" in texto:
        return "salud"
    if "afp" in texto or "pensi" in texto:
        return "afp"
    return "otro"


def liquidacion_desde_buk(settlement: dict, params: dict | None = None) -> dict:
    """Una liquidación con la forma de data/liquidaciones.json, más el employee_id de Buk."""
    params = params or cargar_parametros()
    periodo = f"{int(settlement['year']):04d}-{int(settlement['month']):02d}"
    imponibles, no_imponibles, otros = [], [], []
    legales: dict[str, list[dict]] = {"afp": [], "salud": [], "seguro_cesantia": [], "impuesto_unico": []}
    for linea in settlement.get("lines_settlement") or []:
        clase = _clase(linea)
        monto = redondear(linea.get("amount") or 0)
        if clase == "imponible":
            imponibles.append({"concepto": linea.get("name") or "Haber", "monto": monto})
        elif clase == "no_imponible":
            no_imponibles.append({"concepto": linea.get("name") or "Haber", "monto": monto})
        elif clase in legales:
            legales[clase].append({**linea, "amount": monto})
        else:
            otros.append({"concepto": linea.get("name") or "Descuento", "monto": monto})
    imponible = sum(h["monto"] for h in imponibles)
    base_prev = redondear(settlement.get("income_afp") or min(imponible, tope_imponible_pesos(params, "afp_salud")))
    base_sc = min(imponible, tope_imponible_pesos(params, "seguro_cesantia"))

    def total(clase: str) -> int:
        return sum(l["amount"] for l in legales[clase])

    def tasa(monto: int, base: int) -> float | None:
        return round(monto / base, 4) if base else None

    lineas_afp = legales["afp"]
    institucion = next((l.get("institution") for l in lineas_afp if l.get("institution")), None)
    if institucion is None and lineas_afp:
        m = re.search(r"AFP\s+(\w+)", lineas_afp[0].get("name") or "")
        institucion = m.group(1) if m else None
    institucion = _afp(institucion) if institucion else ""
    base_trib = redondear(settlement.get("taxable_base")
                          or imponible - total("afp") - total("salud") - total("seguro_cesantia"))
    descuentos = [
        {"codigo": "afp", "concepto": f"AFP {institucion}".strip(), "institucion": institucion,
         "base": base_prev, "tasa": tasa(total("afp"), base_prev), "monto": total("afp")},
        {"codigo": "salud", "concepto": "Salud (Fonasa 7%)", "base": base_prev,
         "tasa": tasa(total("salud"), base_prev), "monto": total("salud")},
        {"codigo": "seguro_cesantia", "concepto": "Seguro de cesantía", "base": base_sc,
         "tasa": tasa(total("seguro_cesantia"), base_sc) or 0.0, "monto": total("seguro_cesantia")},
        {"codigo": "impuesto_unico", "concepto": "Impuesto único 2ª categoría", "base": base_trib,
         "tasa": None, "monto": total("impuesto_unico")},
    ]
    total_haberes = imponible + sum(h["monto"] for h in no_imponibles)
    total_descuentos = sum(d["monto"] for d in descuentos)
    liq = {
        "worker_id": None,
        "periodo": periodo,
        "dias_trabajados": int(settlement.get("worked_days") or 0),
        "haberes_imponibles": imponibles,
        "haberes_no_imponibles": no_imponibles,
        "descuentos_legales": descuentos,
        "total_haberes": total_haberes,
        "total_descuentos": total_descuentos,
        "liquido_a_pagar": total_haberes - total_descuentos,
        "datos_variables": {},
        "buk": {"employee_id": settlement["employee_id"], "liquidacion_id": settlement.get("liquidacion_id"),
                "liquido_buk": settlement.get("liquid_reach")},
    }
    if otros:
        liq["buk"]["otros_descuentos"] = otros
    return liq


# ------------------------------------------------------------------ conector
class BukConector:
    nombre = "Buk"
    disponible = True

    def __init__(self, cliente: ClienteBuk | None = None) -> None:
        self._cliente = cliente

    @property
    def modo(self) -> str:
        return "api" if token() else "demo"

    @property
    def detalle(self) -> str:
        if self.modo == "api":
            return f"Conectado a {base_url().split('/api/')[0]}. Trabajadores y liquidaciones del mes."
        return "Demostración: respuestas de ejemplo con el formato de la API de Buk. Falta BUK_TOKEN."

    def cliente(self) -> ClienteBuk:
        if self._cliente is None:
            self._cliente = ClienteBuk.desde_entorno()
        return self._cliente

    def cargar(self, contenido: bytes = b"", **opciones) -> ResultadoCarga:
        periodo = str(opciones.get("periodo") or "")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", periodo):
            raise ErrorCarga("Indica el mes a traer de Buk como AAAA-MM.")
        cliente = self.cliente()
        fichas = {f["buk_id"]: f for f in map(ficha_desde_empleado, cliente.empleados())}
        params = cargar_parametros()
        liquidaciones = []
        for settlement in cliente.liquidaciones(periodo):
            liq = liquidacion_desde_buk(settlement, params)
            if liq["periodo"] != periodo:
                continue
            eid = liq["buk"]["employee_id"]
            if eid not in fichas:  # p. ej. un finiquitado que tuvo liquidación ese mes
                fichas[eid] = ficha_desde_empleado(cliente.empleado(eid))
            liquidaciones.append(liq)
        return ResultadoCarga(
            origen=self.nombre,
            resumen=f"{len(fichas)} trabajador(es) y {len(liquidaciones)} liquidación(es) de {periodo}",
            liquidaciones=liquidaciones,
            trabajadores=list(fichas.values()),
        )
