#!/usr/bin/env python
"""Evalua el agente (modelo configurado en .env) con 7 casos conocidos y escribe un reporte en reports/.

  python scripts/evaluar.py --mock                 # verifica el harness sin red
  python scripts/evaluar.py                        # usa LLM_PROVIDER / LLM_MODEL del .env
  python scripts/evaluar.py --model qwen3:8b -n 3  # 3 repeticiones por caso (los LLM no son deterministas)
"""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.config import Settings  # noqa: E402
from harness.evaluacion import evaluar, reporte_markdown  # noqa: E402
from harness.ingest import asegurar_indice  # noqa: E402
from harness.llm_factory import crear_embeddings, crear_llm  # noqa: E402
from harness.runtime import ejecutar  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--model", help="sobrescribe LLM_MODEL")
    ap.add_argument("-n", "--repeticiones", type=int, default=1)
    args = ap.parse_args()

    cfg = Settings.modo_mock() if args.mock else Settings()
    if args.model:
        cfg = cfg.con(llm_model=args.model)
    llm = crear_llm(cfg)
    indice = asegurar_indice(crear_embeddings(cfg), cfg)

    resultados = evaluar(lambda w, p: ejecutar(w, p, cfg, llm=llm, indice=indice), args.repeticiones)
    etiqueta = "mock" if args.mock else f"{cfg.llm_provider} {cfg.llm_model}"
    md = reporte_markdown(resultados, f"Evaluación del agente de liquidaciones — {etiqueta} — {date.today()}")
    print(md)
    destino = ROOT / "reports" / f"evaluacion_{re.sub(r'[^a-z0-9]+', '_', etiqueta.lower())}_{date.today()}.md"
    destino.write_text(md, encoding="utf-8")
    print(f"Reporte guardado en {destino.relative_to(ROOT)}")
    raise SystemExit(0 if all(r.ok for r in resultados) else 1)


if __name__ == "__main__":
    main()
