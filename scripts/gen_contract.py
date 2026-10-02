"""Regenerate contracts/api.openapi.json from the FastAPI app."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "downloader"))

from app.main import contract  # noqa: E402

target = ROOT / "contracts" / "api.openapi.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(contract(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {target}")
