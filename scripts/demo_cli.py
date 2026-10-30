#!/usr/bin/env python
"""Prueba rapida del agente por consola.

  python scripts/demo_cli.py --mock --worker W001 "Explícame mi liquidación"
  python scripts/demo_cli.py --worker W003 "Revisa mi liquidación"      # usa .env (Ollama/UNAB)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import Settings  # noqa: E402
from harness.runtime import ejecutar  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta")
    ap.add_argument("--worker", default="W001", help="id del trabajador autenticado (W001..W004)")
    ap.add_argument("--mock", action="store_true", help="LLM y embeddings simulados (sin red)")
    ap.add_argument("--json", action="store_true", help="imprime el informe como JSON")
    args = ap.parse_args()

    cfg = Settings.modo_mock() if args.mock else Settings()
    res = ejecutar(args.worker, args.pregunta, cfg)

    print(f"\n--- traza ({len(res.traza)} llamadas) ---")
    for p in res.traza:
        print(f"{p['paso']}. {p['herramienta']}({p['args']})")
    if not res.ok:
        print("\nSALIDA INVALIDA:", *res.errores, sep="\n  ")
        print(res.crudo)
        raise SystemExit(1)
    print("\n--- informe ---")
    print(json.dumps(res.informe.model_dump(), ensure_ascii=False, indent=2) if args.json else res.informe.respuesta)
    for h in res.informe.hallazgos:
        print(f"  [{h.severidad}] {h.descripcion}")
    for a in res.advertencias:
        print("  GROUNDING:", a)


if __name__ == "__main__":
    main()
