"""Migra la carpeta de trabajo anterior de RR.HH. (JSON + markdown) a la base.

Uso (dentro del contenedor de la API, con la carpeta montada en /rrhh):
    python scripts/migrar_rrhh.py /rrhh --cambios 'anexo_W001_2026-09-01.md={"afp": "ProVida"}'

La carpeta tiene liquidaciones.json, casos.json, contratos.json y documentos/contratos/*.md.
Los anexos anteriores no registraban qué campos cambian; --cambios los agrega por documento.
Es idempotente: volver a correrlo reemplaza lo migrado.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import almacen  # noqa: E402
from rrhh.bandeja import sincronizar_casos  # noqa: E402


def _leer(ruta: Path, defecto):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def _cambios(pares: list[str]) -> dict[str, dict]:
    salida = {}
    for par in pares:
        nombre, _, valor = par.partition("=")
        salida[nombre.strip()] = almacen.validar_cambios(json.loads(valor))
    return salida


def migrar(carpeta: Path, cambios: dict[str, dict]) -> None:
    liquidaciones = _leer(carpeta / "liquidaciones.json", [])
    almacen.guardar_liquidaciones(liquidaciones, "migrado")
    print(f"Liquidaciones: {len(liquidaciones)}")

    registro = _leer(carpeta / "contratos.json", {})
    meta = {}
    for entrada in registro.values():
        for doc in ([entrada["contrato"]] if entrada.get("contrato") else []) + entrada.get("anexos", []):
            meta[doc["archivo"]] = doc
    for ruta in sorted((carpeta / "documentos").rglob("*.md")):
        doc_type, worker_id = almacen.metadata_de_nombre(ruta.name)
        datos = meta.get(ruta.name, {})
        vigente = datos.get("vigente_desde")
        almacen.guardar_documento(
            ruta.name, worker_id, doc_type, ruta.read_text(encoding="utf-8"),
            vigente_desde=date.fromisoformat(vigente) if vigente else None,
            descripcion=datos.get("descripcion", ""),
            cambios=cambios.get(ruta.name),
        )
        print(f"Documento: {ruta.name} ({doc_type}, {worker_id}, vigente desde {vigente}, "
              f"cambios {cambios.get(ruta.name) or '-'})")

    casos = _leer(carpeta / "casos.json", [])
    for caso in casos:
        caso.setdefault("reabierto", False)
        almacen.guardar_caso(caso)
    print(f"Casos: {', '.join(c['id'] for c in casos) or '-'}")

    con_diferencias = sincronizar_casos(liquidaciones)
    print(f"Recalculados contra la ficha vigente. Con diferencias: {', '.join(con_diferencias) or '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("carpeta", type=Path)
    parser.add_argument("--cambios", action="append", default=[], metavar='DOCUMENTO={"campo": valor}')
    args = parser.parse_args()
    migrar(args.carpeta, _cambios(args.cambios))


if __name__ == "__main__":
    main()
