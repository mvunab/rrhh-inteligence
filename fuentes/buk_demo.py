"""Instancia de demostración de Buk: responde las rutas de la API con datos de data/buk_demo/.

Es un transporte de httpx, así que ClienteBuk recorre el mismo camino que contra Buk:
header auth_token, paginación con pagination.next y el mismo JSON.
"""
from __future__ import annotations

import json
import math
import re

import httpx

from harness.config import DATA_DIR

from .buk import ClienteBuk

DIR_DEMO = DATA_DIR / "buk_demo"
BASE_DEMO = "https://demo.buk.local/api/v1/chile"
TOKEN_DEMO = "demo"


def _leer(nombre: str) -> list[dict]:
    ruta = DIR_DEMO / nombre
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []


def _pagina(request: httpx.Request, datos: list[dict]) -> httpx.Response:
    params = dict(request.url.params)
    tamano = max(1, min(int(params.get("page_size", 25)), 100))
    pagina = max(1, int(params.get("page", 1)))
    total = max(1, math.ceil(len(datos) / tamano))

    def enlace(n: int) -> str | None:
        if n < 1 or n > total:
            return None
        return str(request.url.copy_merge_params({"page": n, "page_size": tamano}))

    return httpx.Response(200, json={
        "pagination": {"next": enlace(pagina + 1), "previous": enlace(pagina - 1),
                       "count": len(datos), "total_pages": total},
        "data": datos[(pagina - 1) * tamano: pagina * tamano],
    })


def _responder(request: httpx.Request) -> httpx.Response:
    if request.headers.get("auth_token") != TOKEN_DEMO:
        return httpx.Response(401, json={"errors": ["Token inválido"]})
    ruta = request.url.path.removeprefix("/api/v1/chile")
    if ruta == "/employees":
        estado = request.url.params.get("status")
        empleados = [e for e in _leer("employees.json") if not estado or e.get("status") == estado]
        return _pagina(request, empleados)
    if m := re.fullmatch(r"/employees/(\d+)", ruta):
        empleado = next((e for e in _leer("employees.json") if e["id"] == int(m.group(1))), None)
        if empleado is None:
            return httpx.Response(404, json={"errors": ["No encontrado"]})
        return httpx.Response(200, json={"data": empleado})
    if ruta == "/payroll_detail/month":
        m = re.fullmatch(r"\d{2}-(\d{2})-(\d{4})", request.url.params.get("date", ""))
        if not m:
            return httpx.Response(400, json={"errors": ["date debe ser DD-MM-YYYY"]})
        return _pagina(request, _leer(f"payroll_{m.group(2)}-{m.group(1)}.json"))
    return httpx.Response(404, json={"errors": [f"Ruta desconocida {ruta}"]})


def cliente_demo() -> ClienteBuk:
    http = httpx.Client(base_url=BASE_DEMO, transport=httpx.MockTransport(_responder),
                        headers={"auth_token": TOKEN_DEMO, "Accept": "application/json"})
    return ClienteBuk(http)


def periodos_demo() -> list[str]:
    return sorted(p.stem.removeprefix("payroll_") for p in DIR_DEMO.glob("payroll_*.json"))
