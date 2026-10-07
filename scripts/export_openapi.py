"""Write the API's OpenAPI schema to api/openapi.json (the source for the React TypeScript types).

    python scripts/export_openapi.py
    npx openapi-typescript api/openapi.json -o <react-app>/src/api/schema.d.ts
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.main import create_app  # noqa: E402

OUT = ROOT / "api" / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True,
                              ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
