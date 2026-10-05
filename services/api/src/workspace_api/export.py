"""Export generated contracts (OpenAPI document, application-spec JSON Schema).

CI regenerates these and fails if the committed copies differ, so API and
schema changes are always visible in review.

Usage: ``uv run python -m workspace_api.export [--check] [--out contracts]``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from appspec import json_schema_text
from design_system import builtin_contracts, contract_json_schema
from design_system import json_schema as ui_ir_json_schema

from .app import create_app
from .config import Settings


def openapi_text() -> str:
    # Creating the engine does not open a connection, so a placeholder URL is safe here.
    app = create_app(Settings(database_url="postgresql+psycopg://export@localhost/unused"), model_runtime=None)
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def _json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="contracts", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if committed contracts are stale")
    args = parser.parse_args(argv)
    outputs = {
        args.out / "openapi.json": openapi_text(),
        args.out / "application-spec.schema.json": json_schema_text(),
        args.out / "ui-ir.schema.json": _json(ui_ir_json_schema()),
        args.out / "design-system-contract.schema.json": _json(contract_json_schema()),
    }
    for contract in builtin_contracts().values():
        outputs[args.out / "design-systems" / f"{contract.id}.json"] = _json(contract.model_dump(mode="json"))
    stale = []
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print("Stale generated contracts (run `uv run python -m workspace_api.export`):", *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
