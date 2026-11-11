"""Dependencias de autenticación para las rutas de RR.HH."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from harness import almacen
from harness.auth import leer_token


def _token_de(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    # Enlaces <a href> (PDF, plantilla) no mandan Authorization; el token va en la query.
    query = request.query_params.get("token")
    if query:
        return query.strip() or None
    return request.cookies.get("rrhh_token")


def analista_actual(request: Request) -> dict:
    """Analista autenticado. Sin token válido → 401."""
    token = _token_de(request)
    if not token:
        raise HTTPException(401, "Debes iniciar sesión.")
    analista_id = leer_token(token)
    if not analista_id:
        raise HTTPException(401, "La sesión expiró. Vuelve a iniciar sesión.")
    analista = almacen.obtener_analista(analista_id)
    if analista is None:
        raise HTTPException(401, "La sesión ya no es válida.")
    return analista


Analista = Annotated[dict, Depends(analista_actual)]
