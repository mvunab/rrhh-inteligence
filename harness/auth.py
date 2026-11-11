"""Contraseñas y tokens de sesión para analistas de RR.HH."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# 14 días. El centro React guarda el token en localStorage.
TTL_SEGUNDOS = 14 * 24 * 3600
DEMO_EMAIL = "analista@clinica.local"
DEMO_PASSWORD = "analista123"


def _secreto() -> str:
    return os.environ.get("AUTH_SECRET") or "rrhh-intelligence-dev-cambia-esto"


def _firmador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secreto(), salt="analista-sesion")


def hash_password(password: str, salt: bytes | None = None) -> str:
    sal = salt or secrets.token_bytes(16)
    digesto = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, 200_000)
    return f"{sal.hex()}${digesto.hex()}"


def verificar_password(password: str, guardado: str) -> bool:
    try:
        sal_hex, digesto_hex = guardado.split("$", 1)
    except ValueError:
        return False
    sal = bytes.fromhex(sal_hex)
    esperado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, 200_000).hex()
    return hmac.compare_digest(esperado, digesto_hex)


def emitir_token(analista_id: str) -> str:
    return _firmador().dumps({"sub": analista_id, "iat": datetime.now(timezone.utc).isoformat()})


def leer_token(token: str) -> str | None:
    """Devuelve el id del analista o None si el token no vale."""
    try:
        datos = _firmador().loads(token, max_age=TTL_SEGUNDOS)
    except (BadSignature, SignatureExpired):
        return None
    sub = datos.get("sub") if isinstance(datos, dict) else None
    return str(sub) if sub else None


def password_demo() -> str:
    return os.environ.get("ANALISTA_PASSWORD", DEMO_PASSWORD)


def email_demo() -> str:
    return os.environ.get("ANALISTA_EMAIL", DEMO_EMAIL)
