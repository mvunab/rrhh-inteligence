#!/usr/bin/env python
"""Exporta el contrato de salida (JSON Schema) desde harness/schemas.py -> agent/output.schema.json."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.schemas import json_schema  # noqa: E402

destino = ROOT / "agent" / "output.schema.json"
destino.write_text(json.dumps(json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Escrito {destino.relative_to(ROOT)}")
